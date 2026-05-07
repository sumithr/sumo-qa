"""Test scaffolder.

Given a work item, a list of test conditions, and (optionally) target source
paths, produce a structured list of scaffold tasks the host model can execute
with its own file-write tools.

The MCP itself never writes files. It produces honestly-stubbed templates with
named assertions, file paths chosen by convention, and a verify command per
task. The host model:
  1. shows the task list to the user,
  2. writes each file (skeleton + assertions),
  3. runs the verify command, sees the test fail (red),
  4. either implements the production code or hands off to a specialty MCP.

This module is deterministic. Sampling-aware enrichment of the skeleton
happens upstream in tools.aqa_scaffold_tests.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any


_LEVELS = ("unit", "integration", "contract", "functional", "nonfunctional")


def build_scaffold_tasks(
    work_item: str,
    test_conditions: list[str],
    target_paths: list[str],
    classifications: list[str],
    suggested_test_types: list[str],
    test_design_techniques: list[str],
    specialty_needs: list[dict[str, Any]],
) -> dict[str, Any]:
    """Return {tasks, execution_order} for the given inputs.

    Tasks are emitted at the test levels named by `suggested_test_types`,
    plus any specialty tasks routed by `specialty_needs`.
    """
    primary_path = target_paths[0] if target_paths else ""
    primary_layout = _detect_layout(primary_path)

    tasks: list[dict[str, Any]] = []
    counter = 1

    levels_in_scope = [lvl for lvl in suggested_test_types if lvl in _LEVELS]
    if not levels_in_scope:
        levels_in_scope = ["unit"]

    for level in levels_in_scope:
        framework = _framework_for(level, primary_layout, specialty_needs)
        # Skip levels whose framework is owned by a specialty entry - the
        # specialty task below will represent it instead.
        if _level_owned_by_specialty(level, specialty_needs):
            continue
        task = _build_task(
            task_id=f"T{counter}",
            work_item=work_item,
            test_conditions=test_conditions,
            primary_path=primary_path,
            level=level,
            framework=framework,
            techniques=test_design_techniques,
            specialty=None,
        )
        tasks.append(task)
        counter += 1

    # Specialty-driven tasks (frontend E2E, perf, contract, security, mobile, AI/ML).
    for specialty in specialty_needs:
        framework, level, language_override = _framework_for_specialty(specialty["id"])
        if framework is None:
            continue
        task = _build_task(
            task_id=f"T{counter}",
            work_item=work_item,
            test_conditions=test_conditions,
            primary_path=primary_path,
            level=level,
            framework=framework,
            techniques=test_design_techniques,
            specialty=specialty,
            language_override=language_override,
        )
        tasks.append(task)
        counter += 1

    execution_order = _order_by_level(tasks)
    return {"tasks": tasks, "execution_order": execution_order}


# ---------- Layout / framework detection ----------


def _detect_layout(path: str) -> str:
    if not path:
        return "python-pytest"
    lower = path.lower()
    if lower.endswith((".tsx", ".jsx", ".ts", ".js", ".vue", ".svelte")):
        return "node-jest"
    if lower.endswith((".py",)):
        return "python-pytest"
    if lower.endswith((".java", ".kt")):
        return "jvm-junit5"
    if lower.endswith((".swift",)):
        return "swift-xctest"
    return "python-pytest"


def _framework_for(level: str, layout: str, specialty_needs: list[dict[str, Any]]) -> str:
    # If any frontend specialty exists, frontend levels prefer Playwright/Cypress.
    if level == "functional" and _has_specialty(specialty_needs, "frontend_e2e"):
        return "Playwright"
    if level == "nonfunctional" and _has_specialty(specialty_needs, "performance_testing"):
        return "k6"
    if level == "contract" and _has_specialty(specialty_needs, "contract_testing"):
        return "Schemathesis"
    if layout == "python-pytest":
        return "pytest"
    if layout == "node-jest":
        if level in ("unit", "integration"):
            return "Vitest" if level == "unit" else "Jest"
        return "Playwright"
    if layout == "jvm-junit5":
        return "JUnit 5"
    if layout == "swift-xctest":
        return "XCTest"
    return "pytest"


def _framework_for_specialty(specialty_id: str) -> tuple[str | None, str, str | None]:
    """Return (framework_name, test_level, language_override) for a specialty."""
    return {
        "frontend_e2e": ("Playwright", "functional", "typescript"),
        "performance_testing": ("k6", "nonfunctional", "javascript"),
        "contract_testing": ("Schemathesis", "contract", "python"),
        "security_testing": ("Semgrep + ZAP baseline", "nonfunctional", None),
        "mobile_testing": ("Appium", "functional", None),
        "ai_ml_testing": ("Promptfoo", "functional", "yaml"),
        "accessibility_testing": ("axe-core via Playwright", "functional", "typescript"),
    }.get(specialty_id, (None, "functional", None))


def _level_owned_by_specialty(level: str, specialty_needs: list[dict[str, Any]]) -> bool:
    """If a specialty already covers this level, skip the generic task to avoid duplication."""
    if level == "functional" and _has_specialty(specialty_needs, "frontend_e2e"):
        return True
    if level == "nonfunctional" and _has_specialty(specialty_needs, "performance_testing"):
        return True
    if level == "contract" and _has_specialty(specialty_needs, "contract_testing"):
        return True
    return False


def _has_specialty(specialty_needs: list[dict[str, Any]], specialty_id: str) -> bool:
    return any(entry.get("id") == specialty_id for entry in specialty_needs)


# ---------- Task / file path / skeleton ----------


def _build_task(
    *,
    task_id: str,
    work_item: str,
    test_conditions: list[str],
    primary_path: str,
    level: str,
    framework: str,
    techniques: list[str],
    specialty: dict[str, Any] | None,
    language_override: str | None = None,
) -> dict[str, Any]:
    file_path = _file_path_for(framework, primary_path, level, specialty)
    language = language_override or _language_for(framework)
    assertions = _assertions_for(test_conditions, techniques, level)
    skeleton = _skeleton_for(framework, language, work_item, level, assertions, techniques)
    verify_command = _verify_command_for(framework, file_path)

    title = (
        f"{level.title()} test: {_short_subject(primary_path) or _short_subject(work_item)}"
        if specialty is None
        else f"{specialty['approach']} ({framework})"
    )
    task: dict[str, Any] = {
        "id": task_id,
        "title": title,
        "file_path": file_path,
        "framework": framework,
        "language": language,
        "level": level,
        "techniques": techniques[:3],
        "assertions": assertions,
        "skeleton": skeleton,
        "verify_command": verify_command,
        "after_writing": (
            f"Run: {verify_command}. Expect every assertion to fail (red phase). "
            "Then implement production code, then re-run until green."
        ),
        "specialty": specialty["id"] if specialty else None,
    }
    if specialty:
        task["specialty_mcp_hint"] = specialty["mcp_hint"]
        task["well_known_tools"] = specialty["well_known_tools"]
    return task


def _short_subject(text: str) -> str:
    if not text:
        return ""
    if "/" in text or text.endswith(".py") or text.endswith(".ts") or text.endswith(".tsx"):
        stem = Path(text).stem
        return stem
    return " ".join(text.split()[:5])


def _file_path_for(framework: str, primary_path: str, level: str, specialty: dict[str, Any] | None) -> str:
    suffix_for_level = {
        "unit": "",
        "integration": "_integration",
        "contract": "_contract",
        "functional": "_functional",
        "nonfunctional": "_perf",
    }
    suffix = suffix_for_level.get(level, "")

    # Specialty paths follow the specialty's conventional layout.
    if specialty:
        sid = specialty["id"]
        stem = Path(primary_path).stem if primary_path else "feature"
        if sid == "frontend_e2e":
            return f"e2e/{stem}.spec.ts"
        if sid == "accessibility_testing":
            return f"e2e/{stem}.a11y.spec.ts"
        if sid == "performance_testing":
            return f"perf/{stem}.k6.js"
        if sid == "contract_testing":
            return f"tests/contract/test_{stem}_contract.py"
        if sid == "security_testing":
            return f"security/{stem}_zap_baseline.yaml"
        if sid == "mobile_testing":
            return f"mobile-e2e/{stem}.appium.ts"
        if sid == "ai_ml_testing":
            return f"prompt-evals/{stem}.promptfoo.yaml"

    # Generic, layout-aware paths.
    if framework == "pytest":
        if primary_path:
            primary = Path(primary_path)
            stem = primary.stem
            parent_parts = [p for p in primary.parent.parts if p not in {"", ".", "src"}]
            parent = "/".join(parent_parts)
            return f"tests/{parent + '/' if parent else ''}test_{stem}{suffix}.py"
        return f"tests/test_feature{suffix}.py"
    if framework in {"Vitest", "Jest"}:
        if primary_path:
            primary = Path(primary_path)
            stem = primary.stem
            parent_parts = [p for p in primary.parent.parts if p not in {"", ".", "src"}]
            parent = "/".join(parent_parts)
            return f"src/{parent + '/' if parent else ''}__tests__/{stem}{suffix}.test.ts"
        return f"src/__tests__/feature{suffix}.test.ts"
    if framework == "JUnit 5":
        stem = Path(primary_path).stem if primary_path else "Feature"
        return f"src/test/java/{stem}Test{suffix}.java"
    if framework == "XCTest":
        stem = Path(primary_path).stem if primary_path else "Feature"
        return f"Tests/{stem}Tests{suffix}.swift"
    return f"tests/test_feature{suffix}.txt"


def _language_for(framework: str) -> str:
    return {
        "pytest": "python",
        "Schemathesis": "python",
        "Vitest": "typescript",
        "Jest": "typescript",
        "Playwright": "typescript",
        "k6": "javascript",
        "JUnit 5": "java",
        "XCTest": "swift",
        "Appium": "typescript",
        "Promptfoo": "yaml",
        "Semgrep + ZAP baseline": "yaml",
        "axe-core via Playwright": "typescript",
    }.get(framework, "text")


def _assertions_for(test_conditions: list[str], techniques: list[str], level: str) -> list[str]:
    if not test_conditions:
        return ["TODO: name the test condition this assertion proves"]
    named: list[str] = []
    for condition in test_conditions:
        named.append(condition.strip().rstrip(".") + ".")
    # If boundary value analysis is in scope, add boundary triplet hints.
    techs_text = " ".join(techniques).lower()
    if "boundary value" in techs_text and level == "unit":
        named.append("Boundary: just-under, at, and just-over the threshold each behave correctly.")
    if "decision table" in techs_text and level in ("unit", "integration"):
        named.append("Decision table: every relevant rule combination has at least one row covered.")
    if "state transition" in techs_text and level in ("unit", "integration"):
        named.append("State transition: at least one invalid transition is rejected.")
    return named


def _skeleton_for(
    framework: str,
    language: str,
    work_item: str,
    level: str,
    assertions: list[str],
    techniques: list[str],
) -> str:
    """Honest skeleton - assertions raise NotImplementedError / TODO so the
    host model knows nothing has been verified yet (TDD red phase).
    """
    techs = ", ".join(techniques[:3]) or "ISTQB techniques relevant to the change"
    if framework == "pytest":
        body = "\n".join(
            f"def test_{_slug(a)}() -> None:\n"
            "    # Arrange\n"
            "    # Act\n"
            "    # Assert\n"
            f"    raise NotImplementedError({a!r})\n"
            for a in assertions
        )
        return (
            f'"""\n{level.title()} tests for: {work_item}\n\n'
            f"Techniques: {techs}\n\"\"\"\n"
            "import pytest  # noqa: F401\n\n\n"
            f"{body}"
        )
    if framework in {"Vitest", "Jest"}:
        body = "\n".join(
            f"  it({a!r}, () => {{\n"
            "    // Arrange\n    // Act\n    // Assert\n"
            f"    throw new Error('TODO: {a}');\n"
            "  });\n"
            for a in assertions
        )
        suite_name = _suite_name(work_item)
        return (
            f"// {level.title()} tests for: {work_item}\n"
            f"// Techniques: {techs}\n\n"
            "import { describe, it, expect } from 'vitest';\n\n"
            f"describe({suite_name!r}, () => {{\n{body}}});\n"
        )
    if framework == "Playwright":
        body = "\n".join(
            f"  test({a!r}, async ({{ page }}) => {{\n"
            "    // Arrange: navigate / set state\n"
            "    // Act: interact\n"
            "    // Assert: visible behaviour\n"
            f"    test.fixme(true, 'TODO: {a}');\n"
            "  });\n"
            for a in assertions
        )
        suite_name = _suite_name(work_item)
        return (
            f"// E2E tests for: {work_item}\n"
            f"// Techniques: {techs}\n\n"
            "import { test, expect } from '@playwright/test';\n\n"
            f"test.describe({suite_name!r}, () => {{\n{body}}});\n"
        )
    if framework == "k6":
        return (
            f"// k6 perf scenario for: {work_item}\n"
            f"// Techniques: {techs}\n\n"
            "import http from 'k6/http';\n"
            "import { check, sleep } from 'k6';\n\n"
            "export const options = {\n"
            "  // TODO: choose vus, duration, and thresholds based on the SLA.\n"
            "  vus: 10,\n  duration: '30s',\n"
            "  thresholds: {\n    http_req_duration: ['p(95)<500'], // TODO: tune to SLA\n  },\n};\n\n"
            "export default function () {\n"
            "  // TODO: hit the endpoint under test\n"
            "  const res = http.get('http://localhost:8080/health');\n"
            "  check(res, { 'status was 200': (r) => r.status === 200 });\n"
            "  sleep(1);\n"
            "}\n"
        )
    if framework == "Schemathesis":
        return (
            f'"""\nContract tests for: {work_item}\n\n'
            f"Techniques: {techs}\n\"\"\"\n"
            "import schemathesis\n\n"
            "# TODO: point this at the OpenAPI spec served by the service under test.\n"
            "schema = schemathesis.from_uri('http://localhost:8080/openapi.json')\n\n\n"
            "@schema.parametrize()\n"
            "def test_api_contract(case):\n"
            "    # TODO: configure auth headers if needed.\n"
            "    response = case.call()\n"
            "    case.validate_response(response)\n"
        )
    if framework == "Promptfoo":
        return (
            f"# Promptfoo evaluation for: {work_item}\n"
            f"# Techniques: {techs}\n\n"
            "providers:\n  - id: openai:gpt-4o-mini  # TODO: pin to your team's model\n\n"
            "prompts:\n  - file://prompts/system.md  # TODO: real prompt\n\n"
            "tests:\n"
            "  # TODO: each entry is a test condition with assert expectations.\n"
            "  - description: TODO\n    vars:\n      input: TODO\n    assert:\n      - type: contains\n        value: TODO\n"
        )
    if framework == "axe-core via Playwright":
        return (
            f"// Accessibility tests for: {work_item}\n"
            "import { test, expect } from '@playwright/test';\n"
            "import AxeBuilder from '@axe-core/playwright';\n\n"
            "test('no automatically-detectable WCAG violations', async ({ page }) => {\n"
            "  // TODO: navigate to the page under test\n"
            "  await page.goto('/');\n"
            "  const results = await new AxeBuilder({ page }).analyze();\n"
            "  expect(results.violations).toEqual([]);\n"
            "});\n"
        )
    if framework == "Semgrep + ZAP baseline":
        return (
            f"# Security baseline for: {work_item}\n"
            "# 1) Run semgrep with the rule packs that match the change.\n"
            "# semgrep --config p/owasp-top-ten --error src/\n\n"
            "# 2) Run an OWASP ZAP baseline scan against a staging URL.\n"
            "# docker run -t owasp/zap2docker-stable zap-baseline.py -t https://staging.example/api\n"
            "# TODO: wire both into CI; treat findings >= medium as blocking.\n"
        )
    if framework == "Appium":
        return (
            f"// Appium mobile E2E for: {work_item}\n"
            "// TODO: point at your device farm capabilities.\n"
            "describe('mobile flow', () => {\n"
            "  it('TODO: scenario', async () => {\n"
            "    throw new Error('TODO: write the steps');\n"
            "  });\n});\n"
        )
    if framework == "JUnit 5":
        body = "\n".join(
            "  @Test\n"
            f"  void {_slug(a)}() {{\n"
            f"    // TODO: {a}\n"
            "    fail(\"not implemented\");\n"
            "  }\n"
            for a in assertions
        )
        return (
            f"// {level.title()} tests for: {work_item}\n"
            "import org.junit.jupiter.api.Test;\n"
            "import static org.junit.jupiter.api.Assertions.fail;\n\n"
            "class FeatureTest {\n"
            f"{body}}}\n"
        )
    if framework == "XCTest":
        body = "\n".join(
            f"    func test_{_slug(a)}() {{\n"
            f"        // TODO: {a}\n"
            "        XCTFail(\"not implemented\")\n"
            "    }\n"
            for a in assertions
        )
        return (
            f"// {level.title()} tests for: {work_item}\n"
            "import XCTest\n\n"
            "final class FeatureTests: XCTestCase {\n"
            f"{body}}}\n"
        )
    return f"# TODO: write {framework} tests for: {work_item}\n"


