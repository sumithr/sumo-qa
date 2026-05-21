#!/usr/bin/env python3
# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Install sumo-qa as a Claude Code plugin from this local checkout.

The canonical user-facing plugin install is:

    claude plugin install sumithr/sumo-qa

That reads from a GitHub-hosted marketplace. To test the plugin install
path against this checkout — without publishing the branch — Claude Code
supports adding a *local* marketplace that points at the local repo:

    1. A marketplace dir with .claude-plugin/marketplace.json
    2. The plugin lives as a subdirectory of that marketplace dir,
       containing .claude-plugin/plugin.json
    3. `claude plugin marketplace add <marketplace-dir>`
    4. `claude plugin install <plugin-name>@<marketplace-name>`

This script sets all that up under ``.claude/local-marketplace/`` (a
gitignored path) with a symlink ``plugins/sumo-qa → <repo-root>``, then
runs the install. Idempotent — re-run after updating the repo to refresh
the plugin's pinned commit SHA.

Cleanup: ``--uninstall`` removes the plugin and the marketplace registration.

Usage:

    python scripts/dev_plugin_install.py            # install / refresh
    python scripts/dev_plugin_install.py --uninstall   # tear down

Why this script exists separately from ``dev_install.py``:

- ``dev_install.py`` mirrors the **pip install** path (canonical PyPI
  flow). After it runs, ``sumo-qa-doctor``'s ``claude_code_config`` check
  validates the host config the pip installer writes.
