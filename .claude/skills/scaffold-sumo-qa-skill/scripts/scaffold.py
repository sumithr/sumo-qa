#!/usr/bin/env python3
"""Scaffold a new sumo-qa sub-skill end-to-end.

Creates:
  1. skills/sumo-qa-<name>/SKILL.md                 (frontmatter + workflow skeleton)
  2. tests/evals/promptfoo/skill-<name>.yaml        (promptfoo eval stub)
  3. Appends ## <approach-tag> to knowledge/approaches.md

Does NOT modify skills/sumo-qa-deciding-approach/SKILL.md — that file has
context-sensitive routing tables that resist mechanical patching. The
caller adds the routing line by hand after this script runs.

Collision checks fire against the source tree only. The skill that invokes
this script is responsible for the separate check against the installed
MCP server (via sumo_qa_load_approaches), since the MCP surface and the
source tree can drift mid-development.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from textwrap import dedent


def normalize_name(raw: str) -> str:
    """Ensure the skill name carries the sumo-qa- prefix per repo policy."""
    return raw if raw.startswith("sumo-qa-") else f"sumo-qa-{raw}"


def find_repo_root(start: Path) -> Path:
    """Walk up looking for pyproject.toml; fall back to the start path."""
    for candidate in [start, *start.parents]:
        if (candidate / "pyproject.toml").is_file():
            return candidate
    return start


def check_collisions(repo_root: Path, full_name: str, approach_tag: str) -> list[str]:
    """Return human-readable collision messages, empty list if clear."""
    problems: list[str] = []

    skill_dir = repo_root / "skills" / full_name
    if skill_dir.exists():
        problems.append(f"skills/{full_name}/ already exists in the source tree")

    eval_name = full_name.removeprefix("sumo-qa-")
    eval_path = repo_root / "tests" / "evals" / "promptfoo" / f"skill-{eval_name}.yaml"
    if eval_path.exists():
        problems.append(f"tests/evals/promptfoo/skill-{eval_name}.yaml already exists")

    approaches = repo_root / "knowledge" / "approaches.md"
    if approaches.is_file():
        existing = approaches.read_text(encoding="utf-8")
        if re.search(rf"^## {re.escape(approach_tag)}\b", existing, re.MULTILINE):
            problems.append(
                f"approach tag '{approach_tag}' already present in knowledge/approaches.md"
            )

    return problems


SKILL_MD_TEMPLATE = dedent("""\
    ---
    name: {full_name}
    description: {description}
    ---

    # <TITLE — replace with a human-readable name, e.g. "Designing LLM Evals". The auto-title cannot infer acronyms like LLM, CI, API, so the contributor sets this by hand.>

    <INTENT — write a 1–3 sentence paragraph: what this skill does, when it triggers, and why it matters. Do not duplicate the frontmatter `description:` verbatim — that sentence is the trigger; this paragraph is the orientation for the assistant once the skill is active.>

    **Announce at start:** *"<ANNOUNCE — short phrase the assistant says when the skill activates, e.g. 'Walking the eval-design loop.'>"*

    ## Output discipline (mandatory)

    Inherits the global discipline from `using-sumo-qa` (knowledge authority hierarchy, internal scaffolding stays internal, specialty-tool fit).

    ## Output economy (mandatory)

    Spend output tokens on findings, not framing.

    ## Workflow

    1. **<FIRST_STEP_NAME>.** What gets gathered or loaded.
    2. **<SECOND_STEP_NAME>.** The decision or transformation.
    3. **<THIRD_STEP_NAME>.** The artefact handed back to the user.

    ## Constraints

    - <CONSTRAINT — explain the reason, not just the rule.>
    - <CONSTRAINT — explain the reason, not just the rule.>
""")


EVAL_YAML_TEMPLATE = dedent("""\
    description: >
      Skill-isolation eval for {full_name}. One seed scenario; expand via
      `promptfoo generate dataset` once the seed produces stable output.

    providers:
      - id: openai:chat:gpt-4o-mini
        label: candidate-gpt-4o-mini
        config:
          temperature: 0.0
          seed: 42

    defaultTest:
      vars:
        skill_content: file://../../../skills/{full_name}/SKILL.md
        loaded_techniques: file://../../../knowledge/techniques.md
        expected_shape: >-
          <REPLACE THIS PLACEHOLDER. Describe the concrete artefact the candidate
          must produce — file paths, named techniques, pinned phrases, refused
          actions, the exact handoff line. Vague language here = vague candidate
          output = noisy grading. The eval will FAIL on every run until this is
          filled in with a real expectation.>
        anti_patterns:
          - >-
            <REPLACE — name a specific failure shape, e.g. 'Writes production
            fix in same turn (Iron Law: red phase is test-only).'>
          - >-
            <REPLACE — name a second specific failure shape.>
      assert:
        - type: llm-rubric
          value: |
            **Expected shape:** {{{{expected_shape}}}}

            **Anti-patterns (any PRESENT = FAIL — apply the decision table):**
            {{% for ap in anti_patterns %}}
            - {{{{ ap }}}}
            {{% endfor %}}
        - type: javascript
          # Replace the regex with the techniques / pinned phrases this skill
          # must surface. Reference shape: skill-implementing-with-tdd.yaml
          # uses /boundary value analysis|equivalence partitioning|.../i so
          # candidate output is forced to cite a real catalogue technique.
          value: 'output.match(/<TECHNIQUE_OR_PINNED_PHRASE_1>|<TECHNIQUE_OR_PINNED_PHRASE_2>/i) !== null'
          threshold: 1
      options:
        disableVarExpansion: true

    tests:
      - description: <REPLACE — name a concrete situation the skill handles, e.g. 'User asks how to test prompt-injection resistance'.>
        vars:
          ground_truth_context: >-
            <REPLACE — paste the inputs the candidate sees here (file content,
            diff, sibling test, error message). Keep it short and concrete;
            promptfoo grades the candidate's grounding against this exact text.>
        # Add a `prompt:` override if the default prompt template does not fit.
