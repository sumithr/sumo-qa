# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Repo-root conftest for suite-wide test setup.

The ``[tool.pytest.ini_options].pythonpath`` setting in pyproject.toml only
includes ``src``, so packages that live at the repo root (like ``evaluation``)
are not importable by default. This conftest adds the repo root to sys.path
so tests can import them.

It also loads a Hypothesis profile with no per-example deadline. The 200ms
default measures wall-clock time, which a loaded pytest-xdist worker overruns
on correct code; the suite's property tests check behaviour, not speed.
"""

from __future__ import annotations

import sys
from pathlib import Path

from hypothesis import settings

_REPO_ROOT = Path(__file__).resolve().parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

settings.register_profile("sumo-qa", deadline=None)
settings.load_profile("sumo-qa")
