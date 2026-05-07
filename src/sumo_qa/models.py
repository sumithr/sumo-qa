from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


Severity = Literal["low", "medium", "high"]
ConfidenceLevel = Literal["low", "medium", "high"]


class RiskItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: str
    description: str
    severity: Severity = "medium"
    source: str = "heuristic"


class SuggestedTests(BaseModel):
    model_config = ConfigDict(extra="forbid")

    unit: list[str] = Field(default_factory=list)
    integration: list[str] = Field(default_factory=list)
    contract: list[str] = Field(default_factory=list)
    functional: list[str] = Field(default_factory=list)
    nonfunctional: list[str] = Field(default_factory=list)

    def flatten(self) -> list[str]:
        tests: list[str] = []
        for level in ["unit", "integration", "contract", "functional", "nonfunctional"]:
            tests.extend(getattr(self, level))
        return tests


class Confidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    level: ConfidenceLevel
    reason: str


class PresentationHint(BaseModel):
    """How the host model should render this structured output for the user.

    Hosts (Claude Code, IntelliJ AI Assistant, Cursor, etc.) tend to expand
    every JSON field into prose sections, producing long, expensive walls of
    text. This hint asks the host model to render the response sleekly: lead
    with the punchline, bullet the essentials, stop. The structured fields
    remain available for users who drill in.
    """

    model_config = ConfigDict(extra="forbid")

    style: Literal["concise"] = "concise"
    max_words: int = 150
    render_instructions: str


class QAResponseBase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    headline: str
    summary: str
    assumptions: list[str] = Field(default_factory=list)
    top_risks: list[RiskItem] = Field(default_factory=list)
    suggested_tests: SuggestedTests = Field(default_factory=SuggestedTests)
    avoid_testing: list[str] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list)
    confidence: Confidence
    presentation: PresentationHint
    # ISTQB Foundation + Advanced (TA / TTA) test design techniques most relevant
    # to the change shape (e.g. boundary value analysis, decision tables, state
    # transition testing). Sourced from the change-rules engine.
    test_design_techniques: list[str] = Field(default_factory=list)
    # ISO/IEC 25010 quality characteristics most affected by this change
    # (functional_correctness, reliability_recoverability, etc.).
    quality_characteristics: list[str] = Field(default_factory=list)
    # Extra testing capabilities the change is likely to need (e.g. browser
    # E2E, contract testing, load testing, security scanning, mobile, AI/LLM
    # eval, accessibility). Each entry names the approach, well-known tools,
    # and an MCP-server hint so the user can plug in the right capability.
    specialty_testing_needs: list[dict[str, Any]] = Field(default_factory=list)
    # Which QA approach fits this change shape (tdd-scaffold, regression-first,
    # coverage-first-then-refactor, verify-existing, no-tests-recommended,
    # spike-first-then-tests). Includes rationale, the next tool to call (if
    # any), follow-up guidance, alternatives, and a confidence band.
    recommended_approach: dict[str, Any] = Field(default_factory=dict)


class PrepareForWorkResponse(QAResponseBase):
    tool: Literal["qa_prepare_for_work"] = "qa_prepare_for_work"
    work_item: str
    target_paths: list[str] = Field(default_factory=list)
    standards: dict[str, Any]
    knowledge_context: dict[str, Any]
    entry_questions: list[str]
    done_when: list[str]
    qa_risk_areas: list[dict[str, str]]
    test_strategy: dict[str, list[str]]
    llm_analysis: dict[str, Any]


class ReviewLocalChangeResponse(QAResponseBase):
    tool: Literal["qa_review_local_change"] = "qa_review_local_change"
    change_summary: str
    standards: dict[str, Any]
    knowledge_context: dict[str, Any]
    change_classification: dict[str, Any]
    applied_rules: dict[str, Any]
    local_diff: dict[str, Any]
    qa_findings: list[dict[str, str]]
    coverage_questions: list[str]
    recommended_tests: list[str]
    verdict: str
    llm_analysis: dict[str, Any]


class TestingQuestionResponse(QAResponseBase):
    tool: Literal["qa_answer_testing_question"] = "qa_answer_testing_question"
    question: str
    answer: dict[str, Any]
    standards: dict[str, Any]
    knowledge_context: dict[str, Any]
    llm_analysis: dict[str, Any]


class TestPlanPhase(BaseModel):
    """One phase of a test plan (ISTQB Foundation: analysis, design, implementation, execution, completion)."""

    model_config = ConfigDict(extra="forbid")

    name: str
    purpose: str
    deliverables: list[str] = Field(default_factory=list)
    activities: list[str] = Field(default_factory=list)


class TestPlan(BaseModel):
    """ISTQB-Test-Manager-style test plan structure (subset of ISO/IEC/IEEE 29119-3)."""

    model_config = ConfigDict(extra="forbid")

    scope_in: list[str] = Field(default_factory=list)
    scope_out: list[str] = Field(default_factory=list)
    test_basis: list[str] = Field(default_factory=list)
    approach: list[str] = Field(default_factory=list)
    entry_criteria: list[str] = Field(default_factory=list)
    exit_criteria: list[str] = Field(default_factory=list)
    phases: list[TestPlanPhase] = Field(default_factory=list)
    residual_risks: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)


class CreateTestPlanResponse(QAResponseBase):
    tool: Literal["qa_create_test_plan"] = "qa_create_test_plan"
    work_item: str
    scope_size: Literal["small", "medium", "large"]
    test_plan: TestPlan
    standards: dict[str, Any]
    knowledge_context: dict[str, Any]
    change_classification: dict[str, Any]
    applied_rules: dict[str, Any]
    llm_analysis: dict[str, Any]


class ScaffoldTask(BaseModel):
    """A single test-file scaffold task the host model is meant to execute.

    The MCP itself does not write files. Each task carries a file path,
    framework, language, list of named assertions tied to ISTQB techniques,
    an honestly-stubbed code skeleton (assertions raise / TODO so the host
    knows nothing has been verified yet), and a verify command. The host
    iterates through `execution_order` and uses its own file-write tools to
    persist each task.
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    title: str
    file_path: str
    framework: str
    language: str
    level: Literal["unit", "integration", "contract", "functional", "nonfunctional"]
    techniques: list[str] = Field(default_factory=list)
    assertions: list[str] = Field(default_factory=list)
    skeleton: str
    verify_command: str
    after_writing: str
    specialty: str | None = None
    specialty_mcp_hint: str | None = None
    well_known_tools: list[str] = Field(default_factory=list)


class ScaffoldTestsResponse(QAResponseBase):
    tool: Literal["qa_scaffold_tests"] = "qa_scaffold_tests"
    work_item: str
    target_paths: list[str] = Field(default_factory=list)
    tasks: list[ScaffoldTask] = Field(default_factory=list)
    execution_order: list[str] = Field(default_factory=list)
    standards: dict[str, Any]
    change_classification: dict[str, Any]
    applied_rules: dict[str, Any]
    llm_analysis: dict[str, Any]
