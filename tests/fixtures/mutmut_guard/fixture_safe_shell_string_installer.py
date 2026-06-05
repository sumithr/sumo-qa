# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""SAFE fixture (shell=True string command): a shell spawn of an exempt entry point.

A ``shell=True`` single-string command that DOES launch Python but only the
provably non-mutating ``sumo_qa.installer`` entry point must stay UNflagged. This
pins that the new shell-string tokenisation still honours
``SAFE_SUMO_QA_ENTRY_POINTS`` — tokenising ``"python -m sumo_qa.installer ..."``
yields the ``sumo_qa.installer`` token, which is on the allow-list — so the
tokenisation does not over-fire. Fixture, not a test (named ``fixture_*.py``).
"""

from __future__ import annotations

import subprocess


def shell_installer() -> None:
    subprocess.run("python -m sumo_qa.installer --help", shell=True, capture_output=True)
