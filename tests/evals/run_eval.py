#!/usr/bin/env python3
# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Run one sumo-qa eval scenario through the Codex adversarial judge.

Pipeline:
    1. Read the scenario spec (frontmatter + body) from
       `tests/evals/scenarios/<scenario_id>.md`.
    2. Pick the rubric template by scenario_type (skill | tool).
    3. Substitute {{placeholders}} with frontmatter fields + the candidate
       response text loaded from --candidate.
    4. Invoke `codex exec --output-schema ... -o ... <rendered_prompt>` to get a
       JSON verdict that conforms to `tests/evals/schemas/verdict.schema.json`.
    5. Copy the candidate alongside the verdict so each run is self-contained.
    6. Print a one-line summary; exit 0 on PASS, 1 on FAIL.

The runner is intentionally thin — the *judging* lives in the rubric templates
plus Codex's adversarial framing. This script is the glue, not the brain.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
EVALS_DIR = REPO_ROOT / "tests" / "evals"
SCENARIOS_DIR = EVALS_DIR / "scenarios"
RUBRICS_DIR = EVALS_DIR / "rubrics"
SCHEMA_PATH = EVALS_DIR / "schemas" / "verdict.schema.json"
RUNS_DIR = EVALS_DIR / "runs"


def _load_scenario(scenario_id: str) -> tuple[dict, str]:
    """Return (frontmatter_dict, body_text) for `<scenario_id>.md`."""
    path = SCENARIOS_DIR / f"{scenario_id}.md"
    if not path.is_file():
        raise SystemExit(f"scenario file not found: {path}")
    text = path.read_text(encoding="utf-8")
    parts = text.split("---", 2)
    if len(parts) < 3:
        raise SystemExit(f"{path}: expected YAML frontmatter delimited by '---'")
    frontmatter = yaml.safe_load(parts[1]) or {}
    body = parts[2].lstrip("\n")
    return frontmatter, body


def _pick_rubric(scenario_type: str) -> str:
    """Return the rubric template text matching the scenario type."""
    if scenario_type == "skill":
        return (RUBRICS_DIR / "skill-behaviour.md").read_text(encoding="utf-8")
    if scenario_type == "tool":
        return (RUBRICS_DIR / "tool-selection.md").read_text(encoding="utf-8")
    raise SystemExit(f"unknown scenario_type: {scenario_type!r}")


def _section(body: str, heading: str) -> str:
    """Return the body of an h2 section (`## heading`) from the scenario file."""
    pattern = re.compile(
        rf"^##\s+{re.escape(heading)}\s*\n(.*?)(?=^##\s|\Z)", re.MULTILINE | re.DOTALL
    )
    m = pattern.search(body)
    if not m:
        return ""
    return m.group(1).strip()


def _bulleted(items: list[str]) -> str:
    """Format a list as a markdown bullet list, one item per line."""
    return "\n".join(f"- {item}" for item in items)


def _render(template: str, fields: dict[str, str]) -> str:
    """Substitute {{placeholders}} in `template` with values from `fields`."""

    def sub(match: re.Match[str]) -> str:
        key = match.group(1).strip()
        if key not in fields:
            raise SystemExit(f"template placeholder {{{{{key}}}}} has no value")
        return fields[key]

    return re.sub(r"\{\{\s*([a-z_]+)\s*\}\}", sub, template)


def _build_skill_prompt(scenario_id: str, frontmatter: dict, body: str, candidate: str) -> str:
    template = _pick_rubric("skill")
    fields = {
        "scenario_id": scenario_id,
        "scenario_user_prompt": _section(body, "User prompt"),
        "expected_skill": frontmatter.get("expected_skill", "<unspecified>"),
        "expected_interaction_shape": _section(body, "Expected interaction shape"),
        "anti_patterns": _bulleted(frontmatter.get("anti_patterns") or []),
        "candidate_response": candidate,
    }
    return _render(template, fields)


def _build_tool_prompt(scenario_id: str, frontmatter: dict, body: str, candidate: str) -> str:
    template = _pick_rubric("tool")
    fields = {
        "scenario_id": scenario_id,
        "scenario_user_prompt": _section(body, "User prompt"),
        "expected_tool": frontmatter.get("expected_tool", "<unspecified>"),
        "expected_arg_shape": frontmatter.get("expected_arg_shape", "<unspecified>"),
        "expected_use_of_result": _section(body, "Expected use of result"),
        "anti_picks": _bulleted(frontmatter.get("anti_picks") or []),
        "candidate_response": candidate,
    }
    return _render(template, fields)


def _invoke_judge(prompt: str, verdict_path: Path) -> dict:
    """Run `codex exec` with the verdict schema; return the parsed verdict JSON."""
    cmd = [
        "codex",
        "exec",
        "--skip-git-repo-check",
        "--ephemeral",
        "--output-schema",
        str(SCHEMA_PATH),
        "-o",
        str(verdict_path),
        "--color",
        "never",
        prompt,
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        sys.stderr.write(proc.stderr)
        raise SystemExit(f"codex exec failed with exit code {proc.returncode}")
    if not verdict_path.is_file():
        raise SystemExit(f"codex exec finished but verdict file not written: {verdict_path}")
    try:
        return json.loads(verdict_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"verdict file is not valid JSON: {exc}") from exc


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", required=True, help="Scenario ID, e.g. SCN-10 or TS-01.")
    parser.add_argument(
        "--candidate",
        required=True,
        type=Path,
        help="Path to the candidate's first-turn response markdown.",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=None,
        help="Output directory for artifacts. Defaults to tests/evals/runs/<UTC-timestamp>/.",
    )
    args = parser.parse_args()

    if not args.candidate.is_file():
        raise SystemExit(f"candidate file not found: {args.candidate}")

    out_dir = args.out_dir or (RUNS_DIR / datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ"))
    out_dir.mkdir(parents=True, exist_ok=True)

    frontmatter, body = _load_scenario(args.scenario)
    scenario_type = frontmatter.get("scenario_type")
    candidate_text = args.candidate.read_text(encoding="utf-8")

    if scenario_type == "skill":
        prompt = _build_skill_prompt(args.scenario, frontmatter, body, candidate_text)
    elif scenario_type == "tool":
        prompt = _build_tool_prompt(args.scenario, frontmatter, body, candidate_text)
    else:
        raise SystemExit(f"unknown scenario_type in {args.scenario}: {scenario_type!r}")

    verdict_path = out_dir / f"{args.scenario}.verdict.json"
    candidate_dest = out_dir / f"{args.scenario}.candidate.md"
    shutil.copy(args.candidate, candidate_dest)

    verdict = _invoke_judge(prompt, verdict_path)
    sys.stdout.write(
        f"{args.scenario}: {verdict.get('verdict', '?')} | "
        f"worst_item={verdict.get('worst_item', '?')!r} | "
        f"artifacts={out_dir}\n"
    )
    return 0 if verdict.get("verdict") == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
