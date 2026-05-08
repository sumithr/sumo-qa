from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any

from sumo_qa.classification import ChangeClassificationEngine
from sumo_qa.knowledge import KnowledgeContext, KnowledgeProvider, NullKnowledgeProvider
from sumo_qa.llm import AsyncLLMClient, AsyncMockLLMClient, LLMClient, LLMResponse, MockLLMClient
from sumo_qa.local_diff import LocalDiffInspector, LocalDiffReport
from sumo_qa.models import (
    Confidence,
    CreateTestPlanResponse,
    PrepareForWorkResponse,
    PresentationHint,
    ReviewLocalChangeResponse,
    RiskItem,
    ScaffoldTask,
    ScaffoldTestsResponse,
    SuggestedTests,
    TestingQuestionResponse,
    TestPlan,
    TestPlanPhase,
)
from sumo_qa.approach_decision import choose_approach
from sumo_qa.scaffolder import build_scaffold_tasks
from sumo_qa.prompts import SENIOR_QA_SYSTEM_PROMPT, build_guardrailed_qa_prompt, build_qa_prompt
from sumo_qa.rules import StandardsRulesEngine
from sumo_qa.specialty_routing import detect_specialty_needs
from sumo_qa.standards import StandardsEngine
from sumo_qa.tdm_catalogue import TestDataCatalogue
from sumo_qa.tdm_service import TestDataAssistant
from sumo_qa.tdm_validation import TestDataValidator


DEFAULT_STANDARDS_PATH = Path("standards/packs")
DEFAULT_RULES_PATH = Path("standards/rules/change_rules.yaml")
DEFAULT_TEST_DATA_PATH = Path("knowledge/test_data")


def _resolve_data_path(user_path: str | Path, default: Path, *bundled_parts: str) -> Path:
    """Pick the right path for a data resource.

    Resolution order (only when the caller passed the default sentinel):
      1. cwd-relative default (development from a repo clone)
      2. The bundled copy under sumo_qa/_data/ (installed via wheel)
      3. The default itself (which will surface a clear error downstream)

    When the caller passed an explicit path, it is honoured as-is.
    """
    candidate = Path(user_path)
    if candidate != default:
        return candidate
    if candidate.exists():
        return candidate
    bundled = _bundled_data_path(*bundled_parts)
    if bundled is not None and bundled.exists():
        return bundled
    return candidate


def _bundled_data_path(*parts: str) -> Path | None:
    """Return the on-disk path for a bundled data resource, or None."""
    try:
        import importlib.resources as resources
    except ImportError:  # pragma: no cover - Python <3.9
        return None
    try:
        anchor = resources.files("sumo_qa") / "_data"
    except (ModuleNotFoundError, FileNotFoundError):
        return None
    for part in parts:
        anchor = anchor / part
    try:
        as_path = Path(str(anchor))
    except Exception:  # pragma: no cover - defensive
        return None
    return as_path


