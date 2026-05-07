"""qa_scaffold_tests - the MCP returns structured tasks the host model then writes.

The MCP itself never writes files. It produces a checklist the host model can
follow with its own file tools. Each task is small enough to verify after.
"""
from pathlib import Path

from sumo_qa.tools import QAShiftLeftService


ROOT = Path(__file__).resolve().parents[1]


def _service() -> QAShiftLeftService:
    return QAShiftLeftService.from_standards_path(ROOT / "standards" / "packs")


def test_scaffold_tests_returns_structured_tasks() -> None:
    result = _service().qa_scaffold_tests(
        work_item="Add an API endpoint that validates bundle variants on the order pipeline",
        test_conditions=[
            "Valid bundle with all required fields passes validation.",
            "Bundle with missing variant id is blocked at write time with a clear reason.",
            "Boundary: a bundle with exactly one variant passes; with zero is blocked.",
        ],
        target_paths=["src/orders/api.py"],
    )

    assert result["tool"] == "qa_scaffold_tests"
    assert result["headline"]
    tasks = result["tasks"]
    assert len(tasks) >= 1, "expected at least one scaffold task"

    for task in tasks:
        # Required fields per task
        assert task["id"]
        assert task["title"]
        assert task["file_path"]
        assert task["framework"]
        assert task["language"]
        assert task["level"] in {"unit", "integration", "contract", "functional", "nonfunctional"}
        assert task["assertions"], "task must list named assertions"
        assert task["skeleton"], "task must carry an honestly-stubbed skeleton"
        assert task["verify_command"], "task must say how to run the test once written"
        # Skeleton is a stub, never a fake passing implementation
        skel = task["skeleton"].lower()
        assert "todo" in skel or "raise notimplementederror" in skel or "pending" in skel, (
            "skeleton must be an honest stub, not a fake passing implementation\n"
            f"--- {task['id']} skeleton ---\n{task['skeleton']}\n--- end ---"
        )


def test_scaffold_tests_routes_frontend_paths_to_cypress_or_jest() -> None:
    result = _service().qa_scaffold_tests(
        work_item="Refactor the checkout button hover state",
        test_conditions=[
            "Hover transitions render expected colour after 200ms.",
            "Keyboard focus shows the same visual state as mouse hover.",
        ],
        target_paths=["src/components/CheckoutButton.tsx"],
    )

    frameworks = {task["framework"].lower() for task in result["tasks"]}
    languages = {task["language"].lower() for task in result["tasks"]}
    # Frontend tsx triggers a JS-family framework, not pytest
    assert any(f in frameworks for f in ("cypress", "playwright", "jest", "vitest", "react testing library")), (
        f"expected a frontend framework, got {frameworks}"
    )
    assert "python" not in languages, f"frontend file should not produce python tests, got {languages}"


def test_scaffold_tests_marks_specialty_tasks_with_mcp_hint() -> None:
    """Caller supplies the classification — the harness no longer pattern-
    matches paths or text to guess specialty needs."""
    result = _service().qa_scaffold_tests(
        work_item="Refactor the checkout button hover state",
        test_conditions=["Hover transitions render expected colour."],
        target_paths=["src/components/CheckoutButton.tsx"],
        explicit_classifications=["ui_only_change"],
    )

    # Tasks for specialty work expose the routing hint so the host can chain
    # to a specialty MCP if one is available.
    specialty_tasks = [t for t in result["tasks"] if t.get("specialty")]
    assert specialty_tasks, "expected at least one specialty-tagged task for a frontend change"
    for task in specialty_tasks:
        assert task.get("specialty_mcp_hint")


def test_scaffold_tests_emits_execution_order_and_verification_block() -> None:
    """The host model needs an order to follow and a way to run each test."""
    result = _service().qa_scaffold_tests(
        work_item="Add API endpoint that validates bundle variants",
        test_conditions=["Valid bundle passes", "Invalid blocks at write time"],
        target_paths=["src/orders/api.py"],
    )

    order = result["execution_order"]
    task_ids = [t["id"] for t in result["tasks"]]
    assert order, "execution_order must be present"
    assert set(order) == set(task_ids), "execution_order must enumerate every task"
    # Unit tests come before integration / contract / E2E
    levels_in_order = [next(t["level"] for t in result["tasks"] if t["id"] == tid) for tid in order]
    if "unit" in levels_in_order and "integration" in levels_in_order:
        assert levels_in_order.index("unit") < levels_in_order.index("integration")


def test_scaffold_tests_thin_input_asks_for_specifics() -> None:
    result = _service().qa_scaffold_tests(work_item="x", test_conditions=[])
    assert "more detail" in result["headline"].lower() or "specific" in result["headline"].lower()
    assert "concrete work item description" in result["missing_information"] or \
           "test conditions" in result["missing_information"]


def test_scaffold_tests_response_has_presentation_hint() -> None:
    result = _service().qa_scaffold_tests(
        work_item="Add API endpoint",
        test_conditions=["Valid passes"],
        target_paths=["src/orders/api.py"],
    )
    assert result["presentation"]["style"] == "concise"
    instructions = result["presentation"]["render_instructions"].lower()
    assert "task" in instructions
    # Tells the host to surface assertions, not full skeletons
    assert "skeleton" in instructions
