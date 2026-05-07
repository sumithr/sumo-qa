from pathlib import Path

from sumo_qa.local_diff import LocalDiffInspector, _files_from_diff


ROOT = Path(__file__).resolve().parents[1]


def test_local_diff_reports_missing_expected_test_levels() -> None:
    diff = """
--- a/src/stock/cache/availability_cache.py
+++ b/src/stock/cache/availability_cache.py
@@
+ cache_ttl_seconds = 300
"""

    _, report = LocalDiffInspector(ROOT).inspect(
        diff=diff,
        touched_files=None,
        expected_test_types=["unit", "integration", "nonfunctional"],
        test_evidence=[],
    )

    assert "src/stock/cache/availability_cache.py" in report.touched_files
    assert "nonfunctional" in report.missing_test_levels
    assert report.risky_untested_changes


def test_integration_in_file_path_alone_does_not_count_as_coverage(tmp_path: Path) -> None:
    project = tmp_path / "project"
    (project / "src" / "integration").mkdir(parents=True)
    (project / "src" / "integration" / "foo.py").write_text("x = 1\n", encoding="utf-8")

    _, report = LocalDiffInspector(project).inspect(
        diff=None,
        touched_files=["src/integration/foo.py"],
        expected_test_types=["unit", "integration"],
        test_evidence=[],
    )

    assert "src/integration/foo.py" in report.touched_files
    assert report.nearby_tests == []
    assert "integration" in report.missing_test_levels
    assert "unit" in report.missing_test_levels


def test_files_from_diff_handles_simple_modify() -> None:
    diff = (
        "diff --git a/src/foo.py b/src/foo.py\n"
        "index abc..def 100644\n"
        "--- a/src/foo.py\n"
        "+++ b/src/foo.py\n"
        "@@\n"
        "+x = 1\n"
    )

    assert _files_from_diff(diff) == ["src/foo.py"]


def test_files_from_diff_handles_rename_without_content_change() -> None:
    diff = (
        "diff --git a/src/old_name.py b/src/new_name.py\n"
        "similarity index 100%\n"
        "rename from src/old_name.py\n"
        "rename to src/new_name.py\n"
    )

    files = _files_from_diff(diff)

    assert "src/old_name.py" in files
    assert "src/new_name.py" in files


def test_files_from_diff_handles_rename_with_modifications() -> None:
    diff = (
        "diff --git a/src/old.py b/src/new.py\n"
        "similarity index 80%\n"
        "rename from src/old.py\n"
        "rename to src/new.py\n"
        "index abc..def 100644\n"
        "--- a/src/old.py\n"
        "+++ b/src/new.py\n"
        "@@\n"
        "-old = 1\n"
        "+new = 1\n"
    )

    files = _files_from_diff(diff)

    assert "src/old.py" in files
    assert "src/new.py" in files


def test_files_from_diff_handles_delete() -> None:
    diff = (
        "diff --git a/src/dropped.py b/src/dropped.py\n"
        "deleted file mode 100644\n"
        "index abc..0000000\n"
        "--- a/src/dropped.py\n"
        "+++ /dev/null\n"
        "@@\n"
        "-old = 1\n"
    )

    files = _files_from_diff(diff)

    assert "src/dropped.py" in files
    assert "/dev/null" not in files


def test_files_from_diff_handles_new_file() -> None:
    diff = (
        "diff --git a/src/added.py b/src/added.py\n"
        "new file mode 100644\n"
        "index 0000000..abc\n"
        "--- /dev/null\n"
        "+++ b/src/added.py\n"
        "@@\n"
        "+new = 1\n"
    )

    files = _files_from_diff(diff)

    assert "src/added.py" in files
    assert "/dev/null" not in files


def test_files_from_diff_handles_binary_file() -> None:
    diff = (
        "diff --git a/assets/logo.png b/assets/logo.png\n"
        "index abc..def 100644\n"
        "Binary files a/assets/logo.png and b/assets/logo.png differ\n"
    )

    assert _files_from_diff(diff) == ["assets/logo.png"]


