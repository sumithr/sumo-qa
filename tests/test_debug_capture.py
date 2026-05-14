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


def test_capture_handles_timestamp_collision_by_incrementing(tmp_path, monkeypatch):
    """When a run dir already exists for the same timestamp, the function
    increments a suffix until it finds a free slot (lines 36-37)."""
    import time

    monkeypatch.setenv("SUMO_QA_DEBUG_DIR", str(tmp_path))

    # Freeze time so both calls produce the same timestamp prefix.
    fixed_ts = "20260514-120000"
    monkeypatch.setattr(time, "strftime", lambda _fmt: fixed_ts)

    payload = {"x": 1}
    maybe_capture(tool="qa_decide", args={}, output=payload)
    maybe_capture(tool="qa_decide", args={}, output=payload)

    dirs = sorted(d.name for d in tmp_path.iterdir())
    # First call → "20260514-120000-qa_decide"
    # Second call → "20260514-120000-qa_decide-1" (collision resolution)
    assert any("qa_decide" in d and "-1" in d for d in dirs), (
        f"Expected a collision-resolved directory, got: {dirs}"
    )


def test_capture_swallows_write_errors_and_returns_output(tmp_path, monkeypatch):
    """If the write to disk fails for any reason, maybe_capture must still
    return the original output unchanged (lines 42-43 — bare except: pass)."""
    import unittest.mock as mock

    monkeypatch.setenv("SUMO_QA_DEBUG_DIR", str(tmp_path))
    payload = {"x": 99}

    # Make Path.mkdir raise to trigger the exception path.
    with mock.patch("pathlib.Path.mkdir", side_effect=PermissionError("no write")):
        result = maybe_capture(tool="qa_decide", args={}, output=payload)

    assert result == payload