class QAShiftLeftService:
    def __init__(
        self,
        standards_engine: StandardsEngine,
        rules_engine: StandardsRulesEngine | None = None,
        knowledge_provider: KnowledgeProvider | None = None,
        llm_client: LLMClient | None = None,
        classifier: ChangeClassificationEngine | None = None,
        diff_inspector: LocalDiffInspector | None = None,
        test_data_assistant: TestDataAssistant | None = None,
        test_data_catalogue: TestDataCatalogue | None = None,
        test_data_validator: TestDataValidator | None = None,
    ) -> None:
        self.standards_engine = standards_engine
        self.rules_engine = rules_engine or StandardsRulesEngine({})
        self.knowledge_provider = knowledge_provider or NullKnowledgeProvider()
        self.llm_client = llm_client or MockLLMClient()
        self.classifier = classifier or ChangeClassificationEngine()
        self.diff_inspector = diff_inspector or LocalDiffInspector(Path.cwd())
        self.test_data_assistant = test_data_assistant or TestDataAssistant(
            test_data_catalogue or TestDataCatalogue(DEFAULT_TEST_DATA_PATH),
            test_data_validator,
        )

    @classmethod
    def from_standards_path(
        cls,
        path: str | Path = DEFAULT_STANDARDS_PATH,
        rules_path: str | Path = DEFAULT_RULES_PATH,
        test_data_path: str | Path = DEFAULT_TEST_DATA_PATH,
    ) -> "QAShiftLeftService":
        standards_path = _resolve_data_path(path, DEFAULT_STANDARDS_PATH, "standards", "packs")
        resolved_standards_path = standards_path.resolve()
        repo_root = (
            resolved_standards_path.parents[1]
            if resolved_standards_path.name == "packs"
            else Path.cwd()
        )
        resolved_rules_path = _resolve_data_path(
            rules_path, DEFAULT_RULES_PATH, "standards", "rules", "change_rules.yaml"
        )
        resolved_test_data_path = _resolve_data_path(
            test_data_path, DEFAULT_TEST_DATA_PATH, "knowledge", "test_data"
        )
        return cls(
            standards_engine=StandardsEngine.from_directory(standards_path),
            rules_engine=StandardsRulesEngine.from_file(resolved_rules_path),
            diff_inspector=LocalDiffInspector(repo_root),
            test_data_catalogue=TestDataCatalogue(resolved_test_data_path),
        )

    def qa_explain_test_data_requirements(
        self,
        question: str,
        environment: str | None = None,
        domain: str | None = None,
    ) -> dict[str, Any]:
        return self.test_data_assistant.explain_requirements(question, environment, domain)

    def qa_find_test_data(
        self,
        environment: str | None = None,
        domain: str | None = None,
        scenario_tags: list[str] | None = None,
        known_valid_for: list[str] | None = None,
        product_id: str | None = None,
        sku: str | None = None,
        limit: int = 5,
        offset: int = 0,
    ) -> dict[str, Any]:
        return self.test_data_assistant.find_test_data(
            environment=environment,
            domain=domain,
            scenario_tags=scenario_tags,
            known_valid_for=known_valid_for,
            product_id=product_id,
            sku=sku,
            limit=limit,
            offset=offset,
        )

    def qa_validate_test_data(
        self,
        entry_id: str | None = None,
        entry: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self.test_data_assistant.validate_test_data(entry_id, entry)

    def qa_register_known_good_test_data(self, entry: dict[str, Any]) -> dict[str, Any]:
        return self.test_data_assistant.register_known_good_test_data(entry)

    def qa_prepare_for_work(
        self,
        work_item: str,
        acceptance_criteria: list[str] | None = None,
        risk_notes: list[str] | None = None,
        explicit_classifications: list[str] | None = None,
        target_paths: list[str] | None = None,
    ) -> dict[str, Any]:
        criteria = acceptance_criteria or []
        provided_risks = risk_notes or []
        targets = target_paths or []
        standards = self.standards_engine.evaluate("prepare")
        classification = self.classifier.classify(
            work_item,
            [],
            " ".join([*criteria, *provided_risks]),
            explicit_classifications=explicit_classifications,
        )
        rules = self.rules_engine.evaluate(classification.names())
        knowledge = self.knowledge_provider.fetch_context(work_item, scope="prepare", domain_ids=_domain_ids(work_item))
        top_risks = _risks_from_prepare(work_item, criteria, provided_risks, rules)
        suggested_tests = _suggest_tests("prepare", criteria, rules, classification.names())
        missing_information = _prepare_missing_information(criteria, provided_risks)
        thin_input = _is_thin_prepare_input(work_item, criteria, provided_risks)
        if thin_input:
            missing_information = ["concrete work item description", *missing_information]
        assumptions = _common_assumptions(knowledge, context_supplied=bool(criteria or provided_risks))
        confidence = _confidence(
            missing_information=missing_information,
            has_classification=_has_strong_classification(classification),
            has_evidence=bool(criteria),
            knowledge=knowledge,
        )
        llm = self.llm_client.complete(
            system_prompt=SENIOR_QA_SYSTEM_PROMPT,
            user_prompt=build_qa_prompt(
                goal="Prepare QA thinking before implementation starts.",
                facts=[work_item, *criteria, *provided_risks],
                standards=standards.prompts,
                rules=rules["must_consider"],
            ),
        )

        response = PrepareForWorkResponse(
            headline=_prepare_headline(work_item, top_risks, missing_information, thin_input),
            summary=_prepare_summary(work_item, top_risks, suggested_tests),
            presentation=_PREPARE_PRESENTATION,
            test_design_techniques=list(rules.get("test_design_techniques", [])),
            quality_characteristics=list(rules.get("quality_characteristics", [])),
            specialty_testing_needs=detect_specialty_needs(
                classifications=classification.names(),
                touched_files=[],
                free_text=" ".join([work_item, *criteria, *provided_risks]),
            ),
            recommended_approach=choose_approach(
                intent_text=" ".join([work_item, *criteria, *provided_risks]),
                classifications=classification.names(),
                target_paths=[],
                signals={"has_acceptance_criteria": bool(criteria)},
            ),
            assumptions=assumptions,
            top_risks=top_risks,
            suggested_tests=suggested_tests,
            avoid_testing=_avoid_testing("prepare", rules, missing_information),
            missing_information=missing_information,
            confidence=confidence,
            work_item=work_item,
            standards=_evaluation_to_dict(standards),
            knowledge_context=asdict(knowledge),
            entry_questions=_entry_questions(criteria, top_risks, rules),
            done_when=[
                "Acceptance criteria have direct verification evidence.",
                "High-risk paths have automated or documented manual coverage.",
                "Known assumptions are either resolved or explicitly accepted.",
            ],
            qa_risk_areas=[{"category": risk.category, "reason": risk.description} for risk in top_risks],
            test_strategy={
                "primary_checks": _primary_checks(criteria),
                "regression_focus": _regression_focus(work_item, top_risks, rules),
                "test_data_needs": _test_data_needs(work_item, criteria),
            },
            llm_analysis=asdict(llm),
            target_paths=targets,
        )
        return response.model_dump(mode="json")

    def qa_review_local_change(
        self,
        change_summary: str,
        diff: str | None = None,
        touched_files: list[str] | None = None,
        test_evidence: list[str] | None = None,
        explicit_classifications: list[str] | None = None,
    ) -> dict[str, Any]:
        evidence = test_evidence or []
        effective_diff, initial_report = self.diff_inspector.inspect(diff, touched_files, [], evidence)
        classification = self.classifier.classify(
            change_summary,
            initial_report.touched_files,
            effective_diff,
            explicit_classifications=explicit_classifications,
        )
        rules = self.rules_engine.evaluate(classification.names())
        effective_diff, local_report = self.diff_inspector.inspect(
            diff,
            touched_files or initial_report.touched_files,
            rules["suggested_test_types"],
            evidence,
        )
        standards = self.standards_engine.evaluate("review")
        knowledge = self.knowledge_provider.fetch_context(change_summary, scope="review", domain_ids=_domain_ids(change_summary))
        findings = _review_findings(change_summary, classification.names(), rules, local_report, evidence)
        top_risks = _risks_from_review(classification.names(), rules, findings, local_report)
        suggested_tests = _suggest_tests("review", [], rules, classification.names(), local_report)
        missing_information = _review_missing_information(local_report, evidence, classification.names())
        thin_input = _is_thin_review_input(
            change_summary=change_summary,
            touched_files=local_report.touched_files,
            test_evidence=evidence,
            diff_available=local_report.diff_available,
        )
        if thin_input:
            missing_information = [
                "touched files or diff",
                "what changed in concrete terms",
                *missing_information,
            ]
        assumptions = _common_assumptions(knowledge, context_supplied=bool(effective_diff or local_report.touched_files))
        confidence = _confidence(
            missing_information=missing_information,
            has_classification=_has_strong_classification(classification),
            has_evidence=bool(evidence or local_report.nearby_tests),
            knowledge=knowledge,
        )
        llm = self.llm_client.complete(
            system_prompt=SENIOR_QA_SYSTEM_PROMPT,
            user_prompt=build_qa_prompt(
                goal="Review a local change for QA risk and missing evidence.",
                facts=[change_summary, *local_report.touched_files, *evidence],
                standards=standards.prompts,
                rules=rules["must_consider"],
            ),
        )

        response = ReviewLocalChangeResponse(
            headline=_review_headline(
                change_summary, classification.names(), top_risks, local_report, evidence, thin_input
            ),
            summary=_review_summary(change_summary, classification.names(), top_risks, local_report),
            presentation=_REVIEW_PRESENTATION,
            test_design_techniques=list(rules.get("test_design_techniques", [])),
            quality_characteristics=list(rules.get("quality_characteristics", [])),
            specialty_testing_needs=detect_specialty_needs(
                classifications=classification.names(),
                touched_files=local_report.touched_files,
                free_text=change_summary,
            ),
            recommended_approach=choose_approach(
                intent_text=change_summary,
                classifications=classification.names(),
                target_paths=local_report.touched_files,
            ),
            assumptions=assumptions,
            top_risks=top_risks,
            suggested_tests=suggested_tests,
            avoid_testing=_avoid_testing("review", rules, missing_information),
            missing_information=missing_information,
            confidence=confidence,
            change_summary=change_summary,
            standards=_evaluation_to_dict(standards),
            knowledge_context=asdict(knowledge),
            change_classification=classification.to_dict(),
            applied_rules=rules,
            local_diff=local_report.to_dict(),
            qa_findings=findings,
            coverage_questions=_coverage_questions(local_report, evidence, rules),
            recommended_tests=suggested_tests.flatten(),
            verdict=_review_verdict(findings, confidence),
            llm_analysis=asdict(llm),
        )
        return response.model_dump(mode="json")

    def qa_answer_testing_question(
        self,
        question: str,
        context: str | None = None,
        explicit_classifications: list[str] | None = None,
    ) -> dict[str, Any]:
        standards = self.standards_engine.evaluate("question")
        classification = self.classifier.classify(
            question,
            [],
            context or "",
            explicit_classifications=explicit_classifications,
        )
        rules = self.rules_engine.evaluate(classification.names())
        knowledge = self.knowledge_provider.fetch_context(question, scope="question", domain_ids=_domain_ids(question))
        answer = _testing_answer(question, context, classification.names(), rules)
        top_risks = _risks_from_question(answer, rules)
        suggested_tests = _suggest_tests("question", answer["verify"], rules, classification.names())
        missing_information = _question_missing_information(context, classification.names())
        assumptions = _common_assumptions(knowledge, context_supplied=bool(context))
        confidence = _confidence(
            missing_information=missing_information,
            has_classification=_has_strong_classification(classification),
            has_evidence=bool(context),
            knowledge=knowledge,
        )
        llm = self.llm_client.complete(
            system_prompt=SENIOR_QA_SYSTEM_PROMPT,
            user_prompt=build_qa_prompt(
                goal="Answer a testing question as a senior QA engineer.",
                facts=[question, context or ""],
                standards=standards.prompts,
                rules=rules["must_consider"],
            ),
        )

        response = TestingQuestionResponse(
            headline=_question_headline(question, top_risks, suggested_tests),
            summary=answer["short_answer"],
            presentation=_QUESTION_PRESENTATION,
            test_design_techniques=list(rules.get("test_design_techniques", [])),
            quality_characteristics=list(rules.get("quality_characteristics", [])),
            specialty_testing_needs=detect_specialty_needs(
                classifications=classification.names(),
                touched_files=[],
                free_text=" ".join([question, context or ""]),
            ),
            recommended_approach=choose_approach(
                intent_text=" ".join([question, context or ""]),
                classifications=classification.names(),
                target_paths=[],
            ),
            assumptions=assumptions,
            top_risks=top_risks,
            suggested_tests=suggested_tests,
            avoid_testing=_avoid_testing("question", rules, missing_information),
            missing_information=missing_information,
            confidence=confidence,
            question=question,
            answer=answer,
            standards=_evaluation_to_dict(standards),
            knowledge_context=asdict(knowledge),
            llm_analysis=asdict(llm),
        )
        return response.model_dump(mode="json")

    def qa_create_test_plan(
        self,
        work_item: str,
        scope_size: str = "medium",
        acceptance_criteria: list[str] | None = None,
        risk_notes: list[str] | None = None,
        explicit_classifications: list[str] | None = None,
    ) -> dict[str, Any]:
        criteria = acceptance_criteria or []
        provided_risks = risk_notes or []
        normalised_scope = scope_size if scope_size in {"small", "medium", "large"} else "medium"
        standards = self.standards_engine.evaluate("prepare")
        classification = self.classifier.classify(
            work_item,
            [],
            " ".join([*criteria, *provided_risks]),
            explicit_classifications=explicit_classifications,
        )
        rules = self.rules_engine.evaluate(classification.names())
        knowledge = self.knowledge_provider.fetch_context(
            work_item, scope="prepare", domain_ids=_domain_ids(work_item)
        )
        top_risks = _risks_from_prepare(work_item, criteria, provided_risks, rules)
        suggested_tests = _suggest_tests("prepare", criteria, rules, classification.names())
        missing_information = _prepare_missing_information(criteria, provided_risks)
        thin_input = _is_thin_prepare_input(work_item, criteria, provided_risks)
        if thin_input:
            missing_information = ["concrete work item description", *missing_information]
        assumptions = _common_assumptions(
            knowledge, context_supplied=bool(criteria or provided_risks)
        )
        confidence = _confidence(
            missing_information=missing_information,
            has_classification=_has_strong_classification(classification),
            has_evidence=bool(criteria),
            knowledge=knowledge,
        )
        llm = self.llm_client.complete(
            system_prompt=SENIOR_QA_SYSTEM_PROMPT,
            user_prompt=build_qa_prompt(
                goal="Produce a phased test plan with entry/exit criteria and deliverables.",
                facts=[work_item, *criteria, *provided_risks],
                standards=standards.prompts,
                rules=rules["must_consider"],
            ),
        )

        plan = _build_test_plan(
            work_item=work_item,
            scope_size=normalised_scope,
            criteria=criteria,
            provided_risks=provided_risks,
            rules=rules,
            standards=standards,
            classification_names=classification.names(),
        )
        specialty = detect_specialty_needs(
            classifications=classification.names(),
            touched_files=[],
            free_text=" ".join([work_item, *criteria, *provided_risks]),
        )
        response = CreateTestPlanResponse(
            headline=_test_plan_headline(work_item, normalised_scope, top_risks, missing_information, thin_input),
            summary=_test_plan_summary(work_item, normalised_scope, plan),
            assumptions=assumptions,
            top_risks=top_risks,
            suggested_tests=suggested_tests,
            avoid_testing=_avoid_testing("prepare", rules, missing_information),
            missing_information=missing_information,
            confidence=confidence,
            presentation=_TEST_PLAN_PRESENTATION,
            test_design_techniques=list(rules.get("test_design_techniques", [])),
            quality_characteristics=list(rules.get("quality_characteristics", [])),
            specialty_testing_needs=specialty,
            recommended_approach=choose_approach(
                intent_text=" ".join([work_item, *criteria, *provided_risks]),
                classifications=classification.names(),
                target_paths=[],
                signals={"has_acceptance_criteria": bool(criteria)},
            ),
            work_item=work_item,
            scope_size=normalised_scope,
            test_plan=plan,
            standards=_evaluation_to_dict(standards),
            knowledge_context=asdict(knowledge),
            change_classification=classification.to_dict(),
            applied_rules=rules,
            llm_analysis=asdict(llm),
        )
        return response.model_dump(mode="json")

    async def aqa_create_test_plan(
        self,
        work_item: str,
        scope_size: str = "medium",
        acceptance_criteria: list[str] | None = None,
        risk_notes: list[str] | None = None,
        async_llm: AsyncLLMClient | None = None,
        explicit_classifications: list[str] | None = None,
    ) -> dict[str, Any]:
        payload = self.qa_create_test_plan(
            work_item, scope_size, acceptance_criteria, risk_notes,
            explicit_classifications=explicit_classifications,
        )
        if async_llm is None:
            return payload
        prompt = _build_test_plan_sampling_prompt(work_item, payload)
        await _apply_host_sampling(payload, async_llm, prompt)
        return payload

    def qa_decide_approach(
        self,
        intent_text: str,
        target_paths: list[str] | None = None,
        signals: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Decide which QA approach fits this change shape (deterministic path).

        Sync version uses the keyword decider as a safety net. The async
        version (`aqa_decide_approach`) prefers AI reasoning via MCP sampling
        and falls back to this path when the host doesn't support sampling.
        """
        targets = target_paths or []
        classification = self.classifier.classify(intent_text, targets, "")
        decision = choose_approach(
            intent_text=intent_text,
            classifications=classification.names(),
            target_paths=targets,
            signals=signals or {},
        )
        decision["reasoned_by"] = "deterministic"
        return {
            "tool": "sumo_qa_decide_approach",
            "intent_text": intent_text,
            "target_paths": targets,
            "change_classification": classification.to_dict(),
            "recommended_approach": decision,
            "presentation": _DECIDE_APPROACH_PRESENTATION.model_dump(mode="json"),
        }

    async def aqa_decide_approach(
        self,
        intent_text: str,
        target_paths: list[str] | None = None,
        signals: dict[str, Any] | None = None,
        async_llm: AsyncLLMClient | None = None,
    ) -> dict[str, Any]:
        """Decide which QA approach fits — AI-reasoned via MCP sampling.

        Asks the host's LLM to reason over QA principles + your loaded team
        standards + the change shape, instead of keyword-matching. Falls back
        to the deterministic decider when sampling is unavailable, the host
        errors, or the AI returns malformed output - so this is strictly an
        upgrade, never a regression.
        """
        # Always compute the deterministic decision as a safety net.
        deterministic_payload = self.qa_decide_approach(intent_text, target_paths, signals)

        if async_llm is None:
            return deterministic_payload

        # Build the AI-reasoning prompt grounded in QA principles + the
        # team's loaded rules + classifier signals.
        targets = target_paths or []
        classification = self.classifier.classify(intent_text, targets, "")
        rules = self.rules_engine.evaluate(classification.names())
        standards = self.standards_engine.evaluate("review")
        prompt = _build_decide_approach_sampling_prompt(
            intent_text=intent_text,
            target_paths=targets,
            classifications=classification.names(),
            rules=rules,
            standards_prompts=standards.prompts,
            deterministic_decision=deterministic_payload["recommended_approach"],
        )

        try:
            response = await async_llm.complete(SENIOR_QA_SYSTEM_PROMPT, prompt)
        except Exception as exc:  # noqa: BLE001 - sampling failures degrade gracefully
            err_type = type(exc).__name__
            err_msg = (str(exc).strip() or "(no error message)")[:300]
            hint = ""
            if err_type in {"McpError", "ServerError", "Error"}:
                hint = (
                    " Most common cause in Claude Code: the host has not approved "
                    "MCP sampling for this server. Approve sampling via the host's "
                    "permissions UI, or set the env var QA_DISABLE_HOST_SAMPLING=1 "
                    "to skip sampling and rely on the deterministic decider only."
                )
            payload = dict(deterministic_payload)
            payload["recommended_approach"] = {
                **payload["recommended_approach"],
                "reasoning_note": (
                    f"Host LLM sampling failed ({err_type}: {err_msg}); "
                    f"decision below came from the deterministic decider.{hint}"
                ),
            }
            return payload

        ai_decision = _parse_ai_decision(response.content)
        if ai_decision is None:
            payload = dict(deterministic_payload)
            payload["recommended_approach"] = {
                **payload["recommended_approach"],
                "reasoning_note": (
                    "Host LLM returned a response that could not be parsed as a "
                    "structured decision; falling back to the deterministic decider."
                ),
            }
            return payload

        return {
            **deterministic_payload,
            "recommended_approach": ai_decision,
        }

    def qa_scaffold_tests(
        self,
        work_item: str,
        test_conditions: list[str] | None = None,
        target_paths: list[str] | None = None,
        explicit_classifications: list[str] | None = None,
    ) -> dict[str, Any]:
        conditions = test_conditions or []
        targets = target_paths or []
        standards = self.standards_engine.evaluate("review")
        classification = self.classifier.classify(
            work_item,
            targets,
            "",
            explicit_classifications=explicit_classifications,
        )
        rules = self.rules_engine.evaluate(classification.names())
        knowledge = self.knowledge_provider.fetch_context(
            work_item, scope="review", domain_ids=_domain_ids(work_item)
        )
        specialty = detect_specialty_needs(
            classifications=classification.names(),
            touched_files=targets,
            free_text=" ".join([work_item, *conditions]),
        )
        scaffolded = build_scaffold_tasks(
            work_item=work_item,
            test_conditions=conditions,
            target_paths=targets,
            classifications=classification.names(),
            suggested_test_types=rules.get("suggested_test_types", []),
            test_design_techniques=rules.get("test_design_techniques", []),
            specialty_needs=specialty,
        )
        tasks = [ScaffoldTask(**task) for task in scaffolded["tasks"]]

        thin = _is_thin_scaffold_input(work_item, conditions)
        missing_information: list[str] = []
        if thin:
            if len(" ".join(work_item.split())) < 20:
                missing_information.append("concrete work item description")
            if not conditions:
                missing_information.append("test conditions")
            if not targets:
                missing_information.append("target source paths")

        confidence = _confidence(
            missing_information=missing_information,
            has_classification=_has_strong_classification(classification),
            has_evidence=bool(conditions or targets),
            knowledge=knowledge,
        )

        # Risks for the response are the underlying review-style risks.
        findings: list[dict[str, str]] = []  # not running diff inspection here
        top_risks = _risks_from_review(
            classification.names(),
            rules,
            findings,
            LocalDiffReport(
                diff_source="scaffold",
                diff_available=False,
                touched_files=targets,
            ),
        )

        suggested_tests = _suggest_tests("review", [], rules, classification.names())
        llm = self.llm_client.complete(
            system_prompt=SENIOR_QA_SYSTEM_PROMPT,
            user_prompt=build_qa_prompt(
                goal="Produce honest test-scaffold tasks the host model can write.",
                facts=[work_item, *conditions, *targets],
                standards=standards.prompts,
                rules=rules["must_consider"],
            ),
        )

        response = ScaffoldTestsResponse(
            headline=_scaffold_headline(work_item, tasks, missing_information, thin),
            summary=(
                f"{len(tasks)} scaffold task(s) for: {work_item}. "
                "Host model writes each file using its own file tools, "
                "then runs the verify_command."
            ),
            assumptions=_common_assumptions(knowledge, context_supplied=bool(conditions or targets)),
            top_risks=top_risks,
            suggested_tests=suggested_tests,
            avoid_testing=_avoid_testing("review", rules, missing_information),
            missing_information=missing_information,
            confidence=confidence,
            presentation=_SCAFFOLD_PRESENTATION,
            test_design_techniques=list(rules.get("test_design_techniques", [])),
            quality_characteristics=list(rules.get("quality_characteristics", [])),
            specialty_testing_needs=specialty,
            recommended_approach=choose_approach(
                intent_text=" ".join([work_item, *conditions]),
                classifications=classification.names(),
                target_paths=targets,
                signals={"has_acceptance_criteria": bool(conditions)},
            ),
            work_item=work_item,
            target_paths=targets,
            tasks=tasks,
            execution_order=scaffolded["execution_order"],
            standards=_evaluation_to_dict(standards),
            change_classification=classification.to_dict(),
            applied_rules=rules,
            llm_analysis=asdict(llm),
        )
        return response.model_dump(mode="json")

    async def aqa_scaffold_tests(
        self,
        work_item: str,
        test_conditions: list[str] | None = None,
        target_paths: list[str] | None = None,
        async_llm: AsyncLLMClient | None = None,
        explicit_classifications: list[str] | None = None,
    ) -> dict[str, Any]:
        payload = self.qa_scaffold_tests(
            work_item, test_conditions, target_paths,
            explicit_classifications=explicit_classifications,
        )
        if async_llm is None:
            return payload
        prompt = _build_scaffold_sampling_prompt(work_item, payload)
        await _apply_host_sampling(payload, async_llm, prompt)
        return payload

    async def aqa_review_local_change(
        self,
        change_summary: str,
        diff: str | None = None,
        touched_files: list[str] | None = None,
        test_evidence: list[str] | None = None,
        async_llm: AsyncLLMClient | None = None,
        explicit_classifications: list[str] | None = None,
    ) -> dict[str, Any]:
        payload = self.qa_review_local_change(
            change_summary, diff, touched_files, test_evidence,
            explicit_classifications=explicit_classifications,
        )
        if async_llm is None:
            return payload
        prompt = _build_review_sampling_prompt(change_summary, payload)
        await _apply_host_sampling(payload, async_llm, prompt)
        return payload

    async def aqa_prepare_for_work(
        self,
        work_item: str,
        acceptance_criteria: list[str] | None = None,
        risk_notes: list[str] | None = None,
        async_llm: AsyncLLMClient | None = None,
        explicit_classifications: list[str] | None = None,
        target_paths: list[str] | None = None,
    ) -> dict[str, Any]:
        payload = self.qa_prepare_for_work(
            work_item, acceptance_criteria, risk_notes,
            explicit_classifications=explicit_classifications,
            target_paths=target_paths,
        )
        if async_llm is None:
            return payload
        prompt = _build_prepare_sampling_prompt(
            work_item,
            acceptance_criteria or [],
            risk_notes or [],
            payload,
            target_paths=target_paths,
        )
        await _apply_host_sampling(payload, async_llm, prompt)
        return payload

    async def aqa_answer_testing_question(
        self,
        question: str,
        context: str | None = None,
        async_llm: AsyncLLMClient | None = None,
        explicit_classifications: list[str] | None = None,
    ) -> dict[str, Any]:
        payload = self.qa_answer_testing_question(
            question, context,
            explicit_classifications=explicit_classifications,
        )
        if async_llm is None:
            return payload
        prompt = _build_question_sampling_prompt(question, context, payload)
        await _apply_host_sampling(payload, async_llm, prompt)
        return payload


async def _apply_host_sampling(
    payload: dict[str, Any], async_llm: AsyncLLMClient, user_prompt: str
) -> None:
    """Call the host LLM via sampling and patch payload['llm_analysis'] in place.

    On any failure the payload's existing deterministic llm_analysis is left intact
    (with a fallback_reason in metadata), so the response stays useful even if the
    host doesn't support sampling.
    """
    try:
        llm_response = await async_llm.complete(SENIOR_QA_SYSTEM_PROMPT, user_prompt)
    except Exception as exc:  # noqa: BLE001 - sampling failures must degrade gracefully
        fallback = await AsyncMockLLMClient().complete(SENIOR_QA_SYSTEM_PROMPT, user_prompt)
        payload["llm_analysis"] = {
            "content": fallback.content,
            "model": fallback.model,
            "metadata": {**fallback.metadata, "fallback_reason": str(exc)[:200]},
        }
        return
    payload["llm_analysis"] = {
        "content": llm_response.content,
        "model": llm_response.model,
        "metadata": llm_response.metadata,
    }


def _build_decide_approach_sampling_prompt(
    *,
    intent_text: str,
    target_paths: list[str],
    classifications: list[str],
    rules: dict[str, Any],
    standards_prompts: list[str],
    deterministic_decision: dict[str, Any],
) -> str:
    """Ground the AI decider in QA principles + loaded standards + the change shape.

    The AI is invited to pick from canonical approaches OR invent a new one
    if the situation needs it. Must cite at least one principle in the
    rationale. Must return parseable JSON.
    """
    canonical_approaches = [
        ("strategy-orchestration", "REPO-WIDE / POLICY ask, not a single change — e.g. 'design a test strategy', 'audit our coverage', 'across the test pyramid', 'rollout to other services', 'minimum viable QA setup'. Pick this whenever the user is asking about a strategy spanning multiple areas, layers, or services rather than one piece of work. Next step is loading the sumo-qa-strategising skill, not calling a per-change MCP tool."),
        ("tdd-scaffold", "greenfield-ish change adding behaviour; plan -> scaffold -> red -> implement -> green"),
        ("regression-first", "bug fix on existing code; reproduce as one failing test, then fix, confirm green, run targeted regression"),
        ("coverage-first-then-refactor", "behaviour-preserving refactor; audit existing coverage and add characterization tests BEFORE refactoring"),
        ("strengthen-test-coverage", "strengthen existing tests on UNCHANGED production code; mutation-testing follow-up, raise-coverage tasks; suppress equivalent mutants in tool config"),
        ("verify-existing", "config-only / trivial tweak; run the existing suite + a smoke; no new tests"),
        ("no-tests-recommended", "pure docs / typos / comments; build + lint, no QA test work"),
        ("spike-first-then-tests", "exploratory prototype; defer test discipline until the design settles"),
    ]
    canonical_block = "\n".join(f"  - `{name}`: {desc}" for name, desc in canonical_approaches)

    # ISTQB Foundation 7 principles - the universal grounding the AI cites.
    principles = [
        "1. Testing shows the presence of defects, not their absence.",
        "2. Exhaustive testing is impossible.",
        "3. Early testing saves time and money (shift left).",
        "4. Defects cluster together (concentrate test design where defect history is dense).",
        "5. Pesticide paradox (the same tests stop finding new defects; refresh assertions).",
        "6. Testing is context-dependent.",
        "7. Absence-of-errors fallacy (validate fitness for use, not just verify code-level correctness).",
    ]

    iso25010 = (
        "ISO/IEC 25010 quality characteristics: functional suitability, performance "
        "efficiency, compatibility, usability, reliability, security, maintainability, "
        "portability."
    )

    techniques = (
        "ISTQB test design techniques: equivalence partitioning, boundary value "
        "analysis, decision tables, state transition testing, pairwise / orthogonal "
        "arrays, error guessing, exploratory testing charters, structural coverage "
        "(statement / branch / MC-DC)."
    )

    rules_block = ""
    if rules.get("must_consider"):
        rules_block = (
            "Loaded team rules for this change classification:\n"
            + "\n".join(f"  - {item}" for item in rules.get("must_consider", [])[:6])
        )

    standards_block = ""
    if standards_prompts:
        standards_block = (
            "Loaded team standards (from your standards packs):\n"
            + "\n".join(f"  - {item}" for item in standards_prompts[:6])
        )

    targets_line = (
        "Target paths: " + ", ".join(target_paths[:6])
        if target_paths
        else "Target paths: (none supplied)"
    )

    deterministic_hint = (
        f"Deterministic-fallback suggestion (only if your reasoning agrees): "
        f"{deterministic_decision.get('approach', 'unknown')} "
        f"({deterministic_decision.get('confidence', 'unknown')} confidence). "
        "If your reasoning over the principles + loaded rules disagrees, override it."
    )

    return (
        "You are a senior QA engineer reasoning about which testing approach fits "
        "a piece of work. Your job is to pick the right discipline using QA "
        "principles, the team's loaded standards, and the actual change shape - "
        "NOT keyword matching.\n\n"
        f"User intent (verbatim):\n  {intent_text}\n\n"
        f"{targets_line}\n\n"
        f"Classifications inferred deterministically: "
        f"{', '.join(classifications) if classifications else '(none)'}\n\n"
        "ISTQB Foundation principles (cite at least one in your rationale):\n"
        + "\n".join(f"  {p}" for p in principles) + "\n\n"
        f"{iso25010}\n\n"
        f"{techniques}\n\n"
        + (rules_block + "\n\n" if rules_block else "")
        + (standards_block + "\n\n" if standards_block else "")
        + "Canonical approaches (start from these; describe a new one if none fits):\n"
        f"{canonical_block}\n\n"
        f"{deterministic_hint}\n\n"
        "Reason in this order:\n"
        "  (a) FIRST decide the SHAPE of the ask. Is it a single change "
        "(one bug, one refactor, one feature, one piece of work) or a "
        "REPO-WIDE strategy ask (asking about a strategy spanning multiple "
        "services / layers / pyramid levels / a rollout)? If repo-wide, "
        "return `strategy-orchestration` — do not force a per-change "
        "approach.\n"
        "  (b) For a single change, reason about WHAT is changing (production "
        "code? tests? config? docs?) and the user's stated context (e.g. 'no "
        "production code changes' implies an approach that does NOT touch "
        "production code).\n"
        "  (c) Apply the loaded team rules / standards. Pick or describe the "
        "right approach. Cite at least one principle.\n\n"
        "Domain anchoring (REQUIRED): Every recommendation must name a concrete "
        "artefact from the supplied context — a target_path, a class name, a "
        "tool, a feature, a domain term. Phrases like \"the service\", \"the "
        "system\", \"the codebase\", \"the application\" are forbidden when "
        "target_paths or classifications are supplied. If no domain context is "
        "available, label the entire output as one large assumption.\n\n"
        "Required: list every behavioural claim you cannot verify from the "
        "supplied facts under \"assumptions\". Treat them as challengeable, "
        "not as truth.\n\n"
        "Required: list 2-5 top_risks. Every risk MUST be specific to the "
        "change shape (or to the actual files in target_paths if supplied) — "
        "generic phrases like \"missing test data\" or \"unclear acceptance "
        "criteria\" are not acceptable.\n\n"
        "Required: list the SMALLEST useful set of tests in suggested_tests. "
        "Each test MUST name an ISTQB technique and reference one of the "
        "top_risks. A laundry-list checklist is not acceptable.\n\n"
        "Required: list specialty_needs ONLY when the change genuinely "
        "implies a specialty surface. Empty list `[]` is acceptable for "
        "in-process unit-level work; place justification under assumptions. "
        "When non-empty, each entry's `tool` must fit the specific risk you "
        "are addressing (named example: 'JJWT' for token-TTL boundary tests, "
        "'OWASP ZAP' for DAST scans of HTTP endpoints — these are not "
        "interchangeable).\n\n"
        "Output requirements (STRICT — your entire response must be valid JSON):\n"
        "{\n"
        '  "approach": "<canonical name OR a short kebab-case name you invent>",\n'
        '  "rationale": "<1-3 sentences citing at least one principle by number or name>",\n'
        '  "next_action": {\n'
        '    "tool": "<MCP tool name (e.g. sumo_qa_scaffold_tests) — for per-change approaches, otherwise null>",\n'
        '    "skill": "<sub-skill name (e.g. sumo-qa-strategising) — for strategy-orchestration, otherwise null>"\n'
        '  } | null,\n'
        '  "follow_up": "<1-2 sentences of guidance regardless of which tool fires>",\n'
        '  "techniques": ["<ISTQB techniques most relevant>"],\n'
        '  "specialty_needs": [\n'
        '    {"specialty": "<security|performance|frontend|contract|mobile|a11y|ai|mutation-testing|other>", "tool": "<concrete well-known tool name>"}\n'
        '  ],\n'
        '  "alternatives": [{"approach": "<name>", "when": "<when to pick instead>"}],\n'
        '  "top_risks": [\n'
        '    {\n'
        '      "risk": "<one-line risk specific to this change>",\n'
        '      "why_specific_to_this_change": "<reason this risk is not generic>",\n'
        '      "evidence_path": "<file/class/path that grounds the risk>"\n'
        '    }\n'
        '  ],\n'
        '  "suggested_tests": [\n'
        '    {\n'
        '      "name": "<concrete test name>",\n'
        '      "technique": "<named ISTQB technique>",\n'
        '      "covers_risk": "<one of the risk strings from top_risks>"\n'
        '    }\n'
        '  ],\n'
        '  "assumptions": ["<labelled assumption>", "..."],\n'
        '  "confidence": "low|medium|high",\n'
        '  "reasoned_by": "ai"\n'
        "}\n\n"
        "next_action shape (HARD REQUIREMENT): exactly ONE of `tool` or "
        "`skill` MUST be set; the other MUST be `null` or absent. For "
        "per-change approaches (tdd-scaffold, regression-first, "
        "coverage-first-then-refactor, strengthen-test-coverage, "
        "verify-existing, no-tests-recommended, spike-first-then-tests) use "
        "`tool` and leave `skill` null. For `strategy-orchestration` use "
        "`skill: \"sumo-qa-strategising\"` and leave `tool` null. Never "
        "both. Setting both is an error.\n\n"
        "ADDITIONAL HARD REQUIREMENT when `approach` is "
        "\"strategy-orchestration\": the response MUST also include the "
        "following structured fields. For per-change approaches "
        "(tdd-scaffold, regression-first, etc.) these fields are not "
        "required and can be omitted.\n"
        "{\n"
        '  "pyramid_shape": {\n'
        '    "unit": "<one-line description of unit-test investment for this repo>",\n'
        '    "component_integration": "<one-line description>",\n'
        '    "integration": "<one-line description>",\n'
        '    "contract": "<one-line description>",\n'
        '    "e2e": "<one-line description; e2e should stay thin>"\n'
        "  },\n"
        '  "gate_calibration": {\n'
        '    "pr_gate": "<what runs on every PR + wall-time target>",\n'
        '    "merge_gate": "<what runs on merge + wall-time target>",\n'
        '    "nightly": "<what runs nightly>"\n'
        "  },\n"
        '  "ci_feedback_time": {\n'
        '    "target_pr_feedback": "<wall-time target>",\n'
        '    "target_merge_feedback": "<wall-time target>",\n'
        '    "actions": "<concrete actions to hit the targets>"\n'
        "  },\n"
        '  "rollout_plan": [\n'
        '    "<ordered step 1>",\n'
        '    "<ordered step 2>"\n'
        "  ]\n"
        "}\n\n"
        "Return JSON only, no prose around it."
    )


def _parse_ai_decision(content: str) -> dict[str, Any] | None:
    """Parse the AI's response into a decision dict.

    Returns None if unparseable or missing required fields. The caller falls
    back to the deterministic decider in that case.
    """
    if not content or not content.strip():
        return None
    text = content.strip()
    # Tolerate the AI wrapping JSON in fences.
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        if text.endswith("```"):
            text = text.rsplit("```", 1)[0]
        text = text.strip()
    if text.lower().startswith("json"):
        text = text[4:].lstrip()
    try:
        import json as _json
        parsed = _json.loads(text)
    except (ValueError, TypeError):
        return None
    if not isinstance(parsed, dict):
        return None
    if "approach" not in parsed or not isinstance(parsed["approach"], str):
        return None
    if "rationale" not in parsed or not isinstance(parsed["rationale"], str):
        return None
    # Normalise next_action shape - allow null, dict, or string.
    # Round-6: tool|skill disambiguation. If the AI emits a string, treat it
    # as a tool name when it matches the MCP tool prefix (sumo_qa_*) and as
    # a skill name otherwise. Always normalise dicts to have both keys so
    # downstream consumers can branch cleanly.
    if "next_action" not in parsed:
        parsed["next_action"] = None
    elif isinstance(parsed["next_action"], str):
        raw = parsed["next_action"]
        if raw.startswith("sumo_qa_"):
            parsed["next_action"] = {"tool": raw, "skill": None}
        else:
            parsed["next_action"] = {"tool": None, "skill": raw}
    elif isinstance(parsed["next_action"], dict):
        na = parsed["next_action"]
        na.setdefault("tool", None)
        na.setdefault("skill", None)
    parsed.setdefault("follow_up", "")
    parsed.setdefault("techniques", [])
    parsed.setdefault("specialty_needs", [])
    parsed.setdefault("alternatives", [])
    parsed.setdefault("top_risks", [])
    parsed.setdefault("suggested_tests", [])
    parsed.setdefault("assumptions", [])
    parsed.setdefault("confidence", "medium")
    parsed.setdefault("reasoned_by", "ai")
    return parsed


def _domain_anchoring_and_json_schema(
    *,
    schema_lines: list[str],
    extra_required: str = "",
    has_targets: bool = False,
) -> str:
    """Append the standing per-tool requirements to a narrative prompt.

    Forces:
      - Domain anchoring (concrete artefacts, not "the service" / "the system").
      - JSON output with an `assumptions` field for every behavioural claim
        that isn't directly supported by the supplied facts.

    This is the per-tool enforcement of the rules that round-1 evaluations
    showed are universally ignored when only the system prompt mentions them.
    """
    target_clause = (
        "Phrases like \"the service\", \"the system\", \"the codebase\", "
        "\"the application\" are forbidden when target_paths or "
        "classifications are supplied."
    ) if has_targets else (
        "If no target paths or classifications are supplied, label the entire "
        "output as one large assumption rather than asserting behaviour."
    )
    schema_block = "{\n" + "\n".join(schema_lines) + "\n}"
    return (
        "Domain anchoring (REQUIRED): Every recommendation must name a "
        "concrete artefact from the supplied context — a target_path, a "
        "class name, a tool, a feature, a domain term. " + target_clause + "\n\n"
        + (extra_required + "\n\n" if extra_required else "")
        + "Output requirements (STRICT — your entire response must be valid JSON):\n"
        + schema_block + "\n\n"
        "Required: list every behavioural claim you cannot verify from the "
        "supplied facts under \"assumptions\". Treat them as challengeable, "
        "not as truth. If you are inferring no behaviour beyond the supplied "
        "facts, return assumptions: []. A response with confident claims and "
        "no assumptions field is not acceptable.\n\n"
        "Return JSON only, no prose around it."
    )


def _build_review_sampling_prompt(change_summary: str, payload: dict[str, Any]) -> str:
    classification = payload.get("change_classification", {})
    primary = classification.get("primary") or "unclassified"
    primary_confidence = classification.get("primary_confidence", "low")
    classification_summary = f"{primary} ({primary_confidence} confidence)"
    local_diff = payload.get("local_diff", {})
    touched = local_diff.get("touched_files") or []
    missing_levels = local_diff.get("missing_test_levels") or []
    findings = [f.get("finding", "") for f in payload.get("qa_findings", []) if f.get("finding")]
    recommended_paths = sorted(
        {
            f["recommended_test_path"]
            for f in payload.get("qa_findings", [])
            if f.get("recommended_test_path")
        }
    )
    standards = [
        check["title"] for check in payload.get("standards", {}).get("checks", []) if check.get("title")
    ]
    rules = payload.get("applied_rules", {}).get("must_consider", [])
    facts: list[str] = [f"Change summary: {change_summary}"]
    if touched:
        facts.append(f"Touched files ({len(touched)}): {', '.join(touched[:6])}")
    base = build_guardrailed_qa_prompt(
        goal="Review a local change for QA risk and missing evidence.",
        facts=facts,
        classification_summary=classification_summary,
        missing_test_levels=missing_levels,
        recommended_test_paths=recommended_paths,
        findings=findings,
        standards=standards,
        rules=rules,
    )
    return base + "\n\n" + _domain_anchoring_and_json_schema(
        schema_lines=[
            '  "narrative": "<3-6 sentences of senior-QA judgement on this specific change>",',
            '  "principle_cited": "<ISTQB Foundation principle by name or number that shapes this review>",',
            '  "named_techniques": [',
            '    {"technique": "<named ISTQB test design technique>", "covers_risk": "<one of top_risks>"}',
            '  ],',
            '  "top_risks": [',
            '    {"risk": "<change-specific risk, not boilerplate>", "why_specific_to_this_change": "<reason>", "evidence_path": "<file/class/path>"}',
            '  ],',
            '  "smallest_useful_tests": [',
            '    {"name": "<concrete test>", "technique": "<ISTQB technique>", "covers_risk": "<one of top_risks>"}',
            '  ],',
            '  "specialty_needs": [',
            '    {"specialty": "<security|performance|frontend|contract|mobile|a11y|ai|mutation-testing|other>", "tool": "<concrete well-known tool name>"}',
            '  ],',
            '  "assumptions": ["<labelled assumption>", "..."]',
        ],
        extra_required=(
            "HARD REQUIREMENT — principle + minimum-set: `principle_cited` "
            "MUST be a non-empty ISTQB Foundation principle (by name or "
            "number) that shapes this review. `named_techniques` MUST tie "
            "each entry to one of the top_risks via `covers_risk`. "
            "`top_risks` MUST list 2-5 items specific to this change — "
            "generic phrases like \"missing test data\" or \"unclear "
            "acceptance criteria\" are not acceptable. "
            "`smallest_useful_tests` MUST be the smallest set that gives "
            "release confidence (3-7 items for a multi-risk review, fewer "
            "if the change is narrow); a laundry-list checklist is not "
            "acceptable.\n\n"
            "Required: list specialty_needs ONLY when the change genuinely "
            "implies a specialty surface. Empty list `[]` is acceptable for "
            "in-process unit-level work; place justification under assumptions. "
            "When non-empty, each entry's `tool` must fit the specific risk "
            "you are addressing (named example: 'JJWT' for token-TTL boundary "
            "tests, 'OWASP ZAP' for DAST scans of HTTP endpoints — these are "
            "not interchangeable)."
        ),
        has_targets=bool(touched),
    )


_CRITICAL_PATH_TOKENS = (
    "auth",
    "authn",
    "authz",
    "payment",
    "billing",
    "encryption",
    "rate-limit",
    "rate limit",
    "session",
    "token",
    "oauth",
    "jwt",
    "csrf",
    "xss",
    "sql injection",
)


def _critical_path_token_matches(*haystacks: str) -> list[str]:
    """Return critical-path tokens that appear (case-insensitive substring)
    in any of the supplied free-text haystacks. Structural detection only —
    the AI still does all the QA reasoning."""
    blob = " ".join(h or "" for h in haystacks).lower()
    return [token for token in _CRITICAL_PATH_TOKENS if token in blob]


def _build_prepare_sampling_prompt(
    work_item: str,
    criteria: list[str],
    risk_notes: list[str],
    payload: dict[str, Any],
    target_paths: list[str] | None = None,
) -> str:
    classification = payload.get("change_classification", {})
    primary = classification.get("primary") or "unclassified"
    primary_confidence = classification.get("primary_confidence", "low")
    classification_summary = f"{primary} ({primary_confidence} confidence)"
    standards = [
        check["title"] for check in payload.get("standards", {}).get("checks", []) if check.get("title")
    ]
    rules = payload.get("applied_rules", {}).get("must_consider", [])
    targets = target_paths or []
    facts = [f"Work item: {work_item}"]
    if targets:
        facts.append("Target paths: " + ", ".join(targets[:6]))
    if criteria:
        facts.append("Acceptance criteria:")
        facts.extend(f"  - {item}" for item in criteria)
    if risk_notes:
        facts.append("Pre-flagged risks:")
        facts.extend(f"  - {item}" for item in risk_notes)
    base = build_guardrailed_qa_prompt(
        goal="Plan QA before implementation starts.",
        facts=facts,
        classification_summary=classification_summary,
        missing_test_levels=[],
        recommended_test_paths=list(targets),
        findings=payload.get("missing_information", []),
        standards=standards,
        rules=rules,
    )
    matched_tokens = _critical_path_token_matches(
        " ".join(risk_notes or []),
        " ".join(criteria or []),
        work_item,
    )
    critical_uplift = ""
    if matched_tokens:
        critical_uplift = (
            "\n\nCRITICAL-PATH UPLIFT (auto-detected: "
            + ", ".join(matched_tokens)
            + "):\n"
            "  This change is on a critical path. ISTQB Foundation Principle 4\n"
            "  (defects cluster) demands tighter coverage:\n"
            "  - At least one boundary value test PER acceptance criterion rule.\n"
            "  - At least one negative-path / abuse-case test per acceptance\n"
            "    criterion (replay, expired, tampered, malformed, race-condition).\n"
            "  - Specialty pairing REQUIRED: name the security tool you'd use\n"
            "    (OWASP ZAP / Burp Suite / Semgrep / OWASP ASVS).\n"
            "  - When the supplied repo does not contain the relevant boundary\n"
            "    (e.g. work_item mentions auth but no auth module exists in\n"
            "    target_paths), surface this as a missing_information item, not\n"
            "    a fabrication."
        )
    return base + critical_uplift + "\n\n" + _domain_anchoring_and_json_schema(
        schema_lines=[
            '  "narrative": "<3-6 sentences of senior-QA judgement on this specific work item>",',
            '  "checks": ["<concrete check anchored to the work item, criterion, or domain term>"],',
            '  "specialty_needs": [',
            '    {"specialty": "<security|performance|frontend|contract|mobile|a11y|ai|mutation-testing|other>", "tool": "<concrete well-known tool name>"}',
            '  ],',
            '  "assumptions": ["<labelled assumption>", "..."]',
        ],
        extra_required=(
            "Required: list specialty_needs ONLY when the change genuinely "
            "implies a specialty surface. Empty list `[]` is acceptable for "
            "in-process unit-level work; place justification under assumptions. "
            "When non-empty, each entry's `tool` must fit the specific risk "
            "you are addressing (named example: 'JJWT' for token-TTL boundary "
            "tests, 'OWASP ZAP' for DAST scans of HTTP endpoints — these are "
            "not interchangeable)."
        ),
        has_targets=bool(criteria or risk_notes or targets),
    )


def _build_question_sampling_prompt(
    question: str,
    context: str | None,
    payload: dict[str, Any],
) -> str:
    classification = payload.get("change_classification", {})
    primary = classification.get("primary") or "unclassified"
    primary_confidence = classification.get("primary_confidence", "low")
    classification_summary = f"{primary} ({primary_confidence} confidence)"
    standards = [
        check["title"] for check in payload.get("standards", {}).get("checks", []) if check.get("title")
    ]
    answer_verify = payload.get("answer", {}).get("verify", [])
    facts = [f"Question: {question}"]
    if context:
        facts.append(f"Context: {context}")
    base = build_guardrailed_qa_prompt(
        goal="Answer a senior-QA testing question.",
        facts=facts,
        classification_summary=classification_summary,
        missing_test_levels=[],
        recommended_test_paths=[],
        findings=answer_verify,
        standards=standards,
        rules=payload.get("answer", {}).get("risk_areas", []),
    )
    return base + "\n\n" + _domain_anchoring_and_json_schema(
        schema_lines=[
            '  "short_answer": "<one-line senior-QA answer specific to this question>",',
            '  "smallest_useful_tests": [',
            '    {"name": "<concrete test>", "technique": "<ISTQB technique>", "covers_risk": "<one of top_risks>"}',
            '  ],',
            '  "top_risks": [',
            '    {"risk": "<change-specific risk, not boilerplate>", "why_specific_to_this_change": "<reason>", "evidence_path": "<file/class/path>"}',
            '  ],',
            '  "assumptions": ["<labelled assumption>", "..."],',
            '  "recommended_approach": {',
            '    "approach": "<one of: tdd-scaffold | regression-first | coverage-first-then-refactor | strengthen-test-coverage | verify-existing | no-tests-recommended | spike-first-then-tests | strategy-orchestration>",',
            '    "confidence": "<low | medium | high>",',
            '    "next_action": {',
            '      "tool": "<MCP tool name (e.g. sumo_qa_scaffold_tests) — for per-change approaches, otherwise null>",',
            '      "skill": "<sub-skill name (e.g. sumo-qa-strategising) — for strategy-orchestration, otherwise null>"',
            '    }',
            '  },',
            '  "principle_cited": "<ISTQB Foundation principle by name or number that shapes this answer>",',
            '  "named_techniques": [',
            '    {"technique": "<technique>", "covers_risk": "<one of top_risks>"}',
            '  ],',
            '  "specialty_needs": [',
            '    {"specialty": "<security|performance|frontend|contract|mobile|a11y|ai|mutation-testing|other>", "tool": "<concrete well-known tool name>"}',
            '  ]',
        ],
        extra_required=(
            "Routing rule: if the question is open-ended against a whole "
            "service or a strategy / audit / pyramid / rollout ask, set "
            "`recommended_approach.approach` to `strategy-orchestration` and "
            "`recommended_approach.next_action.skill` to "
            "`\"sumo-qa-strategising\"` (leave `tool` null). Cap "
            "`smallest_useful_tests` at 5 items — this is the minimum useful "
            "set, not a checklist.\n\n"
            "next_action shape (HARD REQUIREMENT): exactly ONE of "
            "`recommended_approach.next_action.tool` or "
            "`recommended_approach.next_action.skill` MUST be set; the other "
            "MUST be `null`. For per-change approaches use `tool` (e.g. "
            "`sumo_qa_scaffold_tests`); for `strategy-orchestration` use "
            "`skill: \"sumo-qa-strategising\"`. Never both. Setting both is "
            "an error.\n\n"
            "HARD REQUIREMENT — principle + minimum-set: `principle_cited` "
            "MUST be non-empty when the answer touches risk, prioritisation, "
            "or strategy. `smallest_useful_tests` MUST be the smallest set "
            "that gives release confidence (typically 3-5 items), not an "
            "exhaustive checklist.\n\n"
            "Required: list specialty_needs ONLY when the question genuinely "
            "implies a specialty surface. Empty list `[]` is acceptable for "
            "in-process unit-level work. When non-empty, each entry's `tool` "
            "must fit the specific risk you are addressing (named example: "
            "'JJWT' for token-TTL boundary tests, 'OWASP ZAP' for DAST scans "
            "of HTTP endpoints — these are not interchangeable)."
        ),
        has_targets=bool(context),
    )


_PREPARE_PRESENTATION = PresentationHint(
    style="concise",
    max_words=160,
    render_instructions=(
        "Render this response in roughly 160 words (soft target - aim for it, "
        "but you may exceed if absolutely needed to stay honest about real risk; "
        "still be as concise as possible). Do not write expanded sections, prose "
        "essays, tables, or project-specific code analysis on top of the "
        "structured fields. The JSON IS the answer. "
        "Format: "
        "(0) lead with one APPROACH line: 'APPROACH: <recommended_approach.approach> "
        "(<confidence>) -> next: <recommended_approach.next_action.tool>' "
        "so the user knows what comes next; "
        "(1) the `headline` field as the opening line; "
        "(2) up to 3 `top_risks` as bullets formatted '[severity] category - description' "
        "(short descriptions, ~15 words each); "
        "(3) up to 5 highest-priority items from `suggested_tests` flattened, as bullets; "
        "(4) up to 2 `test_design_techniques` as a single 'Apply:' line "
        "(named ISTQB techniques like boundary value analysis, decision table); "
        "(5) up to 2 `specialty_testing_needs` as a 'Pull in:' block "
        "(approach + 2-3 well-known tools, e.g. 'Browser-driven E2E (Playwright, Cypress)'); "
        "(6) up to 2 `missing_information` items as a single 'Need:' line. "
        "Omit `assumptions`, `done_when`, `entry_questions`, `qa_risk_areas`, "
        "`test_strategy`, `standards`, `applied_rules`, `knowledge_context`, "
        "`quality_characteristics`, and `llm_analysis` from the rendered text - "
        "they remain in the JSON for the user to inspect on demand."
    ),
)


_REVIEW_PRESENTATION = PresentationHint(
    style="concise",
    max_words=160,
    render_instructions=(
        "Render this response in roughly 160 words (soft target - aim for it, "
        "but you may exceed if needed to be honest about real risk; still be "
        "as concise as possible). Do not write expanded sections, prose essays, "
        "or tables on top of the structured fields. The JSON IS the answer. "
        "Format: "
        "(1) the `verdict` as a 1-line tag at the top (e.g. 'VERDICT: needs-test-evidence'); "
        "(2) the `headline` as the next line; "
        "(3) up to 3 `qa_findings` as bullets, each '[severity] finding' with the "
        "`recommended_test_path` inline if present; "
        "(4) up to 3 `top_risks` as bullets if they add information beyond the findings; "
        "(5) up to 2 `test_design_techniques` as a single 'Apply:' line "
        "(named ISTQB techniques); "
        "(6) up to 2 `specialty_testing_needs` as a 'Pull in:' block "
        "(extra MCPs/skills the user should plug in); "
        "(7) up to 2 `missing_information` items. "
        "Omit `change_classification`, `applied_rules`, `local_diff`, "
        "`coverage_questions`, `recommended_tests`, `standards`, `knowledge_context`, "
        "`assumptions`, `quality_characteristics`, and `llm_analysis` from the rendered text."
    ),
)


_DECIDE_APPROACH_PRESENTATION = PresentationHint(
    style="concise",
    max_words=80,
    render_instructions=(
        "Render this decision in <=80 words and stop. Format: "
        "(1) 'APPROACH: <approach> (<confidence>) -> next: <next_action.tool or 'no tool'>'; "
        "(2) one-line `rationale`; "
        "(3) one-line `follow_up`; "
        "(4) up to 2 `alternatives` as bullets. "
        "Do not write essays - this is a decision, not a plan."
    ),
)


_SCAFFOLD_PRESENTATION = PresentationHint(
    style="concise",
    max_words=200,
    render_instructions=(
        "Render this scaffold response in roughly 200 words (soft target - "
        "exceed if absolutely needed; still be as concise as possible). The "
        "JSON IS the answer; do not paste full skeletons into the prose. "
        "Format: "
        "(1) the `headline` as the opening line; "
        "(2) `tasks` as a compact bullet list, one per task: "
        "'[level] T<id> file_path - title (framework, N assertions)'; "
        "(3) `execution_order` as a single line: 'Order: T1 -> T2 -> T3'; "
        "(4) up to 2 `specialty_testing_needs` as a 'Pull in:' block when "
        "specialty tasks are present; "
        "(5) up to 2 `missing_information` items as 'Need:'. "
        "Then prompt the user: 'Write task T<id>? Run with: <verify_command>'. "
        "Do not dump skeleton code into chat - the host model uses its own "
        "file-write tools to persist each skeleton from `tasks[i].skeleton`."
    ),
)


_TEST_PLAN_PRESENTATION = PresentationHint(
    style="concise",
    max_words=220,
    render_instructions=(
        "Render this test plan in roughly 220 words (soft target - exceed if "
        "absolutely needed for honesty; still be as concise as possible). Do "
        "not write expanded prose essays or duplicate the JSON. The JSON IS "
        "the answer. "
        "Format: "
        "(1) the `headline` field as the opening line; "
        "(2) `test_plan.scope_in` as 'In scope:' bullets (max 4); "
        "(3) `test_plan.entry_criteria` as 'Entry:' bullets (max 3); "
        "(4) `test_plan.phases` as a compact phase-by-phase block; "
        "for each phase show only `name`, `purpose` (1 line), and the top 2 "
        "`deliverables`; "
        "(5) `test_plan.exit_criteria` as 'Exit:' bullets (max 4); "
        "(6) up to 2 `specialty_testing_needs` as 'Pull in:' block; "
        "(7) up to 2 `test_plan.open_questions` as 'Open questions:' bullets. "
        "Omit `assumptions`, `applied_rules`, `standards`, `knowledge_context`, "
        "`llm_analysis`, `quality_characteristics`, `test_basis`, "
        "`residual_risks` from the rendered text - they remain in the JSON for "
        "the user to inspect on demand."
    ),
)


_QUESTION_PRESENTATION = PresentationHint(
    style="concise",
    max_words=140,
    render_instructions=(
        "Render this response in roughly 140 words (soft target - you may exceed "
        "if needed to be useful; still be as concise as possible). Do not write "
        "expanded sections, prose essays, or tables. The JSON IS the answer. "
        "Format: "
        "(1) `answer.short_answer` as the opening line; "
        "(2) up to 5 items from `answer.verify` as bullets; "
        "(3) up to 2 `top_risks` as bullets formatted '[severity] description'; "
        "(4) up to 2 `test_design_techniques` as a single 'Apply:' line; "
        "(5) up to 2 `specialty_testing_needs` as a 'Pull in:' block; "
        "(6) up to 2 `missing_information` items if present. "
        "Omit `assumptions`, `standards`, `knowledge_context`, "
        "`quality_characteristics`, and `llm_analysis` from the rendered text."
    ),
)


def _evaluation_to_dict(evaluation: Any) -> dict[str, Any]:
    return {
        "workflow": evaluation.workflow,
        "pack_versions": evaluation.pack_versions,
        "checks": evaluation.checks,
    }


def _domain_ids(text: str) -> list[str]:
    """Domain auto-detection used to phrase-match work_item / question text.
    Removed — phrase tables can't keep up with how language varies. The AI
    is grounded in the team's loaded standards and reads the text directly
    via MCP sampling, so domain detection happens there. Returns an empty
    list; the knowledge provider falls back to its default behaviour.
    """
    return []


def _entry_questions(criteria: list[str], risks: list[RiskItem], rules: dict[str, Any]) -> list[str]:
    questions = [
        "What customer-visible behavior proves this work is correct?",
        "Which existing journey could regress if this changes?",
    ]
    if not criteria:
        questions.append("What are the acceptance criteria and expected outcomes?")
    for item in rules["must_consider"][:4]:
        questions.append(f"How will QA verify {item}?")
    if risks:
        questions.append("Which top risk needs evidence before development is considered complete?")
    return _dedupe(questions)


def _risks_from_prepare(
    work_item: str,
    criteria: list[str],
    risk_notes: list[str],
    rules: dict[str, Any],
) -> list[RiskItem]:
    """Surface risks from the team's loaded rule templates and any caller-
    supplied risk notes. Domain-specific risk surfacing (auth -> security
    boundary risk; payment -> reconciliation risk; etc.) is the AI's job —
    the AI is grounded in ISTQB risk-based testing in the system prompt and
    sees the work_item, criteria, and risk_notes verbatim. The harness no
    longer phrase-matches intent text to inject risks.
    """
    risks: list[RiskItem] = [
        RiskItem(category="rule-expectation", description=template, severity="high", source="standards-rule")
        for template in rules["risk_templates"][:4]
    ]
    for note in risk_notes:
        risks.append(RiskItem(category="provided-risk", description=note, severity="medium", source="user-input"))
    if not risks:
        risks.append(RiskItem(category="unknowns", description="No explicit risk notes supplied; confirm blast radius early.", severity="medium"))
    return _unique_risks(risks)[:5]


def _risks_from_review(
    classifications: list[str],
    rules: dict[str, Any],
    findings: list[dict[str, str]],
    local_report: LocalDiffReport,
) -> list[RiskItem]:
    file_hint = _file_hint(local_report.touched_files)
    templates_by_classification: dict[str, list[str]] = rules.get(
        "templates_by_classification", {}
    )
    risks: list[RiskItem] = []
    seen_descriptions: set[str] = set()
    for classification in classifications:
        per_classification = templates_by_classification.get(classification, [])
        for template in per_classification[:2]:
            description = f"{template}{file_hint}"
            if description in seen_descriptions:
                continue
            seen_descriptions.add(description)
            risks.append(
                RiskItem(
                    category=classification,
                    description=description,
                    severity="high",
                    source="standards-rule",
                )
            )
    for finding in findings:
        risks.append(
            RiskItem(
                category=finding["category"],
                description=finding["finding"],
                severity=finding["severity"],  # type: ignore[arg-type]
                source="local-diff",
            )
        )
    for item in local_report.risky_untested_changes:
        risks.append(RiskItem(category="untested-change", description=item, severity="high", source="local-diff"))
    if not risks:
        risks.append(RiskItem(category="no-obvious-gap", description="No obvious QA risk detected from supplied local change input.", severity="low"))
    return _unique_risks(risks)[:6]


def _risks_from_question(answer: dict[str, Any], rules: dict[str, Any]) -> list[RiskItem]:
    risks = [
        RiskItem(category="question-risk", description=item, severity="medium", source="question-analysis")
        for item in answer["risk_areas"]
    ]
    for template in rules["risk_templates"][:2]:
        risks.append(RiskItem(category="rule-expectation", description=template, severity="high", source="standards-rule"))
    return _unique_risks(risks)[:5]


def _suggest_tests(
    workflow: str,
    criteria_or_checks: list[str],
    rules: dict[str, Any],
    classifications: list[str],
    local_report: LocalDiffReport | None = None,
) -> SuggestedTests:
    tests = SuggestedTests()
    test_types = set(rules["suggested_test_types"])
    if not test_types:
        test_types.add("functional")

    if "business_logic_change" in classifications or "state_transition_change" in classifications:
        test_types.add("unit")
    if "api_contract_change" in classifications or "data_mapping_change" in classifications:
        test_types.add("contract")
    if "async_flow_change" in classifications or "caching_change" in classifications:
        test_types.add("nonfunctional")

    checks = criteria_or_checks or ["changed behavior"]
    for test_type in sorted(test_types):
        if test_type == "unit":
            tests.unit.append("Cover decision boundaries and negative branches closest to the changed logic.")
        elif test_type == "integration":
            tests.integration.append("Verify the changed component with its nearest real dependency or adapter boundary.")
        elif test_type == "contract":
            tests.contract.append("Run contract checks for request, response, validation, and backward-compatible payload examples.")
        elif test_type == "functional":
            tests.functional.append(f"Verify customer-visible outcome for {checks[0]}.")
        elif test_type == "nonfunctional":
            tests.nonfunctional.append("Exercise timeout, retry, stale data, or concurrency behavior relevant to the change.")

    if workflow == "review" and local_report and local_report.nearby_tests:
        tests.unit.append(f"Run nearby tests: {', '.join(local_report.nearby_tests[:4])}.")
    if workflow == "prepare" and criteria_or_checks:
        tests.functional = [f"Verify acceptance criterion: {criterion}" for criterion in criteria_or_checks[:3]] + tests.functional
    return tests


def _primary_checks(criteria: list[str]) -> list[str]:
    if criteria:
        return [f"Verify: {criterion}" for criterion in criteria]
    return ["Define acceptance criteria before estimating QA coverage."]


def _regression_focus(work_item: str, risks: list[RiskItem], rules: dict[str, Any]) -> list[str]:
    """Surface regression focus areas from the loaded team rules + risk
    categories. Domain-specific narrowing (delivery / stock / outlet etc.)
    is the AI's job — the AI is grounded in the team's standards and reads
    the work_item directly via MCP sampling.
    """
    focus = ["changed happy path", "nearest negative path"]
    focus.extend(rules["must_consider"][:4])
    categories = {risk.category for risk in risks}
    if "contract" in categories:
        focus.append("consumer contract compatibility")
    if "fulfilment" in categories:
        focus.append("delivery eligibility and unavailable-option behavior")
    if "stock" in categories:
        focus.append("stock boundary and no-stock behavior")
    return _dedupe(focus)


def _test_data_needs(work_item: str, criteria: list[str]) -> list[str]:
    """Generic test data needs. The AI-sampling path specialises these to
    the actual change (the AI sees `work_item` and `criteria` verbatim and
    is grounded in the standard ISTQB test-data discipline). The harness
    no longer phrase-matches intent text to inject specific data shapes.
    """
    return ["representative valid record", "negative or ineligible record"]


def _review_findings(
    change_summary: str,
    classifications: list[str],
    rules: dict[str, Any],
    local_report: LocalDiffReport,
    test_evidence: list[str],
) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    if not test_evidence and not local_report.nearby_tests:
        findings.append(
            {
                "severity": "high",
                "category": "missing-evidence",
                "finding": "No test evidence or nearby test file was found for the local change.",
            }
        )
    for level in local_report.missing_test_levels:
        recommended_path = _recommended_test_path(level, local_report.touched_files)
        finding: dict[str, str] = {
            "severity": "medium",
            "category": "missing-test-level",
            "finding": (
                f"Expected {level} coverage from change rules, but no clear evidence was found."
                + (f" Suggested location: {recommended_path}." if recommended_path else "")
            ),
        }
        if recommended_path:
            finding["recommended_test_path"] = recommended_path
        findings.append(finding)
    if "api_contract_change" in classifications:
        findings.append(
            {
                "severity": "medium",
                "category": "contract-risk",
                "finding": "Contract or payload behavior appears touched; verify compatibility and consumer-visible behavior.",
            }
        )
    if "data_mapping_change" in classifications:
        findings.append(
            {
                "severity": "medium",
                "category": "mapping-risk",
                "finding": "Mapping behavior appears touched; verify source-to-target parity, nulls, and boundary values.",
            }
        )
    if "async_flow_change" in classifications:
        findings.append(
            {
                "severity": "medium",
                "category": "async-risk",
                "finding": "Async behavior appears touched; verify retries, idempotency, and timeout handling.",
            }
        )
    if not classifications:
        findings.append(
            {
                "severity": "medium",
                "category": "classification-gap",
                "finding": "Change type could not be classified from supplied summary, files, or diff.",
            }
        )
    if local_report.touched_files and not local_report.nearby_tests and not test_evidence:
        findings.append(
            {
                "severity": "medium",
                "category": "coverage-gap",
                "finding": "Touched files do not have obvious nearby tests and no external evidence was supplied.",
            }
        )
    if not findings:
        findings.append(
            {
                "severity": "low",
                "category": "no-obvious-gap",
                "finding": f"No obvious QA gap detected for: {change_summary}.",
            }
        )
    return findings


def _coverage_questions(local_report: LocalDiffReport, test_evidence: list[str], rules: dict[str, Any]) -> list[str]:
    questions = []
    if not test_evidence:
        questions.append("Which automated or manual evidence proves the changed behavior?")
    if local_report.touched_files:
        questions.append("Which customer journey maps to the touched files?")
    for item in rules["must_consider"][:3]:
        questions.append(f"What evidence covers {item}?")
    questions.append("What is the smallest regression set that would catch a broken release here?")
    return _dedupe(questions)


def _testing_answer(
    question: str,
    context: str | None,
    classifications: list[str],
    rules: dict[str, Any],
) -> dict[str, Any]:
    """Deterministic skeleton for `qa_answer_testing_question`. Surfaces the
    universal QA bones (smallest useful test set, named risk areas) plus
    classification-driven specialisation. Domain-specific specialisation
    (delivery / stock / pricing) is the AI's job — the AI is grounded in
    ISTQB risk-based testing in the system prompt and reads the question
    + context verbatim via MCP sampling.
    """
    verify = ["observable expected outcome", "nearest negative path", *rules["must_consider"][:4]]
    # Risk surfacing is the AI's job (see _build_question_sampling_prompt).
    # The previously hard-coded boilerplate ("unclear acceptance criteria",
    # "missing test data", "unverified downstream behavior") was being
    # parroted by the host LLM and tripped the rubric's no_generic_advice
    # dimension. Those phrases describe gaps in input, not change-specific
    # risks, so they belong in missing_information.
    risks: list[str] = []
    if "api_contract_change" in classifications:
        verify.extend(["request validation", "response shape", "consumer compatibility"])
    if "data_mapping_change" in classifications:
        verify.extend(["stored value", "read-back behavior", "null and missing value behavior"])
    return {
        "short_answer": "Test the customer-visible boundary first, then cover the nearest rule, contract, or data boundary that could break release confidence.",
        "verify": _dedupe(verify),
        "risk_areas": risks,
        "known_facts": [context] if context else [],
    }


def _prepare_missing_information(criteria: list[str], risk_notes: list[str]) -> list[str]:
    missing = []
    if not criteria:
        missing.append("acceptance criteria")
    if not risk_notes:
        missing.append("known risk notes or explicit blast radius")
    return missing


def _review_missing_information(
    local_report: LocalDiffReport,
    test_evidence: list[str],
    classifications: list[str],
) -> list[str]:
    missing = []
    if not local_report.touched_files:
        missing.append("changed file paths or diff")
    if not test_evidence and not local_report.nearby_tests:
        missing.append("test evidence")
    if not classifications:
        missing.append("classifiable change type")
    missing.extend(local_report.missing_test_levels)
    return _dedupe(missing)


def _question_missing_information(context: str | None, classifications: list[str]) -> list[str]:
    missing = []
    if not context:
        missing.append("local context for the testing question")
        # These are gaps in input, not risks. They moved out of risk_areas
        # in _testing_answer to stop the host LLM parroting them as
        # generic risks (rubric: no_generic_advice).
        missing.append("unclear acceptance criteria")
        missing.append("missing test data")
        missing.append("unverified downstream behavior")
    if not classifications:
        missing.append("specific change type")
    return missing


def _common_assumptions(knowledge: KnowledgeContext, context_supplied: bool) -> list[str]:
    assumptions = []
    if not context_supplied:
        assumptions.append("Only the supplied prompt is available.")
    if not knowledge.items:
        assumptions.append("No external domain knowledge provider is configured.")
    if knowledge.confidence == "low":
        assumptions.append("Domain-specific facts are not being inferred from an external source.")
    return _dedupe(assumptions)


def _confidence(
    missing_information: list[str],
    has_classification: bool,
    has_evidence: bool,
    knowledge: KnowledgeContext,
) -> Confidence:
    if not has_classification and missing_information:
        return Confidence(level="low", reason="The input lacks enough detail to classify the QA risk confidently.")
    if missing_information and not has_evidence:
        return Confidence(level="medium", reason="The change can be reasoned about, but key evidence or context is missing.")
    if knowledge.confidence == "high" and has_evidence:
        return Confidence(level="high", reason="The output is backed by supplied evidence and high-confidence domain context.")
    return Confidence(level="medium", reason="The output is deterministic and rule-backed, but external domain knowledge is not configured.")


def _avoid_testing(workflow: str, rules: dict[str, Any], missing_information: list[str]) -> list[str]:
    avoid = list(rules["avoid_testing"])
    if workflow == "prepare" and "acceptance criteria" in missing_information:
        avoid.append("large regression runs before the expected behavior is testable")
    if workflow == "review":
        avoid.append("broad suites that do not assert the changed behavior or expected risk")
    if workflow == "question":
        avoid.append("generic test lists not tied to the stated risk")
    return _dedupe(avoid)


def _prepare_summary(work_item: str, risks: list[RiskItem], tests: SuggestedTests) -> str:
    risk = risks[0].category if risks else "unknown risk"
    test_count = len(tests.flatten())
    return f"QA focus: {risk}. Use {test_count} targeted test recommendation(s) before handoff for: {work_item}."


def _prepare_headline(
    work_item: str,
    risks: list[RiskItem],
    missing_information: list[str],
    thin_input: bool = False,
) -> str:
    work_snippet = _truncate(work_item, 80)
    if thin_input:
        return (
            f"Need a more specific work item to plan QA. '{work_snippet}' is too short - "
            "tell me what changes (file/component, behaviour, contract) and the expected outcome."
        )
    if missing_information:
        return (
            f"Before coding '{work_snippet}': resolve missing input "
            f"({', '.join(missing_information[:2])}) so the QA plan can be specific."
        )
    top = _highest_severity_risk(risks)
    if top is not None:
        return f"Top QA risk for '{work_snippet}': {top.category} - {top.description}"
    return f"No obvious QA risk yet for '{work_snippet}'; confirm blast radius before coding."


def _is_thin_prepare_input(work_item: str, criteria: list[str], risk_notes: list[str]) -> bool:
    if criteria or risk_notes:
        return False
    return len(" ".join(work_item.split())) < 20


def _is_thin_scaffold_input(work_item: str, conditions: list[str]) -> bool:
    work_words = len(" ".join(work_item.split()))
    return work_words < 20 and not conditions


def _scaffold_headline(
    work_item: str,
    tasks: list[ScaffoldTask],
    missing_information: list[str],
    thin_input: bool,
) -> str:
    snippet = _truncate(work_item, 80)
    if thin_input:
        return (
            f"Need a more specific work item and at least one test condition before "
            f"I can scaffold tasks. '{snippet}' is too short."
        )
    if missing_information:
        return (
            f"Scaffold for '{snippet}': resolve missing input "
            f"({', '.join(missing_information[:2])}) before writing files."
        )
    if not tasks:
        return f"No scaffold tasks generated for '{snippet}' - check classifications and target paths."
    return f"Scaffold {len(tasks)} test task(s) for '{snippet}'. Execute in order; verify after each."


def _build_scaffold_sampling_prompt(work_item: str, payload: dict[str, Any]) -> str:
    classification = payload.get("change_classification", {})
    primary = classification.get("primary") or "unclassified"
    primary_confidence = classification.get("primary_confidence", "low")
    classification_summary = f"{primary} ({primary_confidence} confidence)"
    standards = [
        check["title"] for check in payload.get("standards", {}).get("checks", []) if check.get("title")
    ]
    rules = payload.get("applied_rules", {}).get("must_consider", [])
    facts = [f"Work item: {work_item}"]
    targets = payload.get("target_paths", [])
    if targets:
        facts.append("Target paths: " + ", ".join(targets[:6]))
    tasks = payload.get("tasks", [])
    if tasks:
        facts.append(
            "Scaffold tasks (host writes these): "
            + "; ".join(f"{t['id']} {t['file_path']} ({t['framework']})" for t in tasks[:5])
        )
    base = build_guardrailed_qa_prompt(
        goal=(
            "Refine the scaffold tasks AND surface gaps.\n"
            "- Keep the file paths and frameworks of host-supplied tasks unchanged.\n"
            "- Improve assertion phrasings when they are vague.\n"
            "- Crucially: when the host-supplied task list under-covers the validator's\n"
            "  branches OR the supplied acceptance criteria, list the gap under\n"
            "  `uncovered_branches`. Never silently approve under-scaffolded coverage.\n"
            "- Never silently complete a stub - red phase first; the host implements\n"
            "  production code only after all scaffolds fail honestly."
        ),
        facts=facts,
        classification_summary=classification_summary,
        missing_test_levels=[],
        recommended_test_paths=[t["file_path"] for t in tasks[:5]],
        findings=[],
        standards=standards,
        rules=rules,
    )
    return base + "\n\n" + _domain_anchoring_and_json_schema(
        schema_lines=[
            '  "narrative": "<3-6 sentences explaining how the scaffold tasks line up with the change>",',
            '  "task_refinements": [',
            '    {"task_id": "<scaffold task id>", "improved_assertion": "<sharper red-phase assertion tied to this file/class>"}',
            '  ],',
            '  "boundary_scaffolds": [',
            '    {',
            '      "ac_text": "<the verbatim acceptance criterion that demands enforcement at a boundary>",',
            '      "boundary_layer": "<service|repository|controller|consumer|other>",',
            '      "scaffold_assertion": "<concrete assertion proving the caller refuses the operation when the validator/predicate returns non-empty violations / fails>"',
            '    }',
            '  ],',
            '  "uncovered_branches": [',
            '    {',
            '      "branch_or_ac": "<the validator branch or acceptance-criterion clause that no current scaffold covers>",',
            '      "proposed_scaffold": {',
            '        "file_path": "<expected test file path>",',
            '        "framework": "<test framework, matching style of host-supplied tasks>",',
            '        "assertion": "<concrete red-phase assertion the host should add>"',
            '      },',
            '      "why_minimum_useful": "<why this scaffold is needed for the smallest useful set, not a nice-to-have>"',
            '    }',
            '  ],',
            '  "cross_cutting_assertions": [',
            '    {',
            '      "ac_text": "<the verbatim acceptance criterion that applies as a property to every result entry>",',
            '      "applies_to": "<which return shape: each violation / each result entry / each error response / etc.>",',
            '      "assertion_template": "<concrete assertion template the host should add to every relevant test>"',
            '    }',
            '  ],',
            '  "top_risks": [',
            '    {',
            '      "risk": "<change-specific risk in this scaffold\'s target>",',
            '      "why_specific_to_this_change": "<reason this risk is not generic>",',
            '      "scaffold_coverage_task_id": "<id of the task_refinement OR boundary_scaffold that covers this risk, OR \\"NONE\\" if uncovered>"',
            '    }',
            '  ],',
            '  "principle_citations": [',
            '    {"principle": "<ISTQB Foundation N - short name>", "applied_to_task_id": "<task id>"}',
            '  ],',
            '  "named_techniques": [',
            '    {"technique": "<ISTQB test design technique>", "applied_to_task_id": "<task id>"}',
            '  ],',
            '  "specialty_needs": [',
            '    {"specialty": "<security|performance|frontend|contract|mobile|a11y|ai|mutation-testing|other>", "tool": "<concrete well-known tool name>"}',
            '  ],',
            '  "assumptions": ["<labelled assumption>", "..."]',
        ],
        extra_required=(
            "HARD REQUIREMENT — principle citation + named techniques: every "
            "scaffold task MUST be supported by at least one named ISTQB "
            "principle (cited by name or number) under principle_citations AND "
            "at least one named ISTQB test design technique under "
            "named_techniques. Generic mentions like \"follow QA best "
            "practices\" or \"add edge cases\" are not acceptable.\n\n"
            "Required: surface 2-5 top_risks specific to THIS change. Each "
            "risk MUST link to the scaffold (task_refinement or "
            "boundary_scaffold) that covers it via scaffold_coverage_task_id; "
            "if no current scaffold covers a real risk, set "
            "scaffold_coverage_task_id to \"NONE\" and add a corresponding "
            "entry under uncovered_branches (see below). Generic risks like "
            "\"the service might fail\" are not acceptable — anchor each risk "
            "to this scaffold's target.\n\n"
            "Required when the host-supplied task list and any "
            "boundary_scaffolds together leave a validator branch or "
            "acceptance-criterion clause uncovered: list each gap under "
            "uncovered_branches with a concrete proposed_scaffold "
            "(file_path, framework, assertion). This is how the smallest "
            "useful test set is reached when the host under-scaffolds; do "
            "NOT inflate the test set with nice-to-haves, only fill genuine "
            "minimum-coverage gaps. If host-supplied tasks plus "
            "boundary_scaffolds already cover every branch and AC clause, "
            "return `uncovered_branches: []`.\n\n"
            "Required when an acceptance criterion is a cross-cutting "
            "property of every result entry (e.g. \"each violation surfaces "
            "a clear reason and the offending SKU\" applies to every "
            "BundlesRuleViolation in the returned list): list it under "
            "cross_cutting_assertions so it is asserted in every relevant "
            "scaffold rather than only the top-level test. If no AC has "
            "this shape, return cross_cutting_assertions: [].\n\n"
            "Required when an acceptance criterion uses enforcement language "
            "('blocked at write time', 'rejected at submit', 'fails at read', "
            "'refused at handoff'): produce one boundary_scaffold entry per "
            "such AC, naming the layer above the unit under test where the "
            "enforcement actually happens. If no AC uses enforcement language, "
            "return `boundary_scaffolds: []`. This is in addition to "
            "task_refinements (which only sharpen unit-level assertions).\n\n"
            "Required: list specialty_needs ONLY when the change genuinely "
            "implies a specialty surface. Empty list `[]` is acceptable for "
            "in-process unit-level work; place justification under assumptions. "
            "When non-empty, each entry's `tool` must fit the specific risk "
            "you are addressing (named example: 'JJWT' for token-TTL boundary "
            "tests, 'OWASP ZAP' for DAST scans of HTTP endpoints — these are "
            "not interchangeable)."
        ),
        has_targets=bool(targets or tasks),
    )


def _is_thin_review_input(
    change_summary: str,
    touched_files: list[str],
    test_evidence: list[str],
    diff_available: bool,
) -> bool:
    if touched_files or test_evidence or diff_available:
        return False
    return len(" ".join(change_summary.split())) < 20


def _review_summary(
    change_summary: str,
    classifications: list[str],
    risks: list[RiskItem],
    local_report: LocalDiffReport,
) -> str:
    classification = classifications[0] if classifications else "unclassified change"
    risk = risks[0].category if risks else "no obvious risk"
    files = len(local_report.touched_files)
    return f"{classification} with {risk}; reviewed {files} touched file(s) for: {change_summary}."


def _review_headline(
    change_summary: str,
    classifications: list[str],
    risks: list[RiskItem],
    local_report: LocalDiffReport,
    test_evidence: list[str],
    thin_input: bool = False,
) -> str:
    summary_snippet = _truncate(change_summary, 80)
    if thin_input:
        return (
            f"Need more detail to review: '{summary_snippet}' is too short and no diff or "
            "touched files were supplied. Share the diff, file paths, or describe what changed."
        )
    has_evidence = bool(test_evidence or local_report.nearby_tests)
    if local_report.touched_files and not has_evidence:
        first_file = local_report.touched_files[0]
        more = f" (+{len(local_report.touched_files) - 1} more)" if len(local_report.touched_files) > 1 else ""
        return (
            f"No test evidence found for {first_file}{more}. "
            f"Add or name a test before merging: '{summary_snippet}'."
        )
    if local_report.missing_test_levels:
        levels = ", ".join(local_report.missing_test_levels[:3])
        return f"Missing {levels} coverage for: '{summary_snippet}'. Add at least one before merging."
    top = _highest_severity_risk(risks)
    if top is not None:
        return f"Highest QA risk on this change: {top.category} - {top.description}"
    return f"No obvious QA gap on this change: '{summary_snippet}'."


def _question_headline(question: str, risks: list[RiskItem], tests: SuggestedTests) -> str:
    question_snippet = _truncate(question, 80)
    test_count = len(tests.flatten())
    top = _highest_severity_risk(risks)
    if top is not None:
        return f"Test focus for '{question_snippet}': {top.description} ({test_count} tests suggested)."
    return f"Test focus for '{question_snippet}': start with the customer-visible boundary ({test_count} tests suggested)."


def _highest_severity_risk(risks: list[RiskItem]) -> RiskItem | None:
    if not risks:
        return None
    return max(risks, key=lambda risk: _SEVERITY_RANK.get(risk.severity, 0))


def _test_plan_headline(
    work_item: str,
    scope_size: str,
    risks: list[RiskItem],
    missing_information: list[str],
    thin_input: bool,
) -> str:
    snippet = _truncate(work_item, 80)
    if thin_input:
        return (
            f"Need a more specific work item to plan QA for. '{snippet}' is too short "
            "- describe what changes (component, behaviour, contract) and the expected "
            "outcome before I can build a test plan."
        )
    if missing_information:
        return (
            f"Test plan for '{snippet}' ({scope_size} scope): resolve missing "
            f"input ({', '.join(missing_information[:2])}) so the plan stays specific."
        )
    top = _highest_severity_risk(risks)
    if top is not None:
        return (
            f"Test plan for '{snippet}' ({scope_size} scope). Top risk to design "
            f"around: {top.category} - {top.description}"
        )
    return f"Test plan for '{snippet}' ({scope_size} scope); no obvious top risk yet - validate scope before designing tests."


def _test_plan_summary(work_item: str, scope_size: str, plan: TestPlan) -> str:
    return (
        f"Phased test plan ({scope_size} scope) for: {work_item}. "
        f"{len(plan.phases)} phases, {len(plan.entry_criteria)} entry criteria, "
        f"{len(plan.exit_criteria)} exit criteria."
    )


def _build_test_plan(
    work_item: str,
    scope_size: str,
    criteria: list[str],
    provided_risks: list[str],
    rules: dict[str, Any],
    standards: Any,
    classification_names: list[str],
) -> TestPlan:
    """Build a phased test plan grounded in the deterministic rules + standards.

    Phases follow ISTQB Foundation: analysis, design, implementation, execution,
    completion. We collapse implementation+execution for small/medium scope.
    """
    test_basis = [f"Acceptance criterion: {item}" for item in criteria]
    if classification_names:
        test_basis.append(f"Change classification: {', '.join(classification_names)}")
    if standards.checks:
        test_basis.extend(f"Standards check: {check['title']}" for check in standards.checks[:3])

    approach = list(rules.get("test_design_techniques", []))[:4]
    if not approach:
        approach = ["risk-based test selection", "specification-based design from acceptance criteria"]

    entry_criteria = [
        "Acceptance criteria are explicit and observable.",
        "Test data classes (valid / invalid / boundary) are identified.",
    ]
    if criteria:
        entry_criteria.append("All listed acceptance criteria have a draft test condition.")
    if classification_names:
        entry_criteria.append(
            f"Standards rules for {', '.join(classification_names)} have been reviewed."
        )

    exit_criteria = [
        "Each acceptance criterion has at least one passing automated or documented manual test.",
        "All high-severity risks have explicit coverage or recorded acceptance.",
        "No high-severity defects are open against the work item.",
    ]
    if rules.get("must_consider"):
        exit_criteria.append(
            "All `must_consider` items from the change rules have explicit test conditions."
        )

    phases: list[TestPlanPhase] = [
        TestPlanPhase(
            name="Analysis",
            purpose="Establish the test basis and identify test conditions before design.",
            activities=[
                "Review acceptance criteria, contracts, and the change classification.",
                "Identify product risks (likelihood x impact) per criterion.",
                "Catalogue test conditions including boundary, error, and combinatorial cases.",
            ],
            deliverables=[
                "Annotated test basis with per-criterion test conditions.",
                "Risk register entries with severity and chosen mitigation depth.",
            ],
        ),
        TestPlanPhase(
            name="Design",
            purpose="Select techniques and design concrete test cases.",
            activities=[
                "Apply ISTQB techniques chosen by the change rules: "
                + (", ".join(approach[:3]) if approach else "boundary value analysis, decision tables, equivalence partitioning"),
                "Specify test data classes (valid, invalid, boundary).",
                "Plan static testing: review acceptance criteria, contracts, and tests of others.",
            ],
            deliverables=[
                "Test case specifications keyed to test conditions.",
                "Test data plan (representatives, boundaries, invalid classes).",
            ],
        ),
        TestPlanPhase(
            name="Implementation & execution",
            purpose="Implement the planned tests and execute them against the change.",
            activities=[
                "Author automated tests at the unit, integration, and contract levels per the suggested test types.",
                "Execute and record results; raise defects with reproduction steps.",
                "Run confirmation tests after each fix; rerun targeted regression based on impact analysis.",
            ],
            deliverables=[
                "Automated test results with traceability back to test conditions.",
                "Defect reports linked to acceptance criteria.",
            ],
        ),
        TestPlanPhase(
            name="Completion",
            purpose="Decide release-readiness and capture residual risk.",
            activities=[
                "Verify exit criteria are satisfied or explicitly waived.",
                "Summarise residual risk and any deferred coverage.",
                "Capture lessons learned for the next iteration of the test pack.",
            ],
            deliverables=[
                "Test summary report (pass/fail by criterion, residual risks).",
                "Updated regression set so the new tests aren't lost.",
            ],
        ),
    ]
    if scope_size == "small":
        # Collapse analysis+design into one for small scope.
        phases = [
            TestPlanPhase(
                name="Analysis & design",
                purpose="Identify conditions and design the smallest useful test set.",
                activities=phases[0].activities + phases[1].activities,
                deliverables=phases[0].deliverables + phases[1].deliverables,
            ),
            phases[2],
            phases[3],
        ]

    open_questions = []
    if not criteria:
        open_questions.append("What are the explicit acceptance criteria?")
    if not provided_risks:
        open_questions.append("What is the blast radius if this regresses in production?")
    if not classification_names:
        open_questions.append("How would you classify the change shape (api, mapping, async, ...)?")

    residual_risks = []
    for risk in provided_risks[:3]:
        residual_risks.append(f"Pre-flagged risk to revisit at exit: {risk}")
    if not residual_risks:
        residual_risks.append(
            "No residual risks pre-flagged; record any deferred coverage at exit."
        )

    return TestPlan(
        scope_in=criteria or [f"Behaviour described as: {work_item}"],
        scope_out=["Unrelated regression unless impact analysis brings it in scope."],
        test_basis=test_basis or [f"Stated work item: {work_item}"],
        approach=approach,
        entry_criteria=entry_criteria,
        exit_criteria=exit_criteria,
        phases=phases,
        residual_risks=residual_risks,
        open_questions=open_questions,
    )


def _build_test_plan_sampling_prompt(work_item: str, payload: dict[str, Any]) -> str:
    classification = payload.get("change_classification", {})
    primary = classification.get("primary") or "unclassified"
    primary_confidence = classification.get("primary_confidence", "low")
    classification_summary = f"{primary} ({primary_confidence} confidence)"
    standards = [
        check["title"]
        for check in payload.get("standards", {}).get("checks", [])
        if check.get("title")
    ]
    rules = payload.get("applied_rules", {}).get("must_consider", [])
    plan = payload.get("test_plan", {})
    facts = [f"Work item: {work_item}", f"Scope size: {payload.get('scope_size', 'medium')}"]
    if plan.get("scope_in"):
        facts.append("In scope: " + "; ".join(plan["scope_in"][:5]))
    if plan.get("approach"):
        facts.append("Approach: " + "; ".join(plan["approach"]))
    base = build_guardrailed_qa_prompt(
        goal="Produce a phased test plan with explicit entry/exit criteria.",
        facts=facts,
        classification_summary=classification_summary,
        missing_test_levels=[],
        recommended_test_paths=[],
        findings=plan.get("entry_criteria", []) + plan.get("exit_criteria", []),
        standards=standards,
        rules=rules,
    )
    return base + "\n\n" + _domain_anchoring_and_json_schema(
        schema_lines=[
            '  "narrative": "<3-6 sentences of senior-QA reasoning anchored to this work item>",',
            '  "phase_focus": [',
            '    {"phase": "<analysis|design|execution|completion>", "focus": "<specific focus tied to this work>"}',
            '  ],',
            '  "open_questions": ["<change-specific open question>"],',
            '  "specialty_needs": [',
            '    {"specialty": "<security|performance|frontend|contract|mobile|a11y|ai|mutation-testing|other>", "tool": "<concrete well-known tool name>"}',
            '  ],',
            '  "assumptions": ["<labelled assumption>", "..."]',
        ],
        extra_required=(
            "Required: list specialty_needs ONLY when the work item genuinely "
            "implies a specialty surface. Empty list `[]` is acceptable for "
            "in-process unit-level work; place justification under assumptions. "
            "When non-empty, each entry's `tool` must fit the specific risk "
            "you are addressing (named example: 'JJWT' for token-TTL boundary "
            "tests, 'OWASP ZAP' for DAST scans of HTTP endpoints — these are "
            "not interchangeable)."
        ),
        has_targets=bool(plan.get("scope_in") or plan.get("approach")),
    )


def _truncate(value: str, limit: int) -> str:
    """Trim a string to a soft character limit at a word boundary.

    No trailing ellipsis. Headlines and short fields are inherently summaries;
    the reader knows long input was condensed and an ellipsis just adds noise.
    """
    cleaned = " ".join(value.split())
    if len(cleaned) <= limit:
        return cleaned
    cut = cleaned[:limit].rstrip()
    space = cut.rfind(" ")
    if space > limit // 2:
        cut = cut[:space]
    return cut.rstrip(",;.:")


def _recommended_test_path(level: str, touched_files: list[str]) -> str:
    if not touched_files:
        return ""
    primary = Path(touched_files[0])
    stem = primary.stem
    if not stem:
        return ""
    suffix_for = {
        "unit": "",
        "integration": "_integration",
        "contract": "_contract",
        "functional": "_functional",
        "nonfunctional": "_perf",
    }
    suffix = suffix_for.get(level, "")
    parent_parts = [part for part in primary.parent.parts if part not in {"", "src", "."}]
    parent_segment = "/".join(parent_parts)
    if parent_segment:
        return f"tests/{parent_segment}/test_{stem}{suffix}.py"
    return f"tests/test_{stem}{suffix}.py"


def _has_strong_classification(classification: Any) -> bool:
    if not classification.classifications:
        return False
    return classification.classifications[0].confidence != "low"


def _file_hint(touched_files: list[str]) -> str:
    if not touched_files:
        return ""
    head = touched_files[:2]
    extra = len(touched_files) - len(head)
    suffix = f" (+{extra} more)" if extra > 0 else ""
    return f" Touched: {', '.join(head)}{suffix}."


def _review_verdict(findings: list[dict[str, str]], confidence: Confidence) -> str:
    severities = {finding["severity"] for finding in findings}
    if "high" in severities:
        return "needs-test-evidence"
    if "medium" in severities or confidence.level == "low":
        return "review-risk-before-handoff"
    return "qa-risk-acceptable-for-phase-1-input"


_SEVERITY_RANK = {"low": 0, "medium": 1, "high": 2}


def _unique_risks(risks: list[RiskItem]) -> list[RiskItem]:
    by_key: dict[tuple[str, str], tuple[int, RiskItem]] = {}
    order: list[tuple[str, str]] = []
    for risk in risks:
        key = (risk.category, risk.description)
        existing = by_key.get(key)
        if existing is None:
            order.append(key)
            by_key[key] = (_SEVERITY_RANK.get(risk.severity, 0), risk)
        elif _SEVERITY_RANK.get(risk.severity, 0) > existing[0]:
            by_key[key] = (_SEVERITY_RANK.get(risk.severity, 0), risk)
    return [by_key[key][1] for key in order]


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            result.append(item)
    return result


# ============================================================================
# Response slimming
# ============================================================================
#
# Without this, tool calls dump 16KB+ of JSON into the host's chat surface
# even though the model only renders 5-6 fields. Every "for completeness"
# field I added accumulated into noise the user has to scroll past.
#
# The shape below is the contract:
#   - Primary fields: what the host model actually renders (small, capped)
#   - `_debug`: everything else, hidden by default but available for inspection
#
# Eval reads `top_risks`, `applied_rules.must_consider`, `applied_rules.risk_templates`,
# `suggested_tests.<level>`, and `confidence.level`. Those stay primary.
#

_PRIMARY_FIELDS_BY_TOOL: dict[str, tuple[str, ...]] = {
    "sumo_qa_prepare_for_work": (
        "tool", "headline", "top_risks", "suggested_tests",
        "missing_information", "confidence", "presentation",
        "test_design_techniques", "specialty_testing_needs",
        "recommended_approach", "applied_rules",
    ),
    "sumo_qa_review_local_change": (
        "tool", "headline", "verdict", "top_risks", "qa_findings",
        "suggested_tests", "missing_information", "confidence",
        "presentation", "test_design_techniques", "specialty_testing_needs",
        "recommended_approach", "applied_rules",
    ),
    "sumo_qa_answer_testing_question": (
        "tool", "headline", "answer", "top_risks", "suggested_tests",
        "missing_information", "confidence", "presentation",
        "test_design_techniques", "specialty_testing_needs",
        "recommended_approach", "applied_rules",
    ),
    "sumo_qa_create_test_plan": (
        "tool", "headline", "test_plan", "top_risks", "suggested_tests",
        "missing_information", "confidence", "presentation",
        "test_design_techniques", "specialty_testing_needs",
        "recommended_approach", "scope_size", "applied_rules",
    ),
    "sumo_qa_scaffold_tests": (
        "tool", "headline", "tasks", "execution_order",
        "missing_information", "confidence", "presentation",
        "specialty_testing_needs", "recommended_approach",
    ),
    "sumo_qa_decide_approach": (
        "tool", "recommended_approach", "presentation",
    ),
}


def _slim(payload: dict[str, Any]) -> dict[str, Any]:
    """Trim a tool response to its primary fields and drop the rest.

    The host model sees only what it needs to render. Reference data
    (loaded standards, full rule definitions, classification details,
    expanded approach reasoning, llm_analysis blobs) is dropped — not
    nested under `_debug` — so we don't pay the transmission cost.

    Eval-required fields stay at the top level: `top_risks`,
    `applied_rules.must_consider`, `applied_rules.risk_templates`,
    `suggested_tests.<level>`, `confidence.level`.
    """
    tool = payload.get("tool", "")
    primary_keys = _PRIMARY_FIELDS_BY_TOOL.get(tool)
    if primary_keys is None:
        return payload  # unknown tool — leave it alone

    primary: dict[str, Any] = {}
    for key in primary_keys:
        if key in payload:
            value = payload[key]
            if _is_empty_or_boilerplate(key, value):
                continue
            primary[key] = value

    # Cap noisy lists.
    if "top_risks" in primary:
        primary["top_risks"] = primary["top_risks"][:3]
    if "qa_findings" in primary:
        primary["qa_findings"] = primary["qa_findings"][:3]
    if "test_design_techniques" in primary:
        primary["test_design_techniques"] = primary["test_design_techniques"][:3]
    if "specialty_testing_needs" in primary:
        primary["specialty_testing_needs"] = primary["specialty_testing_needs"][:2]
    if "missing_information" in primary:
        primary["missing_information"] = primary["missing_information"][:3]

    # Compact recommended_approach to the decision essentials.
    if "recommended_approach" in primary:
        full_ra = primary["recommended_approach"]
        next_action = full_ra.get("next_action")
        next_tool = next_action.get("tool") if isinstance(next_action, dict) else None
        next_skill = next_action.get("skill") if isinstance(next_action, dict) else None
        slim_next_action: dict[str, Any] | None
        if next_tool or next_skill:
            slim_next_action = {"tool": next_tool, "skill": next_skill}
        else:
            slim_next_action = None
        slim_ra: dict[str, Any] = {
            "approach": full_ra.get("approach"),
            "confidence": full_ra.get("confidence"),
            "next_action": slim_next_action,
        }
        rationale = full_ra.get("rationale")
        if rationale:
            slim_ra["rationale"] = rationale
        follow_up = full_ra.get("follow_up")
        if follow_up:
            slim_ra["follow_up"] = follow_up
        primary["recommended_approach"] = slim_ra

    # Slim applied_rules to just the eval-relevant arrays.
    if "applied_rules" in primary:
        full_rules = primary["applied_rules"]
        primary["applied_rules"] = {
            "must_consider": full_rules.get("must_consider", []),
            "risk_templates": full_rules.get("risk_templates", []),
        }

    # Compact presentation hints — drop the long render_instructions; keep the cap.
    if "presentation" in primary:
        pres = primary["presentation"]
        if isinstance(pres, dict):
            primary["presentation"] = {
                k: v for k, v in pres.items() if k in {"style", "max_words"}
            }

    return primary


_BOILERPLATE_KEYS = {
    "assumptions",
    "knowledge_context",
    "coverage_questions",
    "recommended_tests",
    "avoid_testing",
    "quality_characteristics",
}


def _is_empty_or_boilerplate(key: str, value: Any) -> bool:
    """Pure-noise fields we'd rather drop than nest in _debug."""
    if key in _BOILERPLATE_KEYS:
        return True
    if value in (None, "", [], {}):
        return True
    return False
