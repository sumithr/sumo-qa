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


# ---------------------------------------------------------------------------
# Check: python_version
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Check: install_mode
# ---------------------------------------------------------------------------


def test_check_install_mode_editable(tmp_path) -> None:
    # Editable layout: skills/ at repo root, no bundled _data/skills/.
    module_dir = tmp_path / "src" / "sumo_qa"
    module_dir.mkdir(parents=True)
    (tmp_path / "pyproject.toml").write_text("[project]\n")
    (tmp_path / "skills").mkdir()

    result = doctor.check_install_mode(module_dir=module_dir)
    assert result.check_id == "install_mode"
    assert result.status == "OK"
    assert "editable" in result.summary.lower()
    assert result.details["mode"] == "editable"
    assert result.details["skills_path"] == str(tmp_path / "skills")


def test_check_install_mode_wheel(tmp_path) -> None:
    # Wheel layout: bundled skills inside the module directory.
    module_dir = tmp_path / "site-packages" / "sumo_qa"
    bundled = module_dir / "_data" / "skills"
    bundled.mkdir(parents=True)

    result = doctor.check_install_mode(module_dir=module_dir)
    assert result.status == "OK"
    assert "wheel" in result.summary.lower()
    assert result.details["mode"] == "wheel"
    assert result.details["skills_path"] == str(bundled)


def test_check_install_mode_defaults_to_actual_module() -> None:
    # Smoke: with no arg, checks the live install and returns one of the
    # known modes. The doctor's own runtime should classify cleanly.
    result = doctor.check_install_mode()
    assert result.status == "OK"
    assert result.details["mode"] in {"wheel", "editable"}


# ---------------------------------------------------------------------------
# Check: python_version
# ---------------------------------------------------------------------------


def test_check_python_version_reports_interpreter_and_package() -> None:
    from importlib.metadata import version as _pkg_version

    result = doctor.check_python_version()
    assert result.check_id == "python_version"
    assert result.status == "OK"
    py = ".".join(str(p) for p in sys.version_info[:3])
    assert py in result.summary
    assert _pkg_version("sumo-qa") in result.summary
    assert result.fix is None
    assert result.details["python_version"] == py
    assert result.details["sumo_qa_version"] == _pkg_version("sumo-qa")
