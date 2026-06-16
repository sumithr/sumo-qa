# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""HAZARD fixture: ``-m sumo_qa.doctor --help``.

Verbatim shape from ``tests/test_doctor.py``. Doctor now imports the server path
and mutated modules transitively, so spawning it under mutmut crashes the
trampoline. Fixture, not a test (named ``fixture_*.py``).
"""

from __future__ import annotations

import subprocess
import sys


def spawn_doctor_help() -> None:
    subprocess.run(
        [sys.executable, "-m", "sumo_qa.doctor", "--help"],
        capture_output=True,
        text=True,
    )
