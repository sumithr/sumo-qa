import os
from pathlib import Path
from typing import Any

from sumo_qa.debug_capture import maybe_capture
from sumo_qa.llm import HostSamplingClient
from sumo_qa.tools import QAShiftLeftService, _slim


def _maybe_host_llm(ctx: Any) -> HostSamplingClient | None:
    """Return a HostSamplingClient if the host advertises sampling and the user hasn't opted out.

    Returns None when:
      - the user opted out via QA_DISABLE_HOST_SAMPLING
      - no Context was supplied (unit-test invocation)
      - the FastMCP request context isn't established (no live host session)
      - the host's session does not implement create_message
    """
    if os.environ.get("QA_DISABLE_HOST_SAMPLING", "").lower() in {"1", "true", "yes"}:
        return None
    if ctx is None:
        return None
    try:
        session = ctx.session
    except (ValueError, AttributeError):
        return None
    if session is None or not hasattr(session, "create_message"):
        return None
    return HostSamplingClient(session=session)


def build_service() -> QAShiftLeftService:
    standards_path = Path(os.environ.get("QA_STANDARDS_PATH", "standards/packs"))
    rules_path = Path(os.environ.get("QA_RULES_PATH", "standards/rules/change_rules.yaml"))
    test_data_path = Path(os.environ.get("QA_TEST_DATA_PATH", "knowledge/test_data"))
    return QAShiftLeftService.from_standards_path(standards_path, rules_path, test_data_path)


