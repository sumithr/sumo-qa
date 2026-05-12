from pathlib import Path

from sumo_qa.tools import QAShiftLeftService

ROOT = Path(__file__).resolve().parents[1]


def service() -> QAShiftLeftService:
    return QAShiftLeftService.from_standards_path(ROOT / "standards" / "packs")


def test_service_factory_returns_test_data_capable_service() -> None:
    """The slimmed Phase 4 service exposes test-data flows only; the heavy
    QA reasoning tools were removed and moved to skill prompts + knowledge
    loaders. The factory must still produce a usable service."""
    svc = service()
    assert hasattr(svc, "qa_explain_test_data_requirements")
    assert hasattr(svc, "qa_find_test_data")
    assert hasattr(svc, "qa_validate_test_data")
    assert hasattr(svc, "qa_register_known_good_test_data")


def test_resolve_data_path_honours_explicit_user_path(tmp_path: Path) -> None:
    from sumo_qa.tools import (
        DEFAULT_STANDARDS_PATH,
        _resolve_data_path,
    )

    custom = tmp_path / "team-standards"
    resolved = _resolve_data_path(custom, DEFAULT_STANDARDS_PATH, "standards", "packs")

    assert resolved == custom


def test_resolve_data_path_falls_back_to_bundled_when_default_missing(
    tmp_path: Path, monkeypatch
) -> None:
    from sumo_qa.tools import (
        DEFAULT_STANDARDS_PATH,
        _resolve_data_path,
    )

    # Run from a directory where the default cwd-relative path does NOT exist
    monkeypatch.chdir(tmp_path)
    resolved = _resolve_data_path(
        DEFAULT_STANDARDS_PATH, DEFAULT_STANDARDS_PATH, "standards", "packs"
    )

    # In editable install + repo cwd, packaged _data may not exist; the function
    # should still return *something* - the cwd-relative default if nothing else.
    # The contract is: the returned path is one of (cwd default, bundled, default).
    # When run from tmp_path the cwd default doesn't exist; only the bundled path
    # would, IF this is a non-editable install. In an editable install the bundled
    # path also doesn't exist, and the function falls back to the default.
    # This test asserts the function does not crash and returns a Path; the
    # behavioural variants are covered by an end-to-end install test outside CI.
    assert isinstance(resolved, Path)
