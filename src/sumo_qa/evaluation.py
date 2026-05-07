from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from sumo_qa.tools import QAShiftLeftService


@dataclass(frozen=True)
class FixtureResult:
    fixture: str
    score: int
    possible: int
    missing: list[str]

    @property
    def passed(self) -> bool:
        return self.score == self.possible


def run_evaluation(root: str | Path | None = None) -> list[FixtureResult]:
    repo_root = Path(root) if root else _default_repo_root()
    service = QAShiftLeftService.from_standards_path(
        repo_root / "standards" / "packs",
        repo_root / "standards" / "rules" / "change_rules.yaml",
    )
    fixtures = sorted((repo_root / "evaluation").glob("*/*.yaml"))
    return [_run_fixture(service, fixture) for fixture in fixtures]


def print_report(results: list[FixtureResult]) -> None:
    total_score = sum(result.score for result in results)
    total_possible = sum(result.possible for result in results)
    for result in results:
        status = "PASS" if result.passed else "FAIL"
        missing = f" missing={', '.join(result.missing)}" if result.missing else ""
        print(f"{status} {result.fixture}: {result.score}/{result.possible}{missing}")
    print(f"TOTAL {total_score}/{total_possible}")


def main() -> None:
    print_report(run_evaluation())


def _run_fixture(service: QAShiftLeftService, fixture: Path) -> FixtureResult:
    raw = _load_yaml(fixture)
    fixture_type = raw["type"]
    fixture_input = raw["input"]
    expected = raw["expected"]

    explicit_classifications = fixture_input.get("classifications") or fixture_input.get(
        "explicit_classifications"
    )
    if fixture_type == "prepare":
        output = service.qa_prepare_for_work(
            work_item=fixture_input["work_item"],
            acceptance_criteria=fixture_input.get("acceptance_criteria"),
            risk_notes=fixture_input.get("risk_notes"),
            explicit_classifications=explicit_classifications,
        )
    elif fixture_type == "review":
        output = service.qa_review_local_change(
            change_summary=fixture_input["change_summary"],
            diff=fixture_input.get("diff"),
            touched_files=fixture_input.get("touched_files"),
            test_evidence=fixture_input.get("test_evidence"),
            explicit_classifications=explicit_classifications,
        )
    else:
        output = service.qa_answer_testing_question(
            question=fixture_input["question"],
            context=fixture_input.get("context"),
            explicit_classifications=explicit_classifications,
        )

    missing: list[str] = []
    score = 0
    possible = 0

    risk_haystack = _risk_haystack(output)
    for risk in expected.get("risks", []):
        possible += 1
        if str(risk).lower() in risk_haystack:
            score += 1
        else:
            missing.append(f"risk:{risk}")

    suggested_tests = output["suggested_tests"]
    for test_type in expected.get("test_types", []):
        possible += 1
        if suggested_tests.get(test_type):
            score += 1
        else:
            missing.append(f"test_type:{test_type}")

    expected_confidence = expected.get("confidence")
    if expected_confidence:
        possible += 1
        actual_confidence = output["confidence"]["level"]
        if actual_confidence == expected_confidence:
            score += 1
        else:
            missing.append(f"confidence:{expected_confidence}!=actual:{actual_confidence}")

    return FixtureResult(fixture=fixture.relative_to(fixture.parents[2]).as_posix(), score=score, possible=possible, missing=missing)


def _load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def _default_repo_root() -> Path:
    cwd = Path.cwd()
    if (cwd / "evaluation").exists() and (cwd / "standards").exists():
        return cwd
    return Path(__file__).resolve().parents[2]


def _risk_haystack(output: dict[str, Any]) -> str:
    parts: list[str] = []
    for risk in output.get("top_risks", []):
        parts.extend([str(risk.get("category", "")), str(risk.get("description", "")), str(risk.get("source", ""))])
    applied_rules = output.get("applied_rules", {})
    parts.extend(applied_rules.get("must_consider", []))
    parts.extend(applied_rules.get("risk_templates", []))
    return " ".join(parts).lower()


if __name__ == "__main__":
    main()
