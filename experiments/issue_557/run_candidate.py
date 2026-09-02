# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Run issue #557's compact candidate against the pinned review scenarios.

This experiment intentionally bypasses promptfoo only for candidate generation
so deterministic gate validation can run before grading.  The emitted review
prose is then graded by each original promptfoo config and rubric unchanged.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import yaml

from sumo_qa.review_gate_poc import (
    ReviewContext,
    ReviewFeedback,
    ReviewGateValidationError,
    validate_review_response,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
PROMPT_PATH = Path(__file__).with_name("compact_review_prompt.md")
REGRESSION_CONTRACTS_PATH = Path(__file__).with_name("regression_contracts.md")
EVAL_ROOT = REPO_ROOT / "tests/evals/promptfoo"
SKILL_PATH = REPO_ROOT / "skills/sumo-qa-reviewing-before-merge/SKILL.md"
_MACHINE_CONTRACT_MARKER = "## Machine-enforced response contract"

# The eval fixture plays the host: its ground-truth block is what a real host
# would hand the boundary as structured context.  Only sections with a stable
# heading are parsed; anything free-form stays instructed in the prompt.
_AC_SECTION_RE = re.compile(
    r"^#+[ \t]*Host-supplied acceptance criteria[^\n]*\n(?P<body>.*?)(?=^#+[ \t]|\Z)",
    re.DOTALL | re.MULTILINE | re.IGNORECASE,
)
_AC_BULLET_RE = re.compile(r"^[ \t]*-[ \t]*AC(?P<number>\d+):[ \t]*(?P<text>.+)$", re.MULTILINE)
_FEEDBACK_SECTION_RE = re.compile(
    r"^#+[ \t]*SAVED REVIEW FEEDBACK[^\n]*\n(?P<body>.*?)(?=^#+[ \t]|\Z)",
    re.DOTALL | re.MULTILINE | re.IGNORECASE,
)
_FEEDBACK_FIELD_RE = re.compile(
    r"^[ \t]*(?:-[ \t]*)?(?P<key>trigger_signal|recommended_probe):[ \t]*(?P<value>.+)$",
    re.MULTILINE,
)


def build_review_context(variables: dict[str, Any]) -> ReviewContext:
    """Build the host-supplied context the deterministic boundary checks against.

    Extracts only what the scenario states under a stable heading.  Inventory
    drift pairs and external producer names are free prose in these fixtures, so
    they are deliberately NOT extracted -- their rules stay in the prompt rather
    than being silently unenforced.
    """
    ground_truth = variables.get("ground_truth_context")
    if not isinstance(ground_truth, str):
        return ReviewContext()

    criteria: list[str] = []
    section = _AC_SECTION_RE.search(ground_truth)
    if section is not None:
        criteria = [
            match.group("text").strip() for match in _AC_BULLET_RE.finditer(section.group("body"))
        ]

    feedback: ReviewFeedback | None = None
    feedback_section = _FEEDBACK_SECTION_RE.search(ground_truth)
    if feedback_section is not None:
        fields = {
            match.group("key"): match.group("value").strip()
            for match in _FEEDBACK_FIELD_RE.finditer(feedback_section.group("body"))
        }
        if "trigger_signal" in fields and "recommended_probe" in fields:
            feedback = ReviewFeedback(
                trigger=fields["trigger_signal"], probe=fields["recommended_probe"]
            )

    return ReviewContext(acceptance_criteria=criteria, saved_review_feedback=feedback)


_CORE_CUT_MARKER = "### Risk-to-test ledger appendix"
_PROCESS_FLOW_MARKER = "## Process Flow"
_RED_FLAGS_MARKER = "## Red Flags — STOP and rework"
_EXAMPLES_MARKER = "## Examples"
_NEXT_SKILL_MARKER = "## Next skill in the chain"
_BALANCED_RED_FLAGS = """## Red Flags — mandatory pre-verdict guard

Before the verdict, rework the review if any statement below is true:

- Verification is stale/partial, or SAFE is inferred from a green suite without a fresh
  failure-mode-matching test for every named risk.
- A discovered risk is demoted to a residual; an UNCOVERED/UNPROVEN risk lacks its
  discriminating input; or that input is deferred to Codex. These remain SAFE-blockers.
- A parser is called proven from code reading or non-discriminating cases. For fence length,
  require the 4-tick-outer/3-tick-inner case; char-only comparison is the defect.
- Executable behavior is treated as trivial because it lives outside app/src/lib. Hooks,
  scripts, CI commands, and automation still require the runtime sweep and ledger.
- An external-output matcher relies on a hand-authored fixture, or a real-run-traceable
  contract is re-blocked by speculative variants. State internal/self-produced declinations.
- A test-only change is accepted because it is green without proving each assertion fails
  against the broken behavior.
- Applicable standards, changed files, repository test layout, or a required user
  confirmation gate were skipped.
- Residual concerns are omitted or stated as `none`. Name the concrete remaining limits,
  including what the completed verification did not exercise.
- Any supplied AC is omitted, fetched by the skill, fabricated, raised beyond its stated
  behavior, or marked MET without both the implementing diff and fresh matching evidence.
  Every UNMET/UNVERIFIED AC blocks SAFE.
- A relevant surface verifier used the wrong runtime/env/scope/tree, sibling results replace
  a combined-tree run, the primary feature flow was not exercised, a guard lacks a true
  negative, or an A/B control can pass through pre-existing rules. Each is a SAFE-blocker.
- A readiness scorecard contradicts the risk/AC ledger or treats stale/unknown evidence as
  ready. Fix the source rows, never weaken the scorecard or rubric.
"""
CANDIDATE_PROFILES = (
    "compact",
    "repaired-compact",
    "full-gated",
    "core-gated",
    "full-plain",
    "routed-root-plain",
    "balanced-plain",
    "warm-plain",
    "core-plain",
)
_VARIABLE_RE = re.compile(r"{{\s*([A-Za-z_][A-Za-z0-9_]*)\s*}}")
REJECTED_REVIEW = (
    "Deterministic gate validation rejected both candidate attempts; no review was returned."
)
_COLD_CONTEXT_VARS = {
    "skill_content",
    "loaded_classifications",
    "loaded_rules",
    "loaded_techniques",
}


@dataclass(frozen=True)
class PinnedGroup:
    config: str
    description_pattern: str


PINNED_GROUPS = {
    "core": PinnedGroup(
        "skill-reviewing-before-merge.yaml",
        r"^SEED - auth helper fix with fresh passing tests$",
    ),
    "adversarial": PinnedGroup(
        "skill-reviewing-before-merge-adversarial.yaml",
        r"weak-assertion|rollback-data-loss|NEGATIVE CONTROL docs-only typo",
    ),
    "verifier": PinnedGroup(
        "skill-reviewing-before-merge-verifier-evidence.yaml",
        r"missing-verifier|discharged",
    ),
    "unproven": PinnedGroup(
        "skill-reviewing-before-merge-unproven-escalation.yaml",
        r"unproven-substring",
    ),
}


def _full_review_groups() -> dict[str, PinnedGroup]:
    groups: dict[str, PinnedGroup] = {}
    prefix = "skill-reviewing-before-merge"
    for path in sorted(EVAL_ROOT.glob(f"{prefix}*.yaml")):
        if path.name.endswith(".ab.yaml"):
            continue
        suffix = path.name.removeprefix(prefix).removesuffix(".yaml").removeprefix("-")
        group_name = f"full-{suffix or 'base'}"
        groups[group_name] = PinnedGroup(path.name, r".*")
    return groups


FULL_REVIEW_GROUPS = _full_review_groups()
ALL_GROUPS = PINNED_GROUPS | FULL_REVIEW_GROUPS


def _sha256(value: str | bytes) -> str:
    data = value.encode() if isinstance(value, str) else value
    return hashlib.sha256(data).hexdigest()


def _resolve_file_value(value: Any, *, config_dir: Path) -> Any:
    if not isinstance(value, str) or not value.startswith("file://"):
        return value
    path = (config_dir / value.removeprefix("file://")).resolve()
    content = path.read_text(encoding="utf-8")
    if path.suffix in {".yaml", ".yml"}:
        return yaml.safe_load(content)
    if path.suffix == ".json":
        return json.loads(content)
    return content.rstrip()


def _resolve_direct_config_value(
    value: Any,
    *,
    config_dir: Path,
    stringify_structured: bool,
) -> Any:
    """Resolve file vars without changing structured rubric variables."""
    resolved = _resolve_file_value(value, config_dir=config_dir)
    if stringify_structured and isinstance(resolved, dict | list):
        return json.dumps(resolved, ensure_ascii=False, separators=(",", ":"))
    return resolved


def _render_prompt(template: str, variables: dict[str, Any]) -> str:
    missing: set[str] = set()

    def replace(match: re.Match[str]) -> str:
        key = match.group(1)
        if key not in variables:
            missing.add(key)
            return match.group(0)
        value = variables[key]
        if isinstance(value, str):
            return value.rstrip()
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))

    rendered = _VARIABLE_RE.sub(replace, template)
    if missing:
        raise ValueError(f"unresolved prompt variable(s): {', '.join(sorted(missing))}")
    return rendered


