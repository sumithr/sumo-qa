# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Host-schema validation gate for generated plugin folders.

Three checks (all run by default):

  - .claude-plugin/plugin.json against vendored claude-code-plugin-manifest.json
  - .claude-plugin/marketplace.json against vendored claude-code-marketplace.json
  - hooks/hooks-codex.json against vendored codex-hooks.json

The Codex plugin manifest itself has no published schema — that surface
is validated by the install-smoke MCP-handshake matrix instead.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import jsonschema

REPO_ROOT_DEFAULT = Path(__file__).resolve().parents[1]
_SCHEMAS_DIR = Path(__file__).resolve().parent / "schemas"


class SchemaValidationError(ValueError):
    """Raised when a generated plugin file fails its host schema."""


def _validate(json_path: Path, schema_path: Path) -> None:
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    data = json.loads(json_path.read_text(encoding="utf-8"))
    try:
        jsonschema.validate(data, schema)
    except jsonschema.ValidationError as exc:
        raise SchemaValidationError(
            f"{json_path.name} fails schema {schema_path.name}: {exc.message}"
        ) from exc


def validate_claude_code(repo_root: Path) -> None:
    _validate(
        repo_root / ".claude-plugin" / "plugin.json",
        _SCHEMAS_DIR / "claude-code-plugin-manifest.json",
    )


def validate_marketplace(repo_root: Path) -> None:
    _validate(
        repo_root / ".claude-plugin" / "marketplace.json",
        _SCHEMAS_DIR / "claude-code-marketplace.json",
    )


def validate_codex_hooks(repo_root: Path) -> None:
    _validate(
        repo_root / "hooks" / "hooks-codex.json",
        _SCHEMAS_DIR / "codex-hooks.json",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="plugin_packaging.validate_plugins",
        description="Validate generated plugin folders against vendored host schemas.",
    )
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT_DEFAULT)
    args = parser.parse_args(argv)
    try:
        validate_claude_code(args.repo_root)
        validate_marketplace(args.repo_root)
        validate_codex_hooks(args.repo_root)
    except SchemaValidationError as exc:
        sys.stderr.write(f"schema validation failed: {exc}\n")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
