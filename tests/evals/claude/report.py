# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""The run's JSON report: its shape, and the rule that it is written only once.

Two jobs, and the second is the one that matters.

## The shape

`eval-failure-diagnoser` and `/finish-pr` read this file, so its layout is a
contract, versioned by `REPORT_SCHEMA_VERSION` and pinned by
`tests/test_claude_eval_judge.py`. Per config, per case (prompt label x repeat),
per assertion: pass/fail, score, and the judge's own reason. Usage is recorded
per model id, and the totals fold every model that ran.

    {
      "schema_version": 1,
      "generated_at": "<ISO-8601 UTC>",
      "candidate_model": "...", "judge_model": "...",
      "cost_basis": "list",
      "repeat": 1,
      "configs": [
        {"config": "skill-x.yaml",
         "passed": false,
         "cases": [{"prompt_label": "A0 - ...", "description": "...",
                    "repeat": 1, "passed": false,
                    "assertions": [{"kind": "llm-rubric", "passed": false,
                                    "score": 0.0, "reason": "..."}]}],
         # kind is "llm-rubric", "javascript", or "javascript-unported"
         # (a harness gap, not a skill regression - see AssertionRecord)
         "cost": {"input_tokens": 0, "output_tokens": 0, "usd": 0.0,
                  "by_model": {"<canonical model id>": {...}}}}
      ],
      "totals": {"configs": 1, "cases": 1, "passed": 0, "failed": 1,
                 "input_tokens": 0, "output_tokens": 0, "usd": 0.0}
    }

`cost_basis` is always `"list"` and is not decoration. The runner spends the
account's Claude subscription, not metered credit, so the dollar figure is the
notional list-price equivalent of the tokens consumed - the right number for
comparing a candidate tier against a judge tier, the wrong number to read as
an invoice.

## Written once, at the end, or not at all

This is the #651 regression in artifact form. The old baseline script wrote
its snapshot as it went, so when the run died on a 429 mid-matrix, what
survived on disk was a file in which almost nothing had passed - indistinguish-
able from a real collapse in skill quality, and the number the next run
compared against.

So nothing here touches the filesystem until a run has completed. `write_report`
is called by `claude/cli.py` exactly once, after the last case; a
`FatalRunError` propagates past it and the process exits non-zero having
written nothing. There is deliberately no incremental-write mode and no
`--baseline` file: the report IS the snapshot, and a half-finished one has
negative value.

