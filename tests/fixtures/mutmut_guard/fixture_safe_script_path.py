# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""SAFE fixture: spawns a standalone hook *script path*, not ``-m sumo_qa``.

Shape from ``tests/test_route_qa_runners.py`` / ``test_claude_hooks.py`` /
``test_session_start_hook.py``. The hook scripts do not import the ``sumo_qa``
package, so launching them with ``sys.executable`` is not a mutated-module spawn
and the guard must NOT flag it. Fixture, not a test (named ``fixture_*.py``).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

HOOK = Path(__file__).resolve().parent / "some_hook.py"


def run_hook() -> None:
    subprocess.run(
        [sys.executable, str(HOOK)],
        capture_output=True,
        text=True,
    )
