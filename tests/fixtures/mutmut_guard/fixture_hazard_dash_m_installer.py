# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""HAZARD fixture: ``-m sumo_qa.installer --help``.

Verbatim shape from ``tests/test_installer_mcp_binary.py``. Installer now
imports the server path and mutated modules transitively, so spawning it under
mutmut crashes the trampoline. Fixture, not a test (named ``fixture_*.py``).
"""

from __future__ import annotations

import subprocess
import sys


def spawn_installer_help() -> None:
    subprocess.run(
        [sys.executable, "-m", "sumo_qa.installer", "--help"],
        capture_output=True,
        text=True,
    )
