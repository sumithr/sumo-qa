# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""ReDoS guard for the conformance validator that runs its call in a child.

Kept apart from tests/test_conformance_transcript_validator.py so that module
stays inside the mutation gate.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

# mutmut-subprocess-spawning: spawns ``python -c`` importing sumo_qa.conformance,
# which imports the mutated knowledge_loaders, so it MUST be excluded from the
# mutmut gate via [tool.mutmut].pytest_add_cli_args in pyproject.toml. Otherwise
# the subprocess imports trampoline-injected modules without MUTANT_UNDER_TEST
# and crashes.

# The linear matcher finishes in well under 100ms; exponential backtracking
# takes far longer, so the budget tolerates a loaded pytest-xdist worker.
_REDOS_BUDGET_SECONDS = 2.0


def test_blank_string_values_does_not_backtrack_exponentially() -> None:
    """A backslash must match only the escape branch of the quoted-string
    pattern; when it could match either, an unterminated string of escapes
    backtracks exponentially (CodeQL py/redos, #248)."""
    from sumo_qa import conformance

    span = '{"a' + "\\a" * 28
    # The call runs in a child killed at 30s, so a regression fails fast
    # instead of blocking the pytest-xdist worker while it backtracks. The
    # child imports the same sumo_qa as this test: the pre-push hook's venv
    # has it only on pytest's pythonpath, not installed.
    import_root = str(Path(conformance.__file__).parents[1])
    child = (
        f"import sys, time; sys.path.insert(0, {import_root!r});"
        "from sumo_qa.conformance import _blank_string_values;"
        f"span = {span!r}; start = time.perf_counter();"
        "assert _blank_string_values(span) == span;"
        "print(time.perf_counter() - start)"
    )
    try:
        proc = subprocess.run(
            [sys.executable, "-c", child],
            capture_output=True,
            encoding="utf-8",
            timeout=30,
        )
    except subprocess.TimeoutExpired:
        pytest.fail("ReDoS: _blank_string_values did not finish in 30s")
    assert proc.returncode == 0, proc.stderr
    elapsed = float(proc.stdout)
    assert elapsed < _REDOS_BUDGET_SECONDS, f"ReDoS: _blank_string_values took {elapsed:.1f}s"