""")


APPROACHES_BLOCK_TEMPLATE = dedent("""\

    ## {approach_tag}
    {description}
    Next step: load relevant catalogue, then invoke `{full_name}`.
""")


def write_files(
    repo_root: Path,
    full_name: str,
    description: str,
    approach_tag: str,
) -> list[Path]:
    """Write the three scaffold files. Returns the paths written."""
    written: list[Path] = []

    skill_dir = repo_root / "skills" / full_name
    skill_dir.mkdir(parents=True, exist_ok=False)
    skill_md = skill_dir / "SKILL.md"
    skill_md.write_text(
        SKILL_MD_TEMPLATE.format(
            full_name=full_name,
            description=description,
        ),
        encoding="utf-8",
    )
    written.append(skill_md)

    eval_name = full_name.removeprefix("sumo-qa-")
    eval_path = repo_root / "tests" / "evals" / "promptfoo" / f"skill-{eval_name}.yaml"
    eval_path.parent.mkdir(parents=True, exist_ok=True)
    eval_path.write_text(
        EVAL_YAML_TEMPLATE.format(full_name=full_name),
        encoding="utf-8",
    )
    written.append(eval_path)

    approaches = repo_root / "knowledge" / "approaches.md"
    approaches.parent.mkdir(parents=True, exist_ok=True)
    existing = approaches.read_text(encoding="utf-8") if approaches.is_file() else ""
    if not existing.endswith("\n"):
        existing += "\n"
    approaches.write_text(
        existing
        + APPROACHES_BLOCK_TEMPLATE.format(
            approach_tag=approach_tag,
            description=description,
            full_name=full_name,
        ),
        encoding="utf-8",
    )
    written.append(approaches)

    return written


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--name",
        required=True,
        help="Skill name. Prefix `sumo-qa-` is added if missing.",
    )
    parser.add_argument(
        "--description",
        required=True,
        help="One-line description for SKILL.md frontmatter. Conventionally starts 'Use when ...'.",
    )
    parser.add_argument(
        "--approach-tag",
        required=True,
        help="Kebab-case tag for the routing entry in knowledge/approaches.md (e.g. 'flaky-test-triage').",
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=None,
        help="Repo root override. Default: walk up from cwd looking for pyproject.toml.",
    )
    args = parser.parse_args()

    repo_root = args.repo_root or find_repo_root(Path.cwd())
    full_name = normalize_name(args.name)

    problems = check_collisions(repo_root, full_name, args.approach_tag)
    if problems:
        print("Collision detected — cannot scaffold:", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        print(
            "\nThis check covers the source tree only. The installed MCP server may "
            "have additional entries you also need to check against — call "
            "sumo_qa_load_approaches before retrying.",
            file=sys.stderr,
        )
        return 1

    written = write_files(repo_root, full_name, args.description, args.approach_tag)

    eval_name = full_name.removeprefix("sumo-qa-")
    print(f"Scaffolded {full_name}:")
    for path in written:
        print(f"  - {path.relative_to(repo_root)}")
    print(
        "\nNext (each step is the contributor's responsibility — the scaffold is intentionally incomplete):\n"
        f"  1. Open skills/{full_name}/SKILL.md and replace every <PLACEHOLDER>: the title, the intent paragraph, the announce phrase, the three workflow steps, and the constraints. The eval will FAIL until these are real.\n"
        f"  2. Open tests/evals/promptfoo/skill-{eval_name}.yaml and replace every <PLACEHOLDER>: expected_shape, anti_patterns, the javascript regex, the test description, and the ground_truth_context.\n"
        f"  3. Add the routing line in skills/sumo-qa-deciding-approach/SKILL.md. The routing table is a simple markdown table; the line for this skill is:\n"
        f"     | {args.approach_tag} | {full_name} |\n"
        "  4. Run `sumo-qa-validate` to confirm the catalogue still parses.\n"
        "  5. The new approach tag will not appear in `sumo_qa_load_approaches` output until the package is reinstalled (`pip install -e .`) and the MCP host restarted. Until then, source and installed views disagree — that's expected, not a bug."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
