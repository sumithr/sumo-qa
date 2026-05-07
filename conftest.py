"""Repo-root conftest to make top-level packages (e.g. ``evaluation``) importable in tests.

The ``[tool.pytest.ini_options].pythonpath`` setting in pyproject.toml only
includes ``src``, so packages that live at the repo root (like ``evaluation``)
are not importable by default. This conftest adds the repo root to sys.path
so tests can import them.
"""
from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
