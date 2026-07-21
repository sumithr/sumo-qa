# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Regrade captured direct outputs after correcting experiment-only rubric serialization."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
from typing import Any

from .compare_results import (
    _direct_config_matches,
    _direct_positive_usage,
    _grade_config_matches,
    _grading_result_matches,
)
from .run_candidate import (
    FULL_REVIEW_GROUPS,
    build_direct_config,
    build_prompts,
    candidate_prompt_for_group,
    load_group,
    write_grade_config,
)


def _read(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _source_path(source_dir: Path, group: str) -> Path:
    merged = source_dir / f"candidate-direct-{group}-merged.json"
    return merged if merged.exists() else source_dir / f"candidate-direct-{group}.json"


def prepare_outputs(source_dir: Path, output_dir: Path) -> None:
    """Extract exact captured model outputs for Promptfoo's --model-outputs mode."""
    output_dir.mkdir(parents=True, exist_ok=True)
    for group in FULL_REVIEW_GROUPS:
        source_path = _source_path(source_dir, group)
        source = _read(source_path)
        rows = source.get("results", {}).get("results", [])
        _, tests, _ = load_group(group)
        if len(rows) != len(tests):
            raise ValueError(f"scenario count mismatch for {group}")
        outputs: list[str] = []
        for row, test in zip(rows, tests, strict=True):
            if row.get("testCase", {}).get("description") != test["description"]:
                raise ValueError(f"scenario mismatch for {group}")
            output = row.get("response", {}).get("output")
            if not isinstance(output, str) or not output:
                raise ValueError(f"missing captured output for {group}")
            outputs.append(output)
        path = output_dir / f"candidate-direct-{group}-outputs.json"
        path.write_text(json.dumps(outputs, indent=2) + "\n", encoding="utf-8")
        write_grade_config(group, outputs, output_dir)


def merge_regraded(
    source_dir: Path,
    regrade_dir: Path,
    output_dir: Path,
    *,
    candidate_profile: str,
) -> None:
    """Combine captured generation usage with a corrected no-generation regrade."""
    output_dir.mkdir(parents=True, exist_ok=True)
    for group in FULL_REVIEW_GROUPS:
        source_path = _source_path(source_dir, group)
        regrade_path = regrade_dir / f"candidate-{group}-grade.json"
        source = _read(source_path)
        regraded = _read(regrade_path)
        expected_config = build_direct_config(group, candidate_profile=candidate_profile)
        selected_skill = candidate_prompt_for_group(candidate_profile, group)
        _, scenarios, _ = build_prompts(group, skill_content=selected_skill)
        current_config, tests, _ = load_group(group)
        source_rows = source.get("results", {}).get("results", [])
        regrade_rows = regraded.get("results", {}).get("results", [])
        if not len(source_rows) == len(regrade_rows) == len(tests):
            raise ValueError(f"scenario count mismatch for {group}")

        assertions = expected_config.get("defaultTest", {}).get("assert", [])
        outputs = [row.get("response", {}).get("output") for row in source_rows]
        if not _grade_config_matches(
            regraded.get("config"),
            current_config,
            tests,
            outputs,
            group=group,
            allow_provider_override=True,
        ):
            raise ValueError(f"corrected grade config mismatch for {group}")

        merged = copy.deepcopy(source)
        merged_rows = merged["results"]["results"]
        source_row_usage = [0, 0]
        for source_row, regrade_row, merged_row, scenario, test in zip(
            source_rows,
            regrade_rows,
            merged_rows,
            scenarios,
            tests,
            strict=True,
        ):
            description = test["description"]
            output = source_row.get("response", {}).get("output")
            if (
                source_row.get("testCase", {}).get("description") != description
                or regrade_row.get("testCase", {}).get("description") != description
                or source_row.get("prompt", {}).get("raw") != scenario[1]
                or not isinstance(output, str)
                or regrade_row.get("prompt", {}).get("raw") != output
                or regrade_row.get("response", {}).get("output") != output
            ):
                raise ValueError(f"prompt/output binding mismatch for {group}: {description}")
            if not _grading_result_matches(
                regrade_row,
                assertions=assertions,
                graded_output=output,
                allow_reasoning_usage=True,
            ):
                raise ValueError(f"invalid corrected grade for {group}: {description}")
            row_usage = _direct_positive_usage(
                source_row.get("response", {}).get("tokenUsage"),
                minimum_requests=1,
            )
            if row_usage is None:
                raise ValueError(f"invalid captured usage for {group}: {description}")
            source_row_usage[0] += row_usage[0]
            source_row_usage[1] += row_usage[1]
            direct_test = expected_config["defaultTest"]["vars"] | next(
                item.get("vars", {})
                for item in expected_config["tests"]
                if item["description"] == description
            )
            merged_row["testCase"] = {
                "description": description,
                "vars": copy.deepcopy(direct_test),
                "assert": copy.deepcopy(assertions),
                "options": copy.deepcopy(regrade_row["testCase"]["options"]),
            }
            for key in ("success", "score", "namedScores", "gradingResult"):
                if key in regrade_row:
                    merged_row[key] = copy.deepcopy(regrade_row[key])

        source_usage = source.get("results", {}).get("stats", {}).get("tokenUsage")
        validated_usage = _direct_positive_usage(source_usage, minimum_requests=len(tests))
        if validated_usage is None or tuple(source_row_usage) != validated_usage:
            raise ValueError(f"captured aggregate usage mismatch for {group}")
        merged_usage = copy.deepcopy(source_usage)
        merged_usage["assertions"] = copy.deepcopy(
            regraded["results"]["stats"]["tokenUsage"].get("assertions")
        )
        merged_stats = copy.deepcopy(regraded["results"]["stats"])
        merged_stats["tokenUsage"] = merged_usage
        merged["results"]["stats"] = merged_stats
        merged_config = copy.deepcopy(expected_config)
        merged_config["defaultTest"]["options"] = copy.deepcopy(
            regraded["config"]["defaultTest"]["options"]
        )
        if not _direct_config_matches(merged_config, expected_config):
            raise ValueError(f"merged direct config mismatch for {group}")
        merged["config"] = merged_config
        merged["issue557_regrade_provenance"] = {
            "source": str(source_path),
            "source_sha256": _sha256(source_path),
            "regrade": str(regrade_path),
            "regrade_sha256": _sha256(regrade_path),
            "candidate_generation_reused": True,
            "rubric_regraded": True,
        }
        output_path = output_dir / f"candidate-direct-{group}.json"
        output_path.write_text(json.dumps(merged, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("prepare", "merge"))
    parser.add_argument("--source-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--regrade-dir", type=Path)
    parser.add_argument("--profile", choices=("full-plain", "routed-root-plain"))
    args = parser.parse_args()
    if args.mode == "prepare":
        prepare_outputs(args.source_dir, args.output_dir)
        return
    if args.regrade_dir is None or args.profile is None:
        parser.error("merge requires --regrade-dir and --profile")
    merge_regraded(
        args.source_dir,
        args.regrade_dir,
        args.output_dir,
        candidate_profile=args.profile,
    )


if __name__ == "__main__":
    main()
