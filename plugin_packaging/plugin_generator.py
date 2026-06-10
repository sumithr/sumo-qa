# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Plugin packaging generator — single CLI for host-neutral adapter emission.

Modes:
  sync   — read pyproject.toml, write every plugin folder + snapshot + sidecar
  check  — re-run sync into memory, diff every output against on-disk,
           verify SHA256 sidecar matches; exit non-zero on any drift

Deterministic output: sorted JSON keys, indent=2, trailing newline, POSIX
paths. No network. No reading skill bodies (the only file under skills/
this generator touches is pyproject.toml's overlay).

Wired to CI via .github/workflows/plugin-packaging.yml and to local
pre-commit via .pre-commit-config.yaml.
"""

from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import sys
from dataclasses import dataclass
from pathlib import Path

from plugin_packaging.canonical import CanonicalPlugin, load
from plugin_packaging.templates import (
    claude_code,
    codex,
    hooks,
    host_adapters_doc,
    mcp,
)


@dataclass(frozen=True)
class Output:
    relpath: str  # POSIX, repo-root relative
    payload: bytes


def _json_bytes(data: object) -> bytes:
    return (json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")


def _md_bytes(text: str) -> bytes:
    if not text.endswith("\n"):
        text += "\n"
    return text.encode("utf-8")


def _snapshot(plugin: CanonicalPlugin) -> dict:
    """Frozen runtime snapshot consumed by src/sumo_qa/plugin_metadata.py.

    Records ONLY logical metadata — no paths. Paths are resolved at runtime
    by installer._detect_install_mode and friends.
    """
    return {
        "name": plugin.name,
        "version": plugin.version,
        "description": plugin.description,
        "license": plugin.license,
        "author": plugin.author,
        "homepage": plugin.homepage,
        "repository": plugin.repository,
        "display_name": plugin.display_name,
        "short_description": plugin.short_description,
        "long_description": plugin.long_description,
        "category": plugin.category,
        "keywords": list(plugin.keywords),
        "mcp": {
            "server_name": plugin.mcp.server_name,
            "command": plugin.mcp.command,
            "transport": plugin.mcp.transport,
            "args": list(plugin.mcp.args),
        },
    }


def _build_outputs(plugin: CanonicalPlugin) -> list[Output]:
    return [
        Output(".claude-plugin/plugin.json", _json_bytes(claude_code.render(plugin))),
        Output(".codex-plugin/plugin.json", _json_bytes(codex.render(plugin))),
        Output(".mcp.json", _json_bytes(mcp.render(plugin))),
        Output("hooks/hooks.json", _json_bytes(hooks.render_claude_code(plugin))),
        Output("hooks/hooks-codex.json", _json_bytes(hooks.render_codex(plugin))),
        Output("docs/host-adapters.md", _md_bytes(host_adapters_doc.render(plugin))),
        Output("src/sumo_qa/_data/plugin_metadata.json", _json_bytes(_snapshot(plugin))),
    ]


def _sidecar_bytes(outputs: list[Output]) -> bytes:
    sidecar = {
        "generator": "plugin_packaging.plugin_generator",
        "files": {o.relpath: hashlib.sha256(o.payload).hexdigest() for o in outputs},
    }
    return _json_bytes(sidecar)


def sync(repo_root: Path) -> int:
    plugin = load(repo_root / "pyproject.toml")
    outputs = _build_outputs(plugin)
    for out in outputs:
        target = repo_root / out.relpath
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(out.payload)
    sidecar_target = repo_root / "plugin_packaging" / "generated" / "manifest.json"
    sidecar_target.parent.mkdir(parents=True, exist_ok=True)
    sidecar_target.write_bytes(_sidecar_bytes(outputs))
    return 0


def check(repo_root: Path) -> int:
    plugin = load(repo_root / "pyproject.toml")
    expected = _build_outputs(plugin)
    expected_sidecar = _sidecar_bytes(expected)

    drift: list[str] = []
    for out in expected:
        on_disk_path = repo_root / out.relpath
        if not on_disk_path.is_file():
            drift.append(f"MISSING: {out.relpath}")
            continue
        on_disk = on_disk_path.read_bytes()
        if on_disk != out.payload:
            diff = "\n".join(
                difflib.unified_diff(
                    on_disk.decode("utf-8", "replace").splitlines(),
                    out.payload.decode("utf-8", "replace").splitlines(),
                    fromfile=f"a/{out.relpath}",
                    tofile=f"b/{out.relpath}",
                    lineterm="",
                )
            )
            drift.append(f"DRIFT: {out.relpath}\n{diff}")

    sidecar_path = repo_root / "plugin_packaging" / "generated" / "manifest.json"
    if not sidecar_path.is_file() or sidecar_path.read_bytes() != expected_sidecar:
        drift.append("DRIFT: plugin_packaging/generated/manifest.json")

    if drift:
        sys.stderr.write("\n".join(drift) + "\n")
        sys.stderr.write(
            "\nFix: run `python -m plugin_packaging.plugin_generator sync` and commit the result.\n"
        )
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="plugin_packaging.plugin_generator",
        description="Generate host-neutral plugin folders from pyproject.toml",
    )
    parser.add_argument("mode", choices=("sync", "check"))
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="Repository root (default: parent of plugin_packaging/).",
    )
    args = parser.parse_args(argv)
    if args.mode == "sync":
        return sync(args.repo_root)
    return check(args.repo_root)


if __name__ == "__main__":
    raise SystemExit(main())
