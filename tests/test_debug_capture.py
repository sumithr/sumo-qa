# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
import json

from sumo_qa.debug_capture import maybe_capture


def test_capture_writes_files_when_env_set(tmp_path, monkeypatch):
    monkeypatch.setenv("SUMO_QA_DEBUG_DIR", str(tmp_path))
    payload = {"tool": "qa_decide_approach", "x": 1}
    captured = maybe_capture(
        tool="qa_decide_approach",
        args={"intent_text": "x"},
        output=payload,
    )
    # Returns the payload unchanged.
    assert captured == payload
    # Wrote a directory containing input.json + output.json + trace.md.
    runs = list(tmp_path.iterdir())
    assert len(runs) == 1
    run = runs[0]
    assert (run / "input.json").exists()
    assert (run / "output.json").exists()
    assert (run / "trace.md").exists()
    # JSON is valid.
    assert json.loads((run / "output.json").read_text()) == payload


def test_capture_is_noop_when_env_not_set(tmp_path, monkeypatch):
    monkeypatch.delenv("SUMO_QA_DEBUG_DIR", raising=False)
    payload = {"tool": "qa_decide_approach", "x": 1}
    captured = maybe_capture(
        tool="qa_decide_approach",
        args={"intent_text": "x"},
        output=payload,
    )
    # Returns the payload unchanged.
    assert captured == payload
    # Did NOT write any directory under tmp_path.
    assert list(tmp_path.iterdir()) == []