def candidate_prompt(profile: str) -> str:
    """Build one reproducible candidate from the current production skill."""
    compact = PROMPT_PATH.read_text(encoding="utf-8")
    if profile == "compact":
        return compact
    if profile == "repaired-compact":
        contracts = REGRESSION_CONTRACTS_PATH.read_text(encoding="utf-8").rstrip()
        marker_index = compact.index(_MACHINE_CONTRACT_MARKER)
        return (
            f"{compact[:marker_index].rstrip()}\n\n{contracts}\n\n{compact[marker_index:].lstrip()}"
        )
    if profile not in CANDIDATE_PROFILES:
        raise ValueError(f"unknown candidate profile: {profile}")

    behavior = SKILL_PATH.read_text(encoding="utf-8")
    if profile == "full-plain":
        return behavior
    if profile == "routed-root-plain":
        return (
            behavior[: behavior.index(_CORE_CUT_MARKER)].rstrip()
            + "\n\n"
            + behavior[behavior.index(_PROCESS_FLOW_MARKER) :]
        )
    if profile == "balanced-plain":
        return (
            behavior[: behavior.index(_RED_FLAGS_MARKER)].rstrip()
            + "\n\n"
            + _BALANCED_RED_FLAGS.rstrip()
            + "\n\n"
            + behavior[behavior.index(_EXAMPLES_MARKER) :]
        )
    if profile == "warm-plain":
        return (
            behavior[: behavior.index(_RED_FLAGS_MARKER)].rstrip()
            + "\n\n"
            + behavior[behavior.index(_NEXT_SKILL_MARKER) :]
        )
    if profile == "core-plain":
        return behavior[: behavior.index(_CORE_CUT_MARKER)].rstrip() + "\n"

    contract = compact[compact.index(_MACHINE_CONTRACT_MARKER) :].rstrip()
    if profile == "core-gated":
        behavior = behavior[: behavior.index(_CORE_CUT_MARKER)]
    return f"{behavior.rstrip()}\n\n{contract}\n"


