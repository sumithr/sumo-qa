# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""SAFE fixture: ``-m sumo_qa.installer --help``.

Verbatim shape from ``tests/test_installer_mcp_binary.py``. ``installer.py``
imports none of the four mutated modules (verified: neither at import time nor
at CLI runtime), so spawning it is safe under the mutmut trampoline and the
guard must NOT flag it — even though it matches the ``sumo_qa.`` prefix. Proves
the safe-entry-point exemption. Fixture, not a test (named ``fixture_*.py``).
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
