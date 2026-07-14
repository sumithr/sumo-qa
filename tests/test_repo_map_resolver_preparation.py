# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Tests for scan-local resolver preparation (#484 foundation, #358 Rust slice).

Covers the preparation lifecycle contract: the typed ``prepare`` hook runs once
per scan and yields a scan-local resolver (the registered singleton is never
mutated with repository data); prepared state cannot leak between sequential or
concurrent scans; the per-scan :class:`ScanContext` gives bounded, memoized
source reads (no unbounded second repository read); and missing, malformed, or
unreadable Cargo.toml input degrades to path-only resolution with one
deterministic ``other`` warning per affected config instead of aborting the
scan.

Preparation parses real source with tree-sitter, so scan-shaped tests carry the
same skip gate as the resolver suites; the :class:`ScanContext` unit tests are
pure IO and run everywhere.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from sumo_qa.repo_map_imports import infer_imports_edges
from sumo_qa.repo_map_models import RepoMapNode, RepoMapWarning
from sumo_qa.repo_map_resolvers import base as resolvers_base
from sumo_qa.repo_map_resolvers import get_resolver
from sumo_qa.repo_map_resolvers.base import (
    LanguageConfig,
    RawImport,
    ScanContext,
)
from sumo_qa.repo_map_scanner import scan_repo
from sumo_qa.repo_map_treesitter import TREESITTER_AVAILABLE

_needs_ts = pytest.mark.skipif(
    not TREESITTER_AVAILABLE,
    reason="tree-sitter not installed (the [treesitter] extra is absent)",
)

# The bare-import discriminator pair: `use foo::sub::Item;` in main.rs reaches
# src/foo/sub.rs ONLY through provable bare current-scope resolution (`mod foo;`
# gives main.rs -> foo.rs, never the deeper sub.rs).
_BARE_PAIR = ("file:src/main.rs", "file:src/foo/sub.rs")
_MOD_PAIR = ("file:src/main.rs", "file:src/foo.rs")

_EDITION_2021_CARGO = '[package]\nname = "x"\nversion = "0.1.0"\nedition = "2021"\n'


