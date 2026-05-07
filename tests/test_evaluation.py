from pathlib import Path

from sumo_qa.evaluation import run_evaluation


ROOT = Path(__file__).resolve().parents[1]


def test_evaluation_fixtures_pass() -> None:
    results = run_evaluation(ROOT)

    assert len(results) == 4
    assert all(result.passed for result in results)