def candidate_prompt_for_group(profile: str, group_name: str) -> str:
    """Apply explicit-intent cold routes without making a QA judgment."""
    if profile == "routed-root-plain" and group_name in {
        "full-ledger",
        "full-scorecard",
    }:
        return candidate_prompt("full-plain")
    return candidate_prompt(profile)


def load_group(group_name: str) -> tuple[dict[str, Any], list[dict[str, Any]], str]:
    group = ALL_GROUPS[group_name]
    config_path = EVAL_ROOT / group.config
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    matcher = re.compile(group.description_pattern)
    tests = [test for test in config["tests"] if matcher.search(test["description"])]
    if not tests:
        raise ValueError(f"no pinned scenarios selected for {group_name}")
    return config, tests, _sha256(config_path.read_bytes())


def build_prompts(
    group_name: str,
    *,
    skill_content: str | None = None,
    candidate_profile: str = "compact",
) -> tuple[str, list[tuple[str, str]], dict[str, str]]:
    config, tests, config_hash = load_group(group_name)
    selected_candidate = candidate_prompt_for_group(candidate_profile, group_name)
    config_dir = (EVAL_ROOT / ALL_GROUPS[group_name].config).parent
    defaults = {
        key: _resolve_file_value(value, config_dir=config_dir)
        for key, value in config.get("defaultTest", {}).get("vars", {}).items()
    }
    selected_skill = (selected_candidate if skill_content is None else skill_content).rstrip()
    defaults["skill_content"] = selected_skill
    template = config["prompts"][0]
    rendered: list[tuple[str, str]] = []
    for test in tests:
        variables = defaults | {
            key: _resolve_file_value(value, config_dir=config_dir)
            for key, value in test.get("vars", {}).items()
        }
        variables["skill_content"] = selected_skill
        rendered.append((test["description"], _render_prompt(template, variables)))

    provider = config["providers"][0]
    model = provider["id"].removeprefix("openai:chat:")
    metadata = {
        "config": ALL_GROUPS[group_name].config,
        "config_sha256": config_hash,
        "compact_prompt_sha256": _sha256(selected_candidate),
        "candidate_profile": candidate_profile,
        "model": model,
    }
    return model, rendered, metadata