The write itself is atomic - a temporary file in the destination directory,
then `os.replace` - so a crash during serialisation cannot leave a truncated
report where a previous good one was.
"""

from __future__ import annotations

import datetime
import json
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from claude.models import CANDIDATE_MODEL, JUDGE_MODEL

__all__ = [
    "COST_BASIS",
    "REPORT_SCHEMA_VERSION",
    "AssertionRecord",
    "CaseRecord",
    "ConfigRecord",
    "ModelCost",
    "RunReport",
    "write_report",
]

REPORT_SCHEMA_VERSION = 1

# The CLI reports `costBasis: "list"` for every call it prices.
COST_BASIS = "list"


@dataclass(frozen=True)
class AssertionRecord:
    """One assertion's outcome.

    `kind` is one of three, and the third is the one that matters:

    * `llm-rubric` - the judge graded it.
    * `javascript` - a deterministic Python port evaluated it offline.
    * `javascript-unported` - the runner has NO port for this assert, so it
      could not be graded at all. It fails, but it is a gap in the HARNESS,
      not a regression in a skill. Anything reading this file must keep those
      apart: an epic that exists because a tooling failure was misread as a
      collapse in skill quality (#651) should not ship a second way to make
      the same mistake.
    """

    kind: str
    passed: bool
    score: float
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "passed": self.passed,
            "score": self.score,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class CaseRecord:
    """One (prompt label, repeat) pair and everything asserted about it."""

    prompt_label: str
    description: str
    repeat: int
    passed: bool
    assertions: list[AssertionRecord] = field(default_factory=list)
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "prompt_label": self.prompt_label,
            "description": self.description,
            "repeat": self.repeat,
            "passed": self.passed,
            "assertions": [assertion.to_dict() for assertion in self.assertions],
        }
        if self.error:
            payload["error"] = self.error
        return payload


@dataclass
class ModelCost:
    """Accumulated usage for one model id within one config."""

    input_tokens: int = 0
    output_tokens: int = 0
    usd: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "usd": round(self.usd, 6),
        }


@dataclass
class ConfigRecord:
    """One eval config: its cases, and what grading them consumed."""

    config: str
    cases: list[CaseRecord] = field(default_factory=list)
    by_model: dict[str, ModelCost] = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        """A config passes only when every case in it passed.

        An empty config passes vacuously; that is not a silent hole, because
        the totals below report the case count alongside it and slice 1's
        loader already refuses a config that carries no cases by mistake.
        """
        return all(case.passed for case in self.cases)

    def record_usage(
        self, *, model: str, input_tokens: int, output_tokens: int, usd: float
    ) -> None:
        entry = self.by_model.setdefault(model, ModelCost())
        entry.input_tokens += input_tokens
        entry.output_tokens += output_tokens
        entry.usd += usd

    def cost(self) -> dict[str, Any]:
        return {
            "input_tokens": sum(entry.input_tokens for entry in self.by_model.values()),
            "output_tokens": sum(entry.output_tokens for entry in self.by_model.values()),
            "usd": round(sum(entry.usd for entry in self.by_model.values()), 6),
            "by_model": {model: entry.to_dict() for model, entry in sorted(self.by_model.items())},
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "config": self.config,
            "passed": self.passed,
            "cases": [case.to_dict() for case in self.cases],
            "cost": self.cost(),
        }


@dataclass
class RunReport:
    """Every config in one run, plus the run-level totals."""

    configs: list[ConfigRecord] = field(default_factory=list)
    repeat: int = 1
    candidate_model: str = CANDIDATE_MODEL
    judge_model: str = JUDGE_MODEL
    generated_at: str = ""

    def config_for(self, name: str) -> ConfigRecord:
        """The record for `name`, created on first use."""
        for record in self.configs:
            if record.config == name:
                return record
        record = ConfigRecord(config=name)
        self.configs.append(record)
        return record

    def record_usage(
        self, config: str, *, model: str, input_tokens: int, output_tokens: int, usd: float = 0.0
    ) -> None:
        self.config_for(config).record_usage(
            model=model, input_tokens=input_tokens, output_tokens=output_tokens, usd=usd
        )

    @property
    def passed(self) -> bool:
        return all(record.passed for record in self.configs)

    def to_dict(self) -> dict[str, Any]:
        configs = [record.to_dict() for record in self.configs]
        cases = [case for record in self.configs for case in record.cases]
        return {
            "schema_version": REPORT_SCHEMA_VERSION,
            "generated_at": self.generated_at or _now(),
            "candidate_model": self.candidate_model,
            "judge_model": self.judge_model,
            "cost_basis": COST_BASIS,
            "repeat": self.repeat,
            "passed": self.passed,
            "configs": configs,
            "totals": {
                "configs": len(configs),
                "cases": len(cases),
                "passed": sum(1 for case in cases if case.passed),
                "failed": sum(1 for case in cases if not case.passed),
                "input_tokens": sum(entry["cost"]["input_tokens"] for entry in configs),
                "output_tokens": sum(entry["cost"]["output_tokens"] for entry in configs),
                "usd": round(sum(entry["cost"]["usd"] for entry in configs), 6),
            },
        }


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def write_report(path: Path, report: RunReport) -> dict[str, Any]:
    """Serialise `report` to `path` atomically, and return what was written.

    Called exactly once, after a run completes. A run that aborts never
    reaches here, which is the whole point - see the module docstring.
    """
    path = Path(path)
    payload = report.to_dict()
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=str(path.parent), prefix=path.name, suffix=".tmp", delete=False
    )
    try:
        with handle:
            json.dump(payload, handle, indent=2, sort_keys=False)
            handle.write("\n")
        os.replace(handle.name, path)
    except BaseException:
        Path(handle.name).unlink(missing_ok=True)
        raise
    return payload
