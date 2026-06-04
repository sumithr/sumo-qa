# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""HAZARD fixture (false-negative #1): a ``-c`` body built in a separate
variable via ``textwrap.dedent`` and passed to ``subprocess.run``.

Verbatim shape from ``tests/test_ingest_source_free.py`` — the body string lives
in the ``code`` Name, NOT lexically under the ``subprocess.run([...])`` Call, so
the pre-fix lexical literal scan missed it. The spawned interpreter imports
``sumo_qa.knowledge_loaders`` (a mutated module) → trampoline crash under mutmut.
This file is a fixture, not a test (named ``fixture_*.py``).
"""

from __future__ import annotations

import subprocess
import sys
import textwrap


def spawn_loader() -> None:
    code = textwrap.dedent(
        """
        from sumo_qa.knowledge_loaders import sumo_qa_load_principles
        import sys
        sys.stdout.write(sumo_qa_load_principles())
        """
    )
    subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
    )
