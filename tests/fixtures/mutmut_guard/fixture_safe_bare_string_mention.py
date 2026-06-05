# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""SAFE fixture: a bare-string mention of a mutated module, with NO spawn.

A docstring / assertion that merely *names* ``sumo_qa.knowledge_loaders`` must
not be confused for a subprocess hazard (the substring/token-confusion failure
mode the guard is built to avoid). No ``subprocess`` call exists here at all, so
the guard must NOT flag it. Fixture, not a test (named ``fixture_*.py``).
"""

from __future__ import annotations

DOC = "the loader lives in sumo_qa.knowledge_loaders and is imported by server"


def describe() -> str:
    note = "see sumo_qa.rules for the StandardsRulesEngine"
    return f"{DOC} -- {note}"