def build_mcp_server(service: QAShiftLeftService | None = None) -> Any:
    try:
        from mcp.server.fastmcp import Context, FastMCP
    except ImportError as exc:
        raise RuntimeError("The MCP SDK is not installed. Run `pip install -e .`.") from exc

    qa_service = service or build_service()
    mcp = FastMCP("qa-shift-left-mcp")

    @mcp.tool()
    async def qa_prepare_for_work(
        work_item: str,
        acceptance_criteria: list | None = None,
        risk_notes: list | None = None,
        explicit_classifications: list | None = None,
        target_paths: list | None = None,
        ctx: Context = None,
    ) -> dict:
        """Generate a QA plan from a work item, user story, ticket, or feature description.

        Returns: top risks, smallest useful test set, missing information, and
        entry questions. Optional `acceptance_criteria` and `risk_notes` lists,
        when supplied, are folded into the plan.

        `explicit_classifications` is the list of canonical change classifications
        this work falls under (e.g. ["api_contract_change", "data_mapping_change"]).
        When supplied, the team's loaded standards/rules dispatch on them. When
        omitted, the AI-sampling path classifies dynamically; the deterministic
        harness no longer pattern-matches paths or text to guess.

        `target_paths` (optional) anchors the plan to concrete files / classes
        / modules in the supplied repo. When the work_item names a boundary
        not present in `target_paths`, the AI surfaces the gap as
        `missing_information` instead of fabricating artefacts.

        Canonical classification names: api_contract_change, business_logic_change,
        state_transition_change, ui_only_change, configuration_change,
        data_mapping_change, error_handling_change, async_flow_change, caching_change.

        Common natural-language phrasings that map to this tool:
        "plan QA for this", "what should I test for X", "QA strategy for X",
        "what could go wrong if we add X", "before I start coding X what should
        I think about", "what tests should I write for this story", "what's the
        test plan for X".
        """
        return maybe_capture(
            tool="qa_prepare_for_work",
            args={
                "work_item": work_item,
                "acceptance_criteria": acceptance_criteria,
                "risk_notes": risk_notes,
                "explicit_classifications": explicit_classifications,
                "target_paths": target_paths,
            },
            output=_slim(await qa_service.aqa_prepare_for_work(
                work_item, acceptance_criteria, risk_notes,
                async_llm=_maybe_host_llm(ctx),
                explicit_classifications=explicit_classifications,
                target_paths=target_paths,
            )),
        )

    @mcp.tool()
    async def qa_review_local_change(
        change_summary: str,
        diff: str = "",
        touched_files: list | None = None,
        test_evidence: list | None = None,
        explicit_classifications: list | None = None,
        ctx: Context = None,
    ) -> dict:
        """Review uncommitted code, a diff, or a list of touched files for QA risk.

        Returns: verdict (`needs-test-evidence` / `review-risk-before-handoff` /
        `qa-risk-acceptable-for-phase-1-input`), classified change type with
        confidence, missing test levels, recommended test paths, and findings
        keyed to the actual touched files. When `diff` and `touched_files` are
        omitted, the server runs `git diff` in the working directory.

        `explicit_classifications`: list of canonical change classifications
        this change falls under (see qa_prepare_for_work for the canonical
        set). When supplied, the rules engine dispatches on them. When omitted,
        the AI-sampling path classifies dynamically.

        Common natural-language phrasings that map to this tool:
        "review my changes", "is this safe to merge", "QA risk on this PR",
        "what could break if I ship this", "did I miss any tests for this
        change", "look at my diff and tell me what to test", "is this change
        risky".
        """
        return maybe_capture(
            tool="qa_review_local_change",
            args={
                "change_summary": change_summary,
                "diff": diff,
                "touched_files": touched_files,
                "test_evidence": test_evidence,
                "explicit_classifications": explicit_classifications,
            },
            output=_slim(await qa_service.aqa_review_local_change(
                change_summary, diff, touched_files, test_evidence,
                async_llm=_maybe_host_llm(ctx),
                explicit_classifications=explicit_classifications,
            )),
        )

    @mcp.tool()
    async def qa_create_test_plan(
        work_item: str,
        scope_size: str = "medium",
        acceptance_criteria: list | None = None,
        risk_notes: list | None = None,
        explicit_classifications: list | None = None,
        ctx: Context = None,
    ) -> dict:
        """Produce a phased ISTQB-style test plan with entry/exit criteria and deliverables.

        For larger or formally-tracked pieces of work where a flat risk list isn't
        enough. Returns a structured `test_plan` (scope in/out, test basis,
        approach, entry criteria, exit criteria, phases with deliverables,
        residual risks, open questions) plus the usual top risks, suggested
        tests, ISTQB techniques, ISO 25010 quality characteristics, and any
        specialty testing capabilities the change implies (e.g. Cypress for
        frontend, k6 for performance).

        Common natural-language phrasings that map to this tool:
        "create a test plan for X", "give me a formal QA plan for X",
        "draft the test plan I should follow for X", "I'm starting a major
        feature, plan QA properly", "what are the entry/exit criteria for X".
        """
        return maybe_capture(
            tool="qa_create_test_plan",
            args={
                "work_item": work_item,
                "scope_size": scope_size,
                "acceptance_criteria": acceptance_criteria,
                "risk_notes": risk_notes,
                "explicit_classifications": explicit_classifications,
            },
            output=_slim(await qa_service.aqa_create_test_plan(
                work_item,
                scope_size,
                acceptance_criteria,
                risk_notes,
                async_llm=_maybe_host_llm(ctx),
                explicit_classifications=explicit_classifications,
            )),
        )

    @mcp.tool()
    async def qa_decide_approach(
        intent_text: str,
        target_paths: list | None = None,
        signals: dict | None = None,
        ctx: Context = None,
    ) -> dict:  # noqa: D401  (long description below)
        """Decide which QA approach fits this change shape, before doing any deeper work.

        Returns a `recommended_approach` with one of:
          - tdd-scaffold (greenfield-ish; plan -> scaffold -> implement -> green)
          - regression-first (bug fix; reproduce as failing test, then fix)
          - coverage-first-then-refactor (refactor with no behaviour change)
          - verify-existing (config-only / trivial tweak; no new tests)
          - no-tests-recommended (pure docs / typos / comments)
          - spike-first-then-tests (exploratory prototype)

        Plus rationale, the next tool to call (or `null` if no tool), follow-up
        guidance, alternatives, and a confidence band. The host model uses this
        to decide whether to call `qa_scaffold_tests`, `qa_review_local_change`,
        or skip QA tooling entirely.

        Common natural-language phrasings that map to this tool:
        "what QA approach should I take for X", "should I write tests for X",
        "is this a TDD case or a regression test", "what's the right testing
        strategy for X", "do I even need tests for X".
        """
        return maybe_capture(
            tool="qa_decide_approach",
            args={
                "intent_text": intent_text,
                "target_paths": target_paths,
                "signals": signals,
            },
            output=_slim(await qa_service.aqa_decide_approach(
                intent_text,
                target_paths,
                signals,
                async_llm=_maybe_host_llm(ctx),
            )),
        )

    @mcp.tool()
    async def qa_scaffold_tests(
        work_item: str,
        test_conditions: list | None = None,
        target_paths: list | None = None,
        explicit_classifications: list | None = None,
        ctx: Context = None,
    ) -> dict:
        """Produce structured test-scaffold tasks the host model writes with its own file tools.

        Returns a list of `tasks`, each with:
          - file_path (chosen by convention from the target source path)
          - framework (pytest / Vitest / Jest / Playwright / Cypress / k6 /
            Schemathesis / Promptfoo / axe-core / Appium / JUnit 5 / XCTest)
          - language
          - level (unit / integration / contract / functional / nonfunctional)
          - techniques (named ISTQB techniques applied)
          - assertions (named, tied to test conditions)
          - skeleton (honestly-stubbed code - assertions raise / TODO so the
            host knows nothing has been verified yet; this is TDD red phase)
          - verify_command (e.g. `pytest tests/orders/test_api.py -v`)
          - specialty + specialty_mcp_hint when the task should be routed to a
            specialty MCP (Cypress, k6, Pact, Playwright + axe-core, etc.)

        Plus an `execution_order` (unit -> integration -> contract -> functional -> nonfunctional)
        and the deterministic guardrails (top_risks, classification, standards).

        The MCP itself does NOT write files. The host model iterates through
        `execution_order`, writes each `tasks[i].file_path` with `tasks[i].skeleton`
        using its Edit/Write tools, runs `tasks[i].verify_command`, sees the
        test fail (red), and only then writes the production code.

        Common natural-language phrasings that map to this tool:
        "scaffold tests for X", "write the test files for X", "set up the
        test suite for X", "give me the failing tests so I can implement
        against them", "create the test stubs for X".
        """
        return maybe_capture(
            tool="qa_scaffold_tests",
            args={
                "work_item": work_item,
                "test_conditions": test_conditions,
                "target_paths": target_paths,
                "explicit_classifications": explicit_classifications,
            },
            output=_slim(await qa_service.aqa_scaffold_tests(
                work_item,
                test_conditions,
                target_paths,
                async_llm=_maybe_host_llm(ctx),
                explicit_classifications=explicit_classifications,
            )),
        )

    @mcp.tool()
    async def qa_answer_testing_question(
        question: str,
        context: str = "",
        explicit_classifications: list | None = None,
        ctx: Context = None,
    ) -> dict:
        """Answer a free-form testing question with risk-based, actionable QA guidance.

        Returns: a short answer, what to verify, risk areas, and the smallest
        useful test set. Optional `context` (code snippet, ticket text, etc.)
        is folded into the reasoning.

        Common natural-language phrasings that map to this tool:
        "how do I test X", "how should I test Y", "what's the right way to test
        X", "should I write a unit or integration test for Z", "how do I verify
        X", "what tests would prove X".
        """
        return maybe_capture(
            tool="qa_answer_testing_question",
            args={
                "question": question,
                "context": context,
                "explicit_classifications": explicit_classifications,
            },
            output=_slim(await qa_service.aqa_answer_testing_question(
                question, context,
                async_llm=_maybe_host_llm(ctx),
                explicit_classifications=explicit_classifications,
            )),
        )

    @mcp.tool()
    def qa_explain_test_data_requirements(
        question: str,
        environment: str = "",
        domain: str = "",
    ) -> dict:
        """Explain what test data shape and characteristics are needed for a scenario.

        Returns: required product characteristics, stock/fulfilment conditions,
        downstream dependencies, edge cases, and explicit "what NOT to use"
        guidance. Optional `environment` (e.g. "integration") and `domain` are
        folded into the analysis.

        Common natural-language phrasings that map to this tool:
        "what data do I need to test X", "what test data should I look for to
        cover X", "what records / SKUs / postcodes / accounts do I need for X",
        "what's the minimum data setup for X", "what edge-case data should I
        test".
        """
        return maybe_capture(
            tool="qa_explain_test_data_requirements",
            args={
                "question": question,
                "environment": environment,
                "domain": domain,
            },
            output=_slim(qa_service.qa_explain_test_data_requirements(question, environment, domain)),
        )

    @mcp.tool()
    def qa_find_test_data(
        environment: str = "",
        domain: str = "",
        scenario_tags: list | None = None,
        known_valid_for: list | None = None,
        product_id: str = "",
        sku: str = "",
        limit: int = 5,
    ) -> dict:
        """Search the local known-good test data catalogue for entries that match a scenario.

        Returns: ranked matches with confidence, freshness, and suitability
        reasons. Reads the local YAML catalogue under `knowledge/test_data/`
        only; no external lookups. Optional `scenario_tags` and `known_valid_for`
        narrow the search.

        Common natural-language phrasings that map to this tool:
        "find me test data for X", "do we have a known-good record for X",
        "give me a SKU / product / account that does X", "is there a fixture
        for X", "what test data is available for X".
        """
        return maybe_capture(
            tool="qa_find_test_data",
            args={
                "environment": environment,
                "domain": domain,
                "scenario_tags": scenario_tags,
                "known_valid_for": known_valid_for,
                "product_id": product_id,
                "sku": sku,
                "limit": limit,
            },
            output=_slim(qa_service.qa_find_test_data(
                environment,
                domain,
                scenario_tags,
                known_valid_for,
                product_id,
                sku,
                limit,
            )),
        )

    @mcp.tool()
    def qa_validate_test_data(
        entry_id: str | None = None,
        entry: dict | None = None,
    ) -> dict:
        """Validate a test data entry without provisioning or mutating downstream systems.

        Returns: validation result with confidence level, freshness status, and
        an explained reason. Accepts either `entry_id` (looked up in the
        catalogue) or `entry` (a full record dict).

        Common natural-language phrasings that map to this tool:
        "is this test data still valid", "validate this record", "is entry X
        still good", "check if X is fresh".
        """
        return maybe_capture(
            tool="qa_validate_test_data",
            args={
                "entry_id": entry_id,
                "entry": entry,
            },
            output=_slim(qa_service.qa_validate_test_data(entry_id, entry)),
        )

    @mcp.tool()
    def qa_register_known_good_test_data(entry: dict) -> dict:
        """Add or update a known-good test data entry in the local YAML catalogue.

        Detects duplicates by environment + domain + product/SKU + scenario
        overlap. Writes to `knowledge/test_data/<domain>/known_good.yaml`.

        Common natural-language phrasings that map to this tool:
        "save this as known-good test data", "register this fixture so the team
        can reuse it", "promote this record to known-good", "update the
        validated timestamp on entry X", "add this SKU to the catalogue".
        """
        return maybe_capture(
            tool="qa_register_known_good_test_data",
            args={
                "entry": entry,
            },
            output=_slim(qa_service.qa_register_known_good_test_data(entry)),
        )

    @mcp.prompt(
        name="qa_review_my_changes",
        description="Review the user's current local changes for QA risk and missing test evidence.",
    )
    def qa_review_my_changes_prompt(scope: str = "") -> str:
        scope_line = f"\n\nFocus: {scope}" if scope else ""
        # Long-form workflow body so prompt-only hosts (IntelliJ AI Assistant,
        # Cursor, etc.) get the same discipline Claude Code gets via the
        # qa-reviewing-before-merge skill file.
        return (
            "Review my current local changes for QA risk and missing test evidence."
            f"{scope_line}\n\n"
            "Workflow (follow in order, do not skip steps):\n"
            "1. Call the `qa_review_local_change` tool. Pass the change summary "
            "and any touched files I've named; otherwise let it run `git diff`.\n"
            "2. Read these fields literally: `verdict`, `change_classification.primary` "
            "(+ `primary_confidence`), `local_diff.missing_test_levels`, "
            "`qa_findings` (each with `severity` and `recommended_test_path`), "
            "`top_risks`, `recommended_approach`, `specialty_testing_needs`.\n"
            "3. Surface the verdict literally as the first line: 'VERDICT: <verdict>'. "
            "Do not paraphrase, do not soften. If the verdict is `needs-test-evidence` "
            "or `review-risk-before-handoff`, the change is NOT ready to merge.\n"
            "4. List every `qa_findings` item with its severity and (if present) "
            "the `recommended_test_path` inline.\n"
            "5. List the top 3 `top_risks`. Show the highest-severity ones first.\n"
            "6. If `specialty_testing_needs` is non-empty, surface a 'Pull in:' line "
            "naming the approach + 2-3 well-known tools.\n"
            "7. End with one of:\n"
            "   - if verdict is `needs-test-evidence`: 'Want me to scaffold the missing tests? "
            "(would call qa_scaffold_tests with the recommended_test_paths)'\n"
            "   - if `review-risk-before-handoff`: 'Which finding do you want to tackle first?'\n"
            "   - if `qa-risk-acceptable-for-phase-1-input`: 'Ready to merge unless you want me "
            "to dig into a specific risk.'\n"
            "Hard rule: never claim 'safe to merge' unless the tool's verdict says so."
        )

    @mcp.prompt(
        name="qa_what_approach",
        description="Pick the right QA approach (TDD scaffold / regression-first / refactor with coverage / verify existing / skip).",
    )
    def qa_what_approach_prompt(intent: str, target_path: str = "") -> str:
        target_line = f"\nPrimary path: {target_path}" if target_path else ""
        # Long-form workflow body so prompt-only hosts get the same discipline
        # Claude Code gets via the qa-deciding-approach skill file.
        return (
            f"Help me pick the right QA approach for: {intent}{target_line}\n\n"
            "Workflow (follow in order, do not skip):\n"
            "1. Call the `qa_decide_approach` tool with the intent text and any target paths.\n"
            "2. Read `recommended_approach`: `approach`, `rationale`, `next_action`, "
            "`follow_up`, `confidence`, `alternatives`.\n"
            "3. Announce the approach in one line, literally:\n"
            "   APPROACH: <approach> (<confidence>) -> next: <next_action.tool or 'no tool'>\n"
            "4. State the rationale in one sentence.\n"
            "5. Branch:\n"
            "   - `tdd-scaffold` or `regression-first` -> propose calling `qa_create_test_plan` "
            "(if scope is medium/large) or `qa_scaffold_tests` (smaller). Wait for confirmation.\n"
            "   - `coverage-first-then-refactor` -> propose calling `qa_review_local_change` "
            "to find coverage gaps first. Wait for confirmation.\n"
            "   - `verify-existing` -> tell me to run my existing test suite + a smoke; STOP.\n"
            "   - `no-tests-recommended` -> tell me to run the build / docs lint; STOP.\n"
            "   - `spike-first-then-tests` -> tell me to spike freely and capture conditions for later; STOP.\n"
            "6. If `confidence` is `low`, ask ONE focused clarifying question instead of guessing.\n"
            "7. List up to 2 alternatives so I can override if my context differs.\n\n"
            "Hard rule: do not call qa_scaffold_tests / qa_create_test_plan / qa_review_local_change "
            "BEFORE qa_decide_approach. The decision is the precondition; skipping it produces "
            "wrong-shaped work."
        )

    @mcp.prompt(
        name="qa_scaffold_tests_for_work",
        description="Produce honest-stub test scaffold tasks for a work item; host model writes the files.",
    )
    def qa_scaffold_tests_for_work_prompt(work_item: str, target_path: str = "") -> str:
        target_line = f"\nPrimary source path: {target_path}" if target_path else ""
        return (
            f"Scaffold the failing tests I should write for: {work_item}{target_line}\n\n"
            "Return the task list with file paths, frameworks, named assertions, "
            "and verify commands. After I confirm, write each file using your "
            "file tools and run the verify command for each (TDD red phase). "
            "If a task is tagged with a specialty (Cypress, k6, Pact, axe-core), "
            "prefer routing to that specialty MCP if one is available."
        )

    @mcp.prompt(
        name="qa_test_plan_for_work",
        description="Produce a phased ISTQB-style test plan with entry/exit criteria for a substantial piece of work.",
    )
    def qa_test_plan_for_work_prompt(work_item: str, scope_size: str = "medium") -> str:
        return (
            f"Create a test plan for this work item: {work_item}\n"
            f"Scope size: {scope_size} (small / medium / large).\n\n"
            "Show me the scope, entry criteria, the analysis-design-execution-completion "
            "phases with their deliverables, and the exit criteria. Call out any extra "
            "specialty testing capabilities I should pull in (e.g. Cypress, k6, OWASP ZAP, "
            "Appium) and any open questions I need to resolve before starting."
        )

    @mcp.prompt(
        name="qa_plan_for_work",
        description="Generate a QA plan for a user story, ticket, or feature before coding starts.",
    )
    def qa_plan_for_work_prompt(work_item: str) -> str:
        return (
            f"Plan QA for this work item: {work_item}\n\n"
            "Lead with the top QA risk, then list the smallest useful test set "
            "I should write before merging, and call out anything that needs "
            "clarification before I start coding."
        )

    @mcp.prompt(
        name="qa_how_do_i_test",
        description="Answer 'how do I test X' for any topic, behaviour, or change.",
    )
    def qa_how_do_i_test_prompt(thing: str) -> str:
        return (
            f"How do I test {thing}?\n\n"
            "Give me concrete things to verify, the likely risk areas, and the "
            "smallest useful test set."
        )

    @mcp.prompt(
        name="qa_find_data",
        description="Find a known-good test data record for a scenario.",
    )
    def qa_find_data_prompt(scenario: str) -> str:
        return (
            f"Find known-good test data for: {scenario}\n\n"
            "Show me the highest-confidence match first, with the suitability "
            "reason and freshness status."
        )

    @mcp.prompt(
        name="qa_explain_data_needs",
        description="Explain the test data shape needed for a scenario before searching for records.",
    )
    def qa_explain_data_needs_prompt(scenario: str) -> str:
        return (
            f"What test data do I need to test {scenario}?\n\n"
            "Tell me the required characteristics, the edge cases I should "
            "also cover, and what NOT to use."
        )

    @mcp.prompt(
        name="qa_validate_data",
        description="Validate a known-good test data entry by id or full record.",
    )
    def qa_validate_data_prompt(entry_id_or_entry: str) -> str:
        return (
            f"Validate this test data: {entry_id_or_entry}\n\n"
            "Lead with whether it's valid and why, including freshness and "
            "confidence."
        )

    return mcp


def main() -> None:
    build_mcp_server().run()