def test_files_from_diff_handles_mode_only_change() -> None:
    diff = (
        "diff --git a/scripts/run.sh b/scripts/run.sh\n"
        "old mode 100644\n"
        "new mode 100755\n"
    )

    assert _files_from_diff(diff) == ["scripts/run.sh"]


def test_files_from_diff_returns_empty_for_empty_input() -> None:
    assert _files_from_diff("") == []


def test_nearby_tests_word_bounded_stem_avoids_substring_false_positive(tmp_path: Path) -> None:
    project = tmp_path / "project"
    (project / "src").mkdir(parents=True)
    (project / "src" / "orders.py").write_text("x = 1\n", encoding="utf-8")
    (project / "tests").mkdir()
    (project / "tests" / "test_orders.py").write_text("def test_x(): pass\n", encoding="utf-8")
    (project / "tests" / "test_orders_extra.py").write_text("def test_y(): pass\n", encoding="utf-8")
    # False positive risk: 'orders' is a substring of 'disorders'
    (project / "tests" / "test_disorders.py").write_text("def test_z(): pass\n", encoding="utf-8")

    inspector = LocalDiffInspector(project)
    _, report = inspector.inspect(
        diff=None,
        touched_files=["src/orders.py"],
        expected_test_types=["unit"],
        test_evidence=[],
    )

    assert report.nearby_tests, "expected at least the canonical pytest match"
    # Canonical pytest match should come first (strongest)
    assert report.nearby_tests[0] == "tests/test_orders.py"
    # 'orders' as a token in the stem should match
    assert "tests/test_orders_extra.py" in report.nearby_tests
    # 'orders' as a substring of 'disorders' should NOT match
    assert "tests/test_disorders.py" not in report.nearby_tests


def test_weak_single_token_overlap_does_not_satisfy_coverage(tmp_path: Path) -> None:
    project = tmp_path / "project"
    (project / "src").mkdir(parents=True)
    (project / "src" / "fulfilment_eligibility.py").write_text("x = 1\n", encoding="utf-8")
    (project / "tests").mkdir()
    # Shares only 'eligibility' token - too weak to count as nearby evidence.
    (project / "tests" / "test_orders_eligibility.py").write_text(
        "def test_x(): pass\n", encoding="utf-8"
    )

    inspector = LocalDiffInspector(project)
    _, report = inspector.inspect(
        diff=None,
        touched_files=["src/fulfilment_eligibility.py"],
        expected_test_types=["unit"],
        test_evidence=[],
    )

    assert report.nearby_tests == []
    assert "unit" in report.missing_test_levels


def test_strong_test_name_match_satisfies_unit_coverage(tmp_path: Path) -> None:
    project = tmp_path / "project"
    (project / "src").mkdir(parents=True)
    (project / "src" / "orders.py").write_text("x = 1\n", encoding="utf-8")
    (project / "tests").mkdir()
    (project / "tests" / "test_orders.py").write_text("def test_x(): pass\n", encoding="utf-8")

    inspector = LocalDiffInspector(project)
    _, report = inspector.inspect(
        diff=None,
        touched_files=["src/orders.py"],
        expected_test_types=["unit", "integration"],
        test_evidence=[],
    )

    # Unit is satisfied by the stem-match test_orders.py
    assert "unit" not in report.missing_test_levels
    # Integration was expected and there's no integration evidence -> still missing
    assert "integration" in report.missing_test_levels


def test_nearby_tests_caps_returned_matches(tmp_path: Path) -> None:
    project = tmp_path / "project"
    (project / "src").mkdir(parents=True)
    (project / "src" / "orders.py").write_text("x = 1\n", encoding="utf-8")
    (project / "tests").mkdir()
    for index in range(20):
        (project / "tests" / f"test_orders_{index:02d}.py").write_text(
            "def test_x(): pass\n", encoding="utf-8"
        )

    inspector = LocalDiffInspector(project)
    _, report = inspector.inspect(
        diff=None,
        touched_files=["src/orders.py"],
        expected_test_types=["unit"],
        test_evidence=[],
    )

    assert len(report.nearby_tests) <= 10, "should cap noisy match lists"