- ``dev_plugin_install.py`` mirrors the **plugin install** path (Claude
  Code's plugin manager). After it runs, ``claude_code_plugin`` validates
  the entry the plugin manager writes to ``installed_plugins.json``.

The two paths are independent and additive — a real user might use
either, both, or neither. The doctor covers both.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_MARKETPLACE_NAME = "sumo-qa-local"
_PLUGIN_NAME = "sumo-qa"
_MARKETPLACE_DIR = _REPO_ROOT / ".claude" / "local-marketplace"


def _run(argv: list[str], *, check: bool = True) -> int:
    print(f"\n$ {' '.join(argv)}", flush=True)
    result = subprocess.run(argv, check=False)
    if check and result.returncode != 0:
        print(f"\n[dev_plugin_install] command failed with exit code {result.returncode}")
        sys.exit(result.returncode)
    return result.returncode


def _require_claude_cli() -> str:
    """The plugin manager is part of the ``claude`` CLI (Claude Code).
    If the CLI isn't on PATH this script can't do anything useful, so
    error early with an actionable message.
    """
    claude = shutil.which("claude")
    if claude is None:
        print(
            "[dev_plugin_install] `claude` CLI not on PATH. The plugin install "
            "path is a Claude Code feature; install Claude Code (e.g. "
            "https://www.anthropic.com/claude-code) and re-run."
        )
        sys.exit(2)
    return claude


def _build_marketplace() -> None:
    """Materialise the local marketplace at ``.claude/local-marketplace/``.

    Layout:
        .claude/local-marketplace/
            .claude-plugin/marketplace.json
            plugins/
                sumo-qa  ->  <repo-root>  (symlink)

    Idempotent: overwrites marketplace.json, re-points the symlink. We
    re-write the manifest each run so the ``version`` field stays in
    sync with whatever pyproject's `[project] version` is set to.
    """
    _MARKETPLACE_DIR.mkdir(parents=True, exist_ok=True)
    (_MARKETPLACE_DIR / ".claude-plugin").mkdir(exist_ok=True)
    plugins_dir = _MARKETPLACE_DIR / "plugins"
    plugins_dir.mkdir(exist_ok=True)
    plugin_symlink = plugins_dir / _PLUGIN_NAME
    if plugin_symlink.is_symlink() or plugin_symlink.exists():
        plugin_symlink.unlink()
    plugin_symlink.symlink_to(_REPO_ROOT, target_is_directory=True)

    # Read the canonical version from pyproject so the marketplace entry
    # advertises the same version the wheel build would carry.
    version = _read_project_version()

    manifest = {
        "name": _MARKETPLACE_NAME,
        "owner": {"name": "Local Development"},
        "metadata": {
            "description": (
                "Local-development marketplace pointing at this checkout — "
                "used to validate the plugin-install path without publishing."
            ),
            "version": "0.0.0",
        },
        "plugins": [
            {
                "name": _PLUGIN_NAME,
                "description": "Sumo QA — local checkout build, for testing plugin install.",
                "version": version,
                "author": {"name": "Local Development"},
                "source": f"./plugins/{_PLUGIN_NAME}",
            }
        ],
    }
    manifest_path = _MARKETPLACE_DIR / ".claude-plugin" / "marketplace.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"[dev_plugin_install] wrote {manifest_path}")
    print(f"[dev_plugin_install] symlinked {plugin_symlink} -> {_REPO_ROOT}")


def _read_project_version() -> str:
    """Read [project] version from pyproject.toml without taking a TOML dep.

    The canonical line is ``version = "X.Y.Z"``. A grep-based reader keeps
    the script free of an extra runtime dependency (tomli on Py3.10).
    """
    pyproject = _REPO_ROOT / "pyproject.toml"
    for line in pyproject.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("version") and "=" in stripped:
            value = stripped.split("=", 1)[1].strip()
            return value.strip("\"'")
    print(f"[dev_plugin_install] could not find version in {pyproject}")
    sys.exit(2)


def _marketplace_already_registered(claude: str) -> bool:
    result = subprocess.run(
        [claude, "plugin", "marketplace", "list"],
        capture_output=True,
        text=True,
        check=False,
    )
    return _MARKETPLACE_NAME in (result.stdout + result.stderr)


def _verify_plugin_install() -> bool:
    """Verify the plugin install via filesystem reads only — no dependency
    on the sumo_qa Python package being importable.

    This is the parallel of doctor's ``claude_code_plugin`` check, lifted
    out so the script works when ONLY the plugin install path is wired
    (no pip install of sumo-qa). Reads the same files doctor would —
    keeps the two surfaces consistent without sharing code.
    """
    registry = Path.home() / ".claude" / "plugins" / "installed_plugins.json"
    if not registry.exists():
        print(f"[plugin-verify] FAIL — plugin registry not found at {registry}")
        return False
    try:
        data = json.loads(registry.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"[plugin-verify] FAIL — {registry} is not valid JSON ({exc.msg})")
        return False
    plugins = data.get("plugins") if isinstance(data, dict) else None
    if not isinstance(plugins, dict):
        print(f"[plugin-verify] FAIL — {registry} has no `plugins` map")
        return False
    matching = [
        (key, records) for key, records in plugins.items() if key.startswith(f"{_PLUGIN_NAME}@")
    ]
    if not matching:
        print(f"[plugin-verify] FAIL — no {_PLUGIN_NAME}@* entry in plugin registry")
        return False
    key, records = matching[0]
    if not isinstance(records, list) or not records:
        print(f"[plugin-verify] FAIL — {key} has no install records")
        return False
    record = records[0]
    install_path_str = record.get("installPath")
    install_path = Path(install_path_str) if isinstance(install_path_str, str) else None
    if install_path is None or not install_path.exists():
        print(
            f"[plugin-verify] FAIL — {key} installPath "
            f"{install_path_str!r} does not exist (dangling install)"
        )
        return False
    plugin_manifest = install_path / ".claude-plugin" / "plugin.json"
    if not plugin_manifest.exists():
        print(f"[plugin-verify] FAIL — plugin manifest {plugin_manifest} not found")
        return False
    version = record.get("version", "unknown")
    sha = record.get("gitCommitSha", "")
    sha_short = sha[:7] if isinstance(sha, str) and sha else "no-sha"
    print(f"[plugin-verify] OK — {key} v{version} registered (commit {sha_short})")
    print(f"[plugin-verify]    installPath: {install_path}")
    return True


def _maybe_run_full_doctor(python: str) -> None:
    """Run the full ``sumo-qa-doctor`` smoke ONLY when the Python package
    is importable. The dev_install.py script handles the pip-install path
    that puts ``sumo_qa`` on disk; if the user is testing the plugin path
    in isolation, ``import sumo_qa`` will fail and we surface that as a
    clear note rather than crashing.
    """
    probe = subprocess.run(
        [python, "-c", "import sumo_qa.doctor"],
        capture_output=True,
        check=False,
    )
    if probe.returncode != 0:
        print()
        print(
            "[dev_plugin_install] note: the `sumo_qa` Python package is not "
            "installed in the active interpreter. The plugin install "
            "registers skills + hooks + MCP-server configuration, but the "
            "MCP server itself runs the `sumo-qa` binary from the wheel — "
            "install that separately with `python scripts/dev_install.py` "
            "(or `pip install sumo-qa`) for a fully functional setup."
        )
        return
    print()
    print("[dev_plugin_install] sumo_qa package available — running full doctor:")
    _run([python, "-m", "sumo_qa.doctor", "--host", "claude-code"], check=False)


def install(claude: str) -> None:
    _build_marketplace()
    if _marketplace_already_registered(claude):
        print(
            f"[dev_plugin_install] marketplace {_MARKETPLACE_NAME!r} already registered; refreshing."
        )
        _run([claude, "plugin", "marketplace", "update", _MARKETPLACE_NAME])
    else:
        _run([claude, "plugin", "marketplace", "add", str(_MARKETPLACE_DIR)])
    _run([claude, "plugin", "install", f"{_PLUGIN_NAME}@{_MARKETPLACE_NAME}"])

    # First: filesystem-based plugin-install verification. Works even when
    # the sumo_qa Python package isn't installed — reads the same registry
    # the doctor's claude_code_plugin check inspects.
    print()
    if not _verify_plugin_install():
        sys.exit(2)
    # Then: optionally run the full Python doctor for the hybrid case
    # (user has both plugin install and pip install).
    _maybe_run_full_doctor(sys.executable)


def uninstall(claude: str) -> None:
    # Uninstall the plugin first (failure here is tolerated — it may not
    # be installed), then remove the marketplace registration.
    _run(
        [claude, "plugin", "uninstall", f"{_PLUGIN_NAME}@{_MARKETPLACE_NAME}"],
        check=False,
    )
    if _marketplace_already_registered(claude):
        _run([claude, "plugin", "marketplace", "remove", _MARKETPLACE_NAME])
    if _MARKETPLACE_DIR.exists():
        shutil.rmtree(_MARKETPLACE_DIR)
        print(f"[dev_plugin_install] removed {_MARKETPLACE_DIR}")
    print("[dev_plugin_install] uninstall complete.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="dev_plugin_install.py",
        description=(
            "Install sumo-qa as a Claude Code plugin from this local checkout, "
            "using a temporary local marketplace under .claude/local-marketplace/."
        ),
    )
    parser.add_argument(
        "--uninstall",
        action="store_true",
        help=(
            "Uninstall the plugin and remove the local marketplace registration. "
            "Useful for cleanup after testing or before switching branches."
        ),
    )
    args = parser.parse_args(argv)

    claude = _require_claude_cli()
    if args.uninstall:
        uninstall(claude)
    else:
        install(claude)
    return 0


if __name__ == "__main__":  # pragma: no cover -- script entry
    sys.exit(main())