def _write(root: Path, rel: str, text: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _bare_repo(root: Path, cargo: str | None = _EDITION_2021_CARGO) -> None:
    """A minimal crate whose bare import discriminates prepared resolution."""
    if cargo is not None:
        _write(root, "Cargo.toml", cargo)
    _write(root, "src/main.rs", "mod foo;\nuse foo::sub::Item;\nfn main() {}\n")
    _write(root, "src/foo.rs", "pub mod sub;\n")
    _write(root, "src/foo/sub.rs", "pub struct Item;\n")


def _pairs(repo_map) -> set[tuple[str, str]]:
    return {(e.source, e.target) for e in repo_map.edges if e.type == "imports"}


# ---------- ScanContext: bounded, memoized per-scan source reads ----------


def test_scan_context_read_is_bounded_and_memoized(tmp_path: Path, monkeypatch):
    # A file over the bound is truncated to the bound; a second read of the
    # same path must come from the cache, not a second disk read.
    big = b"x" * 2_000_100
    (tmp_path / "big.rs").write_bytes(big)
    opens: list[str] = []
    real_open = Path.open

    def counting_open(self, *args, **kwargs):
        opens.append(self.name)
        return real_open(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", counting_open)
    context = ScanContext(root=tmp_path, files=frozenset({"big.rs"}))
    first = context.read("big.rs")
    second = context.read("big.rs")
    assert first is not None and len(first) == 2_000_000
    assert second == first
    assert opens.count("big.rs") == 1


def test_scan_context_read_missing_file_is_none_and_memoized(tmp_path: Path):
    context = ScanContext(root=tmp_path, files=frozenset())
    assert context.read("absent.rs") is None
    assert context.read("absent.rs") is None


def test_scan_context_consume_evicts_the_prepared_bytes(tmp_path: Path, monkeypatch):
    # consume() after a prepare-time read serves the cached bytes and evicts
    # them (the orchestrator visits each node once); a later consume re-reads.
    (tmp_path / "a.rs").write_bytes(b"mod x;\n")
    opens: list[str] = []
    real_open = Path.open

    def counting_open(self, *args, **kwargs):
        opens.append(self.name)
        return real_open(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", counting_open)
    context = ScanContext(root=tmp_path, files=frozenset({"a.rs"}))
    assert context.read("a.rs") == b"mod x;\n"
    assert opens.count("a.rs") == 1
    assert context.consume("a.rs") == b"mod x;\n"
    assert opens.count("a.rs") == 1  # served from cache
    assert context.consume("a.rs") == b"mod x;\n"
    assert opens.count("a.rs") == 2  # evicted: this one re-reads disk


def test_scan_context_consume_without_prior_read_does_not_retain(tmp_path: Path, monkeypatch):
    # A consume with no prepare-time read goes straight to disk both times —
    # the cache only ever holds what preparation actually read.
    (tmp_path / "b.rs").write_bytes(b"mod y;\n")
    opens: list[str] = []
    real_open = Path.open

    def counting_open(self, *args, **kwargs):
        opens.append(self.name)
        return real_open(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", counting_open)
    context = ScanContext(root=tmp_path, files=frozenset({"b.rs"}))
    assert context.consume("b.rs") == b"mod y;\n"
    assert context.consume("b.rs") == b"mod y;\n"
    assert opens.count("b.rs") == 2


def test_scan_context_warn_config_dedupes_per_config(tmp_path: Path):
    warnings: list[RepoMapWarning] = []
    context = ScanContext(root=tmp_path, files=frozenset(), warnings=warnings)
    context.warn_config("bad config", "Cargo.toml")
    context.warn_config("bad config", "Cargo.toml")
    context.warn_config("bad config", "crates/a/Cargo.toml")
    assert [(w.kind, w.message, w.path) for w in warnings] == [
        ("other", "bad config", "Cargo.toml"),
        ("other", "bad config", "crates/a/Cargo.toml"),
    ]


def test_scan_context_warn_config_tolerates_missing_warning_list(tmp_path: Path):
    context = ScanContext(root=tmp_path, files=frozenset())
    context.warn_config("bad config", "Cargo.toml")  # must not raise


# ---------- preparation lifecycle: once per scan, scan-local instance ----------


_FAKE_CONFIG = LanguageConfig(id="fakelang", extensions=(".fake",))


class _PreparedFake:
    config = _FAKE_CONFIG

    def __init__(self) -> None:
        self.extract_calls = 0

    def extract(self, src: bytes) -> list[RawImport]:
        self.extract_calls += 1
        return []

    def resolve(self, importer: str, imp: RawImport, file_set: set[str]) -> list[str]:
        return []


class _PreparableFake:
    config = _FAKE_CONFIG

    def __init__(self) -> None:
        self.prepare_calls = 0
        self.extract_calls = 0
        self.prepared = _PreparedFake()
        self.last_context: ScanContext | None = None

    def extract(self, src: bytes) -> list[RawImport]:
        self.extract_calls += 1
        return []

    def resolve(self, importer: str, imp: RawImport, file_set: set[str]) -> list[str]:
        return []

    def prepare(self, context: ScanContext) -> _PreparedFake:
        self.prepare_calls += 1
        self.last_context = context
        return self.prepared


class _PlainFake:
    config = _FAKE_CONFIG

    def __init__(self) -> None:
        self.extract_calls = 0

    def extract(self, src: bytes) -> list[RawImport]:
        self.extract_calls += 1
        return []

    def resolve(self, importer: str, imp: RawImport, file_set: set[str]) -> list[str]:
        return []


def _fake_nodes(paths: list[str]) -> list[RepoMapNode]:
    return [
        RepoMapNode(
            id=f"file:{path}",
            type="source_file",
            path=path,
            language="fakelang",
            fingerprint=None,
        )
        for path in paths
    ]


@_needs_ts
def test_prepare_runs_once_per_scan_and_extraction_uses_the_prepared_instance(
    tmp_path: Path, monkeypatch
):
    _write(tmp_path, "a.fake", "x")
    _write(tmp_path, "b.fake", "y")
    fake = _PreparableFake()
    monkeypatch.setitem(resolvers_base._REGISTRY, "fakelang", fake)
    infer_imports_edges(_fake_nodes(["a.fake", "b.fake"]), tmp_path)
    assert fake.prepare_calls == 1  # one preparation per scan, not per node
    assert fake.extract_calls == 0  # the singleton never sees repository data
    assert fake.prepared.extract_calls == 2  # both nodes use the prepared instance
    assert fake.last_context is not None
    assert fake.last_context.files == frozenset({"a.fake", "b.fake"})


@_needs_ts
def test_resolver_without_prepare_is_used_directly(tmp_path: Path, monkeypatch):
    _write(tmp_path, "a.fake", "x")
    fake = _PlainFake()
    monkeypatch.setitem(resolvers_base._REGISTRY, "fakelang", fake)
    infer_imports_edges(_fake_nodes(["a.fake"]), tmp_path)
    assert fake.extract_calls == 1  # path-only resolvers keep the existing contract


@_needs_ts
def test_scan_preparation_never_mutates_the_registered_rust_singleton(tmp_path: Path):
    _bare_repo(tmp_path)
    repo_map = scan_repo(tmp_path, generator_version="t")
    assert _BARE_PAIR in _pairs(repo_map)  # the prepared scan resolves the bare import
    singleton = get_resolver("rust")
    assert singleton is not None
    bare = RawImport(module="self::foo::sub::Item", level=2, names=(), function_local=False)
    files = {"Cargo.toml", "src/main.rs", "src/foo.rs", "src/foo/sub.rs"}
    # The registered singleton stays path-only: without scan-local context it
    # must keep dropping bare imports even right after a context-rich scan.
    assert singleton.resolve("src/main.rs", bare, files) == []


# ---------- isolation: sequential and concurrent scans share nothing ----------


@_needs_ts
def test_sequential_scans_do_not_share_prepared_state(tmp_path: Path):
    repo_a = tmp_path / "a"
    repo_b = tmp_path / "b"
    _bare_repo(repo_a)
    _bare_repo(repo_b, cargo=None)  # no Cargo.toml: normal path-only fallback
    map_a_first = scan_repo(repo_a, generator_version="t")
    map_b = scan_repo(repo_b, generator_version="t")
    map_a_second = scan_repo(repo_a, generator_version="t")
    assert _BARE_PAIR in _pairs(map_a_first)
    # Repo A's edition context must not leak into repo B's scan...
    assert _BARE_PAIR not in _pairs(map_b)
    assert _MOD_PAIR in _pairs(map_b)  # ...which still resolves path-only edges
    # ...and repo B's scan must leave no residue that changes repo A.
    assert _pairs(map_a_second) == _pairs(map_a_first)


@_needs_ts
def test_concurrent_scans_use_isolated_preparation(tmp_path: Path):
    repo_a = tmp_path / "a"
    repo_b = tmp_path / "b"
    _bare_repo(repo_a)
    _bare_repo(repo_b, cargo=None)
    with ThreadPoolExecutor(max_workers=2) as pool:
        future_a = pool.submit(scan_repo, repo_a, generator_version="t")
        future_b = pool.submit(scan_repo, repo_b, generator_version="t")
        map_a = future_a.result()
        map_b = future_b.result()
    assert _BARE_PAIR in _pairs(map_a)
    assert _BARE_PAIR not in _pairs(map_b)
    assert _MOD_PAIR in _pairs(map_b)


# ---------- config degradation: missing / malformed / unreadable ----------


@_needs_ts
def test_malformed_cargo_toml_degrades_with_one_deterministic_other_warning(tmp_path: Path):
    _bare_repo(tmp_path, cargo="not = [valid toml\n")
    repo_map = scan_repo(tmp_path, generator_version="t")
    # The scan completes and path-only edges still stand; only the bare
    # (context-dependent) edge is withheld.
    assert _MOD_PAIR in _pairs(repo_map)
    assert _BARE_PAIR not in _pairs(repo_map)
    others = [w for w in repo_map.warnings if w.kind == "other"]
    assert len(others) == 1
    assert others[0].path == "Cargo.toml"
    # Deterministic: a second scan of the same state emits the identical warning.
    again = scan_repo(tmp_path, generator_version="t")
    assert [(w.kind, w.message, w.path) for w in again.warnings] == [
        (w.kind, w.message, w.path) for w in repo_map.warnings
    ]


@_needs_ts
def test_non_utf8_cargo_toml_degrades_with_one_other_warning(tmp_path: Path):
    _bare_repo(tmp_path, cargo=None)
    (tmp_path / "Cargo.toml").write_bytes(b"\xff\xfe[package]\n")
    repo_map = scan_repo(tmp_path, generator_version="t")
    assert _MOD_PAIR in _pairs(repo_map)
    assert _BARE_PAIR not in _pairs(repo_map)
    others = [w for w in repo_map.warnings if w.kind == "other"]
    assert len(others) == 1
    assert others[0].path == "Cargo.toml"


@_needs_ts
def test_unreadable_cargo_toml_degrades_with_one_other_warning(tmp_path: Path, monkeypatch):
    _bare_repo(tmp_path)
    real_read = ScanContext.read

    def failing_read(self, rel_path: str):
        if rel_path == "Cargo.toml":
            return None  # simulate an unreadable config portably (no chmod on Windows)
        return real_read(self, rel_path)

    monkeypatch.setattr(ScanContext, "read", failing_read)
    repo_map = scan_repo(tmp_path, generator_version="t")
    assert _MOD_PAIR in _pairs(repo_map)
    assert _BARE_PAIR not in _pairs(repo_map)
    others = [w for w in repo_map.warnings if w.kind == "other"]
    assert len(others) == 1
    assert others[0].path == "Cargo.toml"


# ---------- edition gating: uniform paths must be provable ----------


@_needs_ts
@pytest.mark.parametrize("edition", ["2018", "2021", "2024"])
def test_uniform_path_editions_enable_bare_resolution(tmp_path: Path, edition: str):
    _bare_repo(tmp_path, cargo=f'[package]\nname = "x"\nedition = "{edition}"\n')
    repo_map = scan_repo(tmp_path, generator_version="t")
    assert _BARE_PAIR in _pairs(repo_map)
    assert not [w for w in repo_map.warnings if w.kind == "other"]


@_needs_ts
@pytest.mark.parametrize(
    "cargo",
    [
        '[package]\nname = "x"\nedition = "2015"\n',
        '[package]\nname = "x"\n',  # edition key absent: Cargo defaults to 2015
    ],
)
def test_pre_uniform_or_unknown_edition_keeps_bare_paths_external(tmp_path: Path, cargo: str):
    _bare_repo(tmp_path, cargo=cargo)
    repo_map = scan_repo(tmp_path, generator_version="t")
    assert _MOD_PAIR in _pairs(repo_map)
    assert _BARE_PAIR not in _pairs(repo_map)
    # A well-formed pre-2018 Cargo.toml is a normal fallback, not a warning.
    assert not [w for w in repo_map.warnings if w.kind == "other"]


@_needs_ts
def test_workspace_inherited_edition_enables_bare_resolution(tmp_path: Path):
    _write(
        tmp_path,
        "Cargo.toml",
        '[workspace]\nmembers = ["crates/app"]\n\n[workspace.package]\nedition = "2021"\n',
    )
    _write(tmp_path, "crates/app/Cargo.toml", '[package]\nname = "app"\nedition.workspace = true\n')
    _bare_repo(tmp_path / "crates" / "app", cargo=None)
    repo_map = scan_repo(tmp_path, generator_version="t")
    pairs = _pairs(repo_map)
    assert ("file:crates/app/src/main.rs", "file:crates/app/src/foo/sub.rs") in pairs


@_needs_ts
def test_workspace_without_edition_stays_conservative(tmp_path: Path):
    _write(tmp_path, "Cargo.toml", '[workspace]\nmembers = ["crates/app"]\n')
    _write(tmp_path, "crates/app/Cargo.toml", '[package]\nname = "app"\nedition.workspace = true\n')
    _bare_repo(tmp_path / "crates" / "app", cargo=None)
    repo_map = scan_repo(tmp_path, generator_version="t")
    pairs = _pairs(repo_map)
    assert ("file:crates/app/src/main.rs", "file:crates/app/src/foo/sub.rs") not in pairs
    assert ("file:crates/app/src/main.rs", "file:crates/app/src/foo.rs") in pairs


@_needs_ts
def test_nearest_cargo_toml_governs_each_importer(tmp_path: Path):
    # Root package pins edition 2015; a nested package pins 2021. Each
    # importer's bare imports follow its OWN nearest manifest.
    _bare_repo(tmp_path, cargo='[package]\nname = "outer"\nedition = "2015"\n')
    _bare_repo(tmp_path / "sub", cargo='[package]\nname = "inner"\nedition = "2021"\n')
    repo_map = scan_repo(tmp_path, generator_version="t")
    pairs = _pairs(repo_map)
    assert ("file:sub/src/main.rs", "file:sub/src/foo/sub.rs") in pairs
    assert _BARE_PAIR not in pairs
