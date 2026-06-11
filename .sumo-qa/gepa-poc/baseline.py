"""Valset baseline on the CURRENT SKILL.md — the comparison anchor for the POC verdict."""

import json
from pathlib import Path

import harness
import scoring
import scratch
from run_poc import VALSET

scratch.build_scratch()  # scratch == current skill (the seed)
out = {}
for inst in VALSET:
    rows = harness.run_yaml_with_retry(inst["yaml"], repeat=3)
    out[inst["yaml"]] = {
        "tests": len(rows),
        "pass": sum(r["success"] for r in rows),
        "ab_floor_ok": scoring.ab_floor_ok(rows) if inst["kind"] == "ab" else None,
    }
print(json.dumps(out, indent=2))
Path(__file__).with_name("baseline.json").write_text(json.dumps(out, indent=2))
