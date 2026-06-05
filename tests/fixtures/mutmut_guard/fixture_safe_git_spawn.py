# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""SAFE fixture: spawns ``git``, not a Python interpreter.

Shape from ``tests/test_cli.py`` / ``test_repo_map_scanner.py``. A ``git`` (or
``pip``-build) subprocess never imports the ``sumo_qa`` package into a fresh
interpreter, so it is not a trampoline hazard and the guard must NOT flag it.
Fixture, not a test (named ``fixture_*.py``).
"""

from __future__ import annotations

import subprocess


def git_init(path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(["git", "add", "-A"], cwd=path, check=True)
