# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Unit tests for the Ruby import resolver (#360).

``extract`` is tested against REAL tree-sitter output over a COMMITTED ``.rb``
fixture mini-repo (skipped without the extra); ``resolve`` is pure path
arithmetic over a supplied file set and runs on every interpreter. Each
``resolve`` case names the UA rule it exercises: ``require_relative``
file-relative anchoring (with ``..`` walk-up), ``require`` load-path resolution
(``lib/`` and repo root), the ``.rb`` probe, and the gem/stdlib drop.

The ``extract`` fixtures are real Ruby source parsed by real tree-sitter
(``real-capture fixtures for external-output matchers``): the matcher is asserted
against the grammar's actual parse, not an invented AST. The ``resolve`` cases
partition the import space (``equivalence partitioning``): file-relative,
load-path-lib, load-path-root, gem-dropped, and the past-root overshoots.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sumo_qa.repo_map_resolvers import get_resolver, registered_languages
from sumo_qa.repo_map_resolvers.base import RawImport
from sumo_qa.repo_map_resolvers.ruby import RubyResolver
from sumo_qa.repo_map_scanner import scan_repo
from sumo_qa.repo_map_treesitter import TREESITTER_AVAILABLE

resolver = RubyResolver()

_FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "repo_map" / "ruby_resolver"


def _fixture_bytes(rel: str) -> bytes:
    return (_FIXTURE_ROOT / rel).read_bytes()


# ---------- registry ----------


def test_ruby_resolver_is_registered():
    assert "ruby" in registered_languages()
    assert get_resolver("ruby") is not None


# ---------- extract (real tree-sitter, committed fixture) ----------

_needs_ts = pytest.mark.skipif(
    not TREESITTER_AVAILABLE,
    reason="tree-sitter not installed (the [treesitter] extra is absent)",
)


@_needs_ts
def test_extract_main_fixture_relative_require_and_gem():
    # main.rb mixes require_relative (level 1, file-relative) and require
    # (level 0, load-path); the gem `json` is still EXTRACTED (it is `resolve`
    # that drops it, not `extract`). The method-local require is flagged lazy.
    raws = {(r.module, r.level): r for r in resolver.extract(_fixture_bytes("main.rb"))}

    assert raws[("models/user", 1)].function_local is False  # module-level require_relative
    assert raws[("helper", 0)].function_local is False  # module-level require (load-path)
    assert ("json", 0) in raws  # gem extracted here; dropped only at resolve time
    assert raws[("lib/util", 1)].function_local is True  # require inside `def boot` -> lazy
    # require carries no specifiers.
    assert all(r.names == () for r in raws.values())


@_needs_ts
def test_extract_skips_interpolated_and_computed_arguments():
    # edge_forms.rb spells require five ways: single-quote, parenthesised, an
    # interpolated string, a non-literal (File.join) argument, and a require
    # nested in a block. Only the three plain string literals are extractable;
    # the interpolated and computed arguments carry no static path -> dropped.
    modules = {
        (r.module, r.level, r.function_local)
        for r in resolver.extract(_fixture_bytes("edge_forms.rb"))
    }
    assert modules == {
        ("lib/single_quote", 0, False),  # single-quoted require
        ("paren_form", 0, False),  # require("paren_form")
        ("blockmod", 1, False),  # require_relative inside a block is not method-local
    }


# ---------- resolve (pure path arithmetic, runs everywhere) ----------


def test_resolve_require_relative_to_sibling():
    # `require_relative "helper"` resolves next to the requiring file.
    imp = RawImport(module="helper", level=1, names=(), function_local=False)
    files = {"lib/app.rb", "lib/helper.rb"}
    assert resolver.resolve("lib/app.rb", imp, files) == ["lib/helper.rb"]


def test_resolve_require_relative_dot_prefix_is_current_dir():
    # A leading `./` is the requiring file's own directory, not a new level.
    imp = RawImport(module="./helper", level=1, names=(), function_local=False)
    files = {"lib/app.rb", "lib/helper.rb"}
    assert resolver.resolve("lib/app.rb", imp, files) == ["lib/helper.rb"]