def _completion(
    client: httpx.Client,
    *,
    model: str,
    messages: list[dict[str, str]],
    api_key: str,
) -> tuple[str, dict[str, Any]]:
    request_body: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "seed": 42,
    }
    if not model.startswith("gpt-5"):
        request_body["temperature"] = 0.0
    response = client.post(
        "https://api.openai.com/v1/chat/completions",
        headers={"Authorization": f"Bearer {api_key}"},
        json=request_body,
    )
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise RuntimeError(f"OpenAI candidate request failed: {response.text}") from exc
    body = response.json()
    content = body["choices"][0]["message"]["content"]
    if not content:
        raise RuntimeError("candidate returned an empty response")
    return content, body.get("usage", {})


def write_grade_config(group_name: str, reviews: list[str], output_dir: Path) -> Path:
    """Create an echo-provider config with the original rubric and selected tests."""
    config, tests, _ = load_group(group_name)
    if len(reviews) != len(tests):
        raise ValueError(
            f"review count mismatch for {group_name}: got {len(reviews)}, expected {len(tests)}"
        )

    default_test = config["defaultTest"]
    config_dir = (EVAL_ROOT / ALL_GROUPS[group_name].config).parent
    default_vars = {
        key: _resolve_file_value(value, config_dir=config_dir)
        for key, value in default_test.get("vars", {}).items()
        if key not in _COLD_CONTEXT_VARS
    }
    grade_tests = []
    for test, review in zip(tests, reviews, strict=True):
        grade_tests.append(
            {
                "description": test["description"],
                "vars": default_vars
                | {
                    key: _resolve_file_value(value, config_dir=config_dir)
                    for key, value in test.get("vars", {}).items()
                    if key not in _COLD_CONTEXT_VARS
                }
                | {"output": review},
            }
        )

    grade_config = {
        "description": f"Issue #557 unchanged-rubric grading: {group_name}",
        "providers": ["echo"],
        "prompts": ["{{output}}"],
        "defaultTest": {
            "assert": default_test["assert"],
            "options": default_test["options"],
        },
        "tests": grade_tests,
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"candidate-{group_name}-grade-config.yaml"
    path.write_text(
        yaml.safe_dump(grade_config, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    return path


def build_direct_config(group_name: str, *, candidate_profile: str) -> dict[str, Any]:
    """Build a Promptfoo config that replaces only the production skill body."""
    config, tests, _ = load_group(group_name)
    config_dir = (EVAL_ROOT / ALL_GROUPS[group_name].config).parent
    selected_skill = candidate_prompt_for_group(candidate_profile, group_name).rstrip()
    direct = dict(config)
    direct["description"] = f"Issue #557 direct candidate: {group_name} ({candidate_profile})"
    default_test = dict(config.get("defaultTest", {}))
    default_test["vars"] = {
        key: _resolve_direct_config_value(
            value,
            config_dir=config_dir,
            stringify_structured=key in _COLD_CONTEXT_VARS,
        )
        for key, value in default_test.get("vars", {}).items()
    } | {"skill_content": selected_skill}
    direct["defaultTest"] = default_test
    direct["tests"] = []
    for test in tests:
        direct_test = dict(test)
        direct_test["vars"] = {
            key: _resolve_direct_config_value(
                value,
                config_dir=config_dir,
                stringify_structured=key in _COLD_CONTEXT_VARS,
            )
            for key, value in test.get("vars", {}).items()
            if key != "skill_content"
        }
        direct["tests"].append(direct_test)
    return direct


def write_direct_config(
    group_name: str,
    output_dir: Path,
    *,
    candidate_profile: str,
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"candidate-direct-{group_name}-config.yaml"
    path.write_text(
        yaml.safe_dump(
            build_direct_config(group_name, candidate_profile=candidate_profile),
            sort_keys=False,
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    return path


def validate_result_record(record: dict[str, Any]) -> tuple[str, int, int]:
    """Revalidate one stored candidate record and return review plus billed usage."""
    if record.get("validation_passed") is False:
        raise ValueError("candidate did not pass deterministic validation")
    attempts = record.get("attempts")
    if not isinstance(attempts, list) or not 1 <= len(attempts) <= 2:
        raise ValueError("candidate record must contain one or two attempts")

    prompt_tokens = 0
    completion_tokens = 0
    for index, attempt in enumerate(attempts, start=1):
        if not isinstance(attempt, dict):
            raise ValueError("candidate attempt must be an object")
        if attempt.get("number") != index:
            raise ValueError("candidate attempt numbers must be sequential")
        usage = attempt.get("usage")
        if not isinstance(usage, dict):
            raise ValueError("candidate attempt is missing usage")
        prompt = usage.get("prompt_tokens")
        completion = usage.get("completion_tokens")
        total = usage.get("total_tokens")
        if (
            type(prompt) is not int
            or type(completion) is not int
            or type(total) is not int
            or prompt <= 0
            or completion <= 0
            or total != prompt + completion
        ):
            raise ValueError("candidate attempt usage must be positive and internally consistent")
        prompt_tokens += prompt
        completion_tokens += completion

        response = attempt.get("response")
        if not isinstance(response, str) or not response:
            raise ValueError("candidate attempt is missing its raw response")
        if index < len(attempts):
            try:
                validate_review_response(response)
            except ReviewGateValidationError:
                continue
            raise ValueError("candidate retried after an already-valid response")

    try:
        validated = validate_review_response(attempts[-1]["response"])
    except ReviewGateValidationError as exc:
        raise ValueError(f"selected candidate response is invalid: {exc}") from exc
    if record.get("review") != validated.review:
        raise ValueError("stored review does not match the validated raw response")
    if record.get("gate_report") != validated.report.model_dump():
        raise ValueError("stored gate report does not match the validated raw response")
    if record.get("safe_to_merge") is not validated.safe_to_merge:
        raise ValueError("stored verdict does not match the validated raw response")
    return validated.review, prompt_tokens, completion_tokens


def run_group(group_name: str, output_dir: Path, *, candidate_profile: str = "compact") -> Path:
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is required")

    model, scenarios, metadata = build_prompts(
        group_name,
        candidate_profile=candidate_profile,
    )
    results: list[dict[str, Any]] = []
    reviews: list[str] = []
    with httpx.Client(timeout=300) as client:
        for description, prompt in scenarios:
            messages = [{"role": "user", "content": prompt}]
            attempts: list[dict[str, Any]] = []
            validated = None
            validation_error: str | None = None
            for attempt_number in (1, 2):
                raw, usage = _completion(
                    client,
                    model=model,
                    messages=messages,
                    api_key=api_key,
                )
                attempts.append({"number": attempt_number, "usage": usage, "response": raw})
                try:
                    validated = validate_review_response(raw)
                    break
                except ReviewGateValidationError as exc:
                    validation_error = str(exc)
                    if attempt_number == 2:
                        break
                    messages.extend(
                        [
                            {"role": "assistant", "content": raw},
                            {
                                "role": "user",
                                "content": (
                                    "Deterministic gate rejection: "
                                    f"{exc}. Return the complete corrected GATE_REPORT and REVIEW "
                                    "envelopes. If an evidence source is missing from REVIEW, add an "
                                    "explicit 'Command: <observed command> -> <observed result>' line "
                                    "using only the supplied evidence. Evidence in GATE_REPORT alone "
                                    "does not support the visible verdict. Do not change your QA judgment "
                                    "merely to pass validation."
                                ),
                            },
                        ]
                    )

            if validated is None:
                reviews.append(REJECTED_REVIEW)
                results.append(
                    {
                        "description": description,
                        "rendered_prompt_sha256": _sha256(prompt),
                        "rendered_prompt_characters": len(prompt),
                        "attempts": attempts,
                        "validation_passed": False,
                        "validation_error": validation_error,
                        "gate_report": None,
                        "safe_to_merge": None,
                        "review": None,
                    }
                )
                continue
            reviews.append(validated.review)
            results.append(
                {
                    "description": description,
                    "rendered_prompt_sha256": _sha256(prompt),
                    "rendered_prompt_characters": len(prompt),
                    "attempts": attempts,
                    "validation_passed": True,
                    "validation_error": None,
                    "gate_report": validated.report.model_dump(),
                    "safe_to_merge": validated.safe_to_merge,
                    "review": validated.review,
                }
            )

    output_dir.mkdir(parents=True, exist_ok=True)
    result_path = output_dir / f"candidate-{group_name}.json"
    model_outputs_path = output_dir / f"candidate-{group_name}-outputs.json"
    result_path.write_text(
        json.dumps({"group": group_name, **metadata, "results": results}, indent=2) + "\n",
        encoding="utf-8",
    )
    model_outputs_path.write_text(json.dumps(reviews, indent=2) + "\n", encoding="utf-8")
    write_grade_config(group_name, reviews, output_dir)
    return result_path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("group", nargs="?", choices=ALL_GROUPS)
    parser.add_argument(
        "--all-review",
        action="store_true",
        help="run all non-control reviewing-before-merge eval scenarios",
    )
    parser.add_argument("--output-dir", type=Path, default=Path("/private/tmp/issue557"))
    parser.add_argument("--profile", choices=CANDIDATE_PROFILES, default="compact")
    parser.add_argument("--grade-from-result", type=Path)
    parser.add_argument(
        "--write-direct-configs",
        action="store_true",
        help="write direct Promptfoo configs for provider-independent screening",
    )
    args = parser.parse_args()
    if args.all_review:
        if args.group is not None or args.grade_from_result is not None:
            parser.error("--all-review cannot be combined with group or --grade-from-result")
        if args.write_direct_configs:
            if not (args.profile.endswith("-plain") or args.profile == "repaired-compact"):
                parser.error(
                    "--write-direct-configs requires a *-plain or repaired-compact profile"
                )
            for group_name in FULL_REVIEW_GROUPS:
                print(
                    write_direct_config(
                        group_name,
                        args.output_dir,
                        candidate_profile=args.profile,
                    )
                )
            return
        for group_name in FULL_REVIEW_GROUPS:
            print(run_group(group_name, args.output_dir, candidate_profile=args.profile))
        return
    if args.write_direct_configs:
        parser.error("--write-direct-configs requires --all-review")
    if args.group is None:
        parser.error("group is required unless --all-review is used")
    if args.grade_from_result is not None:
        result = json.loads(args.grade_from_result.read_text(encoding="utf-8"))
        reviews = [
            REJECTED_REVIEW
            if item.get("validation_passed") is False
            else validate_result_record(item)[0]
            for item in result["results"]
        ]
        print(write_grade_config(args.group, reviews, args.output_dir))
        return
    print(run_group(args.group, args.output_dir, candidate_profile=args.profile))


if __name__ == "__main__":
    main()
