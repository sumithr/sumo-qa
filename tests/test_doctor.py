# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Tests for sumo-qa-doctor — the read-only setup diagnostics CLI.

Each test exercises one check or one rendering path. Production code stays
in src/sumo_qa/doctor.py; installer.py is never modified.
"""

from __future__ import annotations

import sys

from sumo_qa import doctor


def test_module_exposes_main() -> None:
    assert hasattr(doctor, "main")
    assert callable(doctor.main)


def test_module_exposes_check_result_dataclass() -> None:
    cr = doctor.CheckResult(
        check_id="example",
        status="OK",
        summary="example summary",
        fix=None,
    )
    assert cr.check_id == "example"
    assert cr.status == "OK"
    assert cr.summary == "example summary"
    assert cr.fix is None


def test_check_result_dataclass_supports_details() -> None:
    cr = doctor.CheckResult(
        check_id="example",
        status="FAIL",
        summary="broken",
        fix="run X",
        details={"k": "v"},
    )
    assert cr.fix == "run X"
    assert cr.details == {"k": "v"}


def test_python_version_module_marker_used_in_tests() -> None:
    # Sanity guard: the doctor's sumo-qa version probe relies on the
    # interpreter that installed sumo-qa being the one running pytest.
    assert sys.version_info >= (3, 10)
