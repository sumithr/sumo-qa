# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""HAZARD fixture: shell-string ``python -m sumo_qa.installer --help``.

Same import hazard as ``fixture_hazard_dash_m_installer.py``, but through the
single-string ``shell=True`` command shape. Fixture, not a test.
"""

from __future__ import annotations

import subprocess


def spawn_installer_help_shell_string() -> None:
    subprocess.run("python -m sumo_qa.installer --help", shell=True, capture_output=True)
