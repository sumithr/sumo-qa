#!/usr/bin/env python3
# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Install sumo-qa from this local checkout, matching the canonical
user-facing install flow but pointing at the local source tree instead
of PyPI.

The canonical user install (from README.md / docs/INSTALL.md) is:

    python -m pip install sumo-qa && python -m sumo_qa.installer --claude-code

This script does the exact same two-step flow with one substitution:
``pip install <repo-root>`` instead of ``pip install sumo-qa``. pip
builds the wheel from the local ``pyproject.toml`` and installs it just
like a PyPI release would, no tags or version bumps required.

Use cases:

- Verify a feature branch in a real-user-shaped install (replaces your
  existing pip-installed sumo-qa with the local build).
- Smoke-test changes to ``installer.py`` or ``doctor.py`` against the
  actual host configs they'd touch on your machine.
- Hand the wheel off to a teammate via ``pip install
  /path/to/their/checkout`` — same flow, no GitHub round-trip.

Reversal: ``pip install --upgrade sumo-qa==<previous-version>`` restores
the PyPI build.

Usage:

    python scripts/dev_install.py                          # full canonical flow
    python scripts/dev_install.py --skip-installer         # only pip install
    python scripts/dev_install.py --claude-code            # only Claude Code host
    python scripts/dev_install.py --vscode --workspace .   # VS Code, this dir
    python scripts/dev_install.py --python /path/to/python # specific interpreter
    python scripts/dev_install.py --no-doctor              # skip post-install smoke

Every flag this script does not consume is passed through to
``sumo-qa-install`` verbatim.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

# Resolve the repo root relative to this script so it works from any cwd.
_REPO_ROOT = Path(__file__).resolve().parent.parent

# Flags this script consumes itself; everything else is passed through to
# ``sumo-qa-install``. Centralised so the help text stays in sync.
_KNOWN_LOCAL_FLAGS = {
    "--python",
    "--skip-installer",
    "--no-doctor",
    "--help",
    "-h",
}


def _run(argv: list[str], *, check: bool = True) -> int:
    """Run a subprocess, echo the command, propagate stdout/stderr."""
    print(f"\n$ {' '.join(argv)}", flush=True)
    result = subprocess.run(argv, check=False)
    if check and result.returncode != 0:
        print(f"\n[dev_install] command failed with exit code {result.returncode}")
        sys.exit(result.returncode)
    return result.returncode


def _resolve_python(requested: str | None) -> str:
    """Pick the Python that will own the new install.

    Default: the same interpreter running this script.

    ``--python`` lets you target a different one — e.g. your pyenv 3.10.3
    when the script itself is running under 3.14 from the worktree venv.
    """
    if requested is None:
        return sys.executable
    resolved = shutil.which(requested) or requested
    if not Path(resolved).exists():
        print(f"[dev_install] --python: cannot find {requested!r}")
        sys.exit(2)
    return resolved


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="dev_install.py",
        description=(
            "Install sumo-qa from this local checkout, matching the canonical "
            "user-facing install flow (pip install + sumo-qa-install)."
        ),
        epilog=(
            "Any flag this script does not consume (e.g. --claude-code, "
            "--vscode, --workspace, --jetbrains, --claude-desktop, "
            "--skip-mcp-install) is passed through to sumo-qa-install."
        ),
        allow_abbrev=False,
    )
    parser.add_argument(
        "--python",
        default=None,
        help=(
            "Python interpreter to install into. Defaults to the one running "
            "this script. Use this to target your pyenv / system Python "
            "rather than the worktree's .venv."
        ),
    )
    parser.add_argument(
        "--skip-installer",
        action="store_true",
        help=(
            "Only run `pip install .` — don't run sumo-qa-install afterward. "
            "Useful when you only want to refresh the wheel + console "
            "scripts, not touch host configs."
        ),
    )
    parser.add_argument(
        "--no-doctor",
        action="store_true",
        help=(
            "Skip the post-install `sumo-qa-doctor` smoke. By default the "
            "script runs doctor at the end so you can confirm the install "
            "is healthy."
        ),
    )
    args, passthrough = parser.parse_known_args(argv)

    for flag in passthrough:
        if flag in _KNOWN_LOCAL_FLAGS:
            print(f"[dev_install] internal error: {flag!r} leaked to passthrough")
            return 2

    python = _resolve_python(args.python)
    print(f"[dev_install] target Python: {python}")
    print(f"[dev_install] repo root:     {_REPO_ROOT}")

    # Step 1: pip install — builds a wheel from the local pyproject and
    # installs it into the target Python. --upgrade so a previously-pinned
    # version gets replaced; --force-reinstall to bypass pip's "already
    # satisfied" short-circuit when the version string hasn't bumped.
    _run(
        [
            python,
            "-m",
            "pip",
            "install",
            "--upgrade",
            "--force-reinstall",
            str(_REPO_ROOT),
        ]
    )

    # Step 2: sumo-qa-install (unless skipped). Use the module form so this
    # works even when the pip Scripts dir isn't on PATH yet — same PATH-proof
    # entry point INSTALL.md documents.
    if not args.skip_installer:
        installer_argv = [python, "-m", "sumo_qa.installer", *passthrough]
        _run(installer_argv)
    elif passthrough:
        print(f"[dev_install] note: --skip-installer set; ignoring passthrough flags {passthrough}")

    # Step 3: sumo-qa-doctor smoke (unless skipped). Module form again for
    # the same reason. Exit code 1 from doctor means a check FAILed — print
    # a hint but don't propagate the non-zero to this script's exit code,
    # so a partial install (e.g. Claude Code OK but VS Code not configured
    # for this workspace) doesn't look like a script failure.
    if not args.no_doctor:
        code = _run(
            [python, "-m", "sumo_qa.doctor"],
            check=False,
        )
        if code == 1:
            print(
                "\n[dev_install] doctor reported FAILs — see output above for the "
                "Fix: commands. Re-run with --no-doctor to skip this step."
            )
        elif code != 0:
            print(f"[dev_install] doctor exited unexpectedly with code {code}")
            return code

    print("\n[dev_install] done.")
    return 0


if __name__ == "__main__":  # pragma: no cover -- script entry
    sys.exit(main())