def _verify_command_for(framework: str, file_path: str) -> str:
    return {
        "pytest": f"pytest {file_path} -v",
        "Schemathesis": f"pytest {file_path} -v",
        "Vitest": f"npx vitest run {file_path}",
        "Jest": f"npx jest {file_path}",
        "Playwright": f"npx playwright test {file_path}",
        "k6": f"k6 run {file_path}",
        "Promptfoo": f"npx promptfoo eval -c {file_path}",
        "axe-core via Playwright": f"npx playwright test {file_path}",
        "Semgrep + ZAP baseline": "semgrep --config p/owasp-top-ten src/ && zap-baseline.py -t <staging-url>",
        "Appium": f"npx ts-node {file_path}",
        "JUnit 5": "./gradlew test",
        "XCTest": "xcodebuild test -scheme <Scheme> -destination '<Destination>'",
    }.get(framework, f"# TODO: command to run {file_path}")


def _order_by_level(tasks: list[dict[str, Any]]) -> list[str]:
    """Unit first, then integration, then contract, then functional, then nonfunctional."""
    rank = {"unit": 0, "integration": 1, "contract": 2, "functional": 3, "nonfunctional": 4}
    return [
        task["id"]
        for task in sorted(tasks, key=lambda t: (rank.get(t["level"], 99), t["id"]))
    ]


def _slug(text: str) -> str:
    cleaned = "".join(c.lower() if c.isalnum() else "_" for c in text)
    cleaned = "_".join(filter(None, cleaned.split("_")))
    return cleaned[:60].rstrip("_") or "case"


def _suite_name(work_item: str) -> str:
    return work_item[:80] if work_item else "feature"
