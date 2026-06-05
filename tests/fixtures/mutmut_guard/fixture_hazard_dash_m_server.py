# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""HAZARD fixture (false-negative #2): ``-m sumo_qa.server``.

``server.py`` imports ``sumo_qa.knowledge_loaders`` (and ``tdm_validation``) at
top level, so spawning ``python -m sumo_qa.server`` loads a mutated module → the
mutmut trampoline crashes (``KeyError: 'MUTANT_UNDER_TEST'``). The pre-fix guard
only matched the ``-m sumo_qa.ingest`` token, so this and every other
``sumo_qa.<sub>`` mutated-importing entry point escaped detection. Fixture, not a
test (named ``fixture_*.py``).
"""

from __future__ import annotations

import subprocess
import sys


def spawn_server() -> None:
    subprocess.run(
        [sys.executable, "-m", "sumo_qa.server"],
        capture_output=True,
        text=True,
    )