def test_resolve_require_relative_dotdot_walks_up_one_dir():
    # `require_relative "../shared"` from lib/sub/app.rb anchors at lib/.
    imp = RawImport(module="../shared", level=1, names=(), function_local=False)
    files = {"lib/sub/app.rb", "lib/shared.rb", "lib/sub/shared.rb"}
    assert resolver.resolve("lib/sub/app.rb", imp, files) == ["lib/shared.rb"]


def test_resolve_require_relative_overshoot_above_root_yields_nothing():
    # More `..` than there are ancestor dirs walks past the repo root -> nothing.
    imp = RawImport(module="../shared", level=1, names=(), function_local=False)
    files = {"app.rb", "shared.rb"}
    assert resolver.resolve("app.rb", imp, files) == []


def test_resolve_require_relative_current_dir_only_yields_nothing():
    # `require_relative "."` names the directory, not a file -> no target.
    imp = RawImport(module=".", level=1, names=(), function_local=False)
    files = {"app.rb"}
    assert resolver.resolve("app.rb", imp, files) == []


def test_resolve_require_relative_probes_rb_extension_when_already_present():
    # An explicit `.rb` suffix in the path is probed verbatim, not doubled.
    imp = RawImport(module="util.rb", level=1, names=(), function_local=False)
    files = {"app.rb", "util.rb"}
    assert resolver.resolve("app.rb", imp, files) == ["util.rb"]


def test_resolve_require_resolves_against_lib_load_path():
    # `require "helper"` is load-path relative; lib/ is on the path -> lib/helper.rb.
    imp = RawImport(module="helper", level=0, names=(), function_local=False)
    files = {"app.rb", "lib/helper.rb"}
    assert resolver.resolve("app.rb", imp, files) == ["lib/helper.rb"]


def test_resolve_require_full_path_resolves_against_repo_root():
    # `require "lib/bar"` written from the repo root resolves at the root load
    # path before the lib/ one, so it lands on lib/bar.rb (not lib/lib/bar.rb).
    imp = RawImport(module="lib/bar", level=0, names=(), function_local=False)
    files = {"app.rb", "lib/bar.rb"}
    assert resolver.resolve("app.rb", imp, files) == ["lib/bar.rb"]


def test_resolve_require_gem_or_stdlib_yields_nothing():
    # A require that matches no repo file is a gem/stdlib -> no edge.
    imp = RawImport(module="json", level=0, names=(), function_local=False)
    files = {"app.rb"}
    assert resolver.resolve("app.rb", imp, files) == []


def test_resolve_require_escaping_root_yields_nothing():
    # A load-path require whose path escapes every root resolves to nothing.
    imp = RawImport(module="..", level=0, names=(), function_local=False)
    files = {"app.rb"}
    assert resolver.resolve("app.rb", imp, files) == []


def test_resolve_empty_module_yields_nothing():
    # Defensive: an empty module string (no static path) resolves to nothing.
    imp = RawImport(module="", level=0, names=(), function_local=False)
    files = {"app.rb"}
    assert resolver.resolve("app.rb", imp, files) == []


# ---------- orchestrator integration (real tree-sitter, committed fixture) ----------


@_needs_ts
def test_scan_emits_ruby_import_edges_with_confidence():
    # End-to-end over the committed Ruby fixture mini-repo: scan_repo must emit
    # `imports` edges for the require_relative (file-relative) and require
    # (load-path) targets, tag the method-local require `medium`, and drop the
    # `json` gem (no edge to any non-repo target).
    repo_map = scan_repo(_FIXTURE_ROOT, generator_version="t")
    edges = {(e.source, e.target): e for e in repo_map.edges if e.type == "imports"}

    # require_relative "models/user" -> module-level -> high.
    assert edges[("file:main.rb", "file:models/user.rb")].confidence == "high"
    # require "helper" -> resolved on the lib/ load path -> high.
    assert edges[("file:main.rb", "file:lib/helper.rb")].confidence == "high"
    # require_relative "lib/util" inside `def boot` -> lazy -> medium.
    assert edges[("file:main.rb", "file:lib/util.rb")].confidence == "medium"
    # The `json` gem resolves to no repo file -> no edge.
    assert all("json" not in target for _src, target in edges)
    # Every emitted edge endpoint is a real node (no dangling edges).
    node_ids = {n.id for n in repo_map.nodes}
    for src, target in edges:
        assert src in node_ids
        assert target in node_ids
