"""Deterministic simulator of a well-behaved MCP host rendering a QA response.

This module exists so the maintainer can iterate on the `presentation` hints
without burning host LLM tokens. It applies the rules that a host model SHOULD
follow when it sees `presentation.render_instructions`, deterministically:

  * Lead with the right field (headline / verdict+headline / short_answer).
  * Bullet a small number of items from the structured fields.
  * Stop at the word cap.
  * Never write expanded sections, prose essays, or project-specific analysis.

If the simulator's output is sleek, the hint design is sleek. The only thing
this can't catch is "the real host model ignores the hint" - that's a single
binary check at the end via the actual host (Claude Code, IntelliJ AI Assistant,
etc.), not something to verify on every iteration.
"""
from __future__ import annotations

from typing import Any


def render_response(response: dict[str, Any]) -> str:
    """Render a QA response the way a well-behaved MCP host should.

    `presentation.max_words` is a SOFT target, not a knife. The renderer keeps
    the output bounded by *structure* (a fixed set of fields, each with a
    bounded amount of text) rather than by mid-sentence truncation. If a
    legitimately complex response needs to exceed the soft target to stay
    honest, it does. Tests assert against a hard runaway ceiling
    (typically 2x the soft target) instead.

    Raises KeyError if the response has no `presentation` field, since that
    means the response shape is broken upstream.
    """
    # Touch the field so a missing one still raises KeyError as documented.
    _ = response["presentation"]
    tool = response.get("tool", "")

    if tool == "sumo_qa_prepare_for_work":
        return _render_prepare(response)
    if tool == "sumo_qa_review_local_change":
        return _render_review(response)
    if tool == "sumo_qa_answer_testing_question":
        return _render_question(response)
    if tool == "sumo_qa_create_test_plan":
        return _render_test_plan(response)
    if tool == "sumo_qa_scaffold_tests":
        return _render_scaffold(response)
    if tool == "sumo_qa_decide_approach":
        return _render_decide_approach(response)
    # Fallback: just the headline.
    return response.get("headline", "(no headline)")


def _render_prepare(response: dict[str, Any]) -> str:
    parts: list[str] = [_format_approach_line(response.get("recommended_approach", {})), response.get("headline", "")]
    risks_block = _format_risks(response.get("top_risks", [])[:3])
    if risks_block:
        parts.append(risks_block)
    tests_block = _format_flat_tests(response.get("suggested_tests", {}), limit=5)
    if tests_block:
        parts.append(tests_block)
    apply_line = _format_apply_line(response.get("test_design_techniques", []))
    if apply_line:
        parts.append(apply_line)
    specialty_block = _format_specialty_block(response.get("specialty_testing_needs", []))
    if specialty_block:
        parts.append(specialty_block)
    missing = response.get("missing_information", [])[:2]
    if missing:
        parts.append("Need: " + "; ".join(missing))
    return "\n\n".join(p for p in parts if p)


def _render_review(response: dict[str, Any]) -> str:
    verdict = response.get("verdict", "")
    parts: list[str] = [_format_approach_line(response.get("recommended_approach", {}))]
    if verdict:
        parts.append(f"VERDICT: {verdict}")
    parts.append(response.get("headline", ""))
    findings_block = _format_findings(response.get("qa_findings", [])[:3])
    if findings_block:
        parts.append(findings_block)
    risks_block = _format_risks(response.get("top_risks", [])[:3])
    if risks_block:
        parts.append(risks_block)
    apply_line = _format_apply_line(response.get("test_design_techniques", []))
    if apply_line:
        parts.append(apply_line)
    specialty_block = _format_specialty_block(response.get("specialty_testing_needs", []))
    if specialty_block:
        parts.append(specialty_block)
    missing = response.get("missing_information", [])[:2]
    if missing:
        parts.append("Need: " + "; ".join(missing))
    return "\n\n".join(p for p in parts if p)


def _render_question(response: dict[str, Any]) -> str:
    parts: list[str] = [_format_approach_line(response.get("recommended_approach", {}))]
    answer = response.get("answer", {}) or {}
    short = answer.get("short_answer", "")
    if short:
        parts.append(short)
    verify = answer.get("verify", [])[:5]
    if verify:
        parts.append("Verify:\n" + "\n".join(f"- {item}" for item in verify))
    risks_block = _format_risks(response.get("top_risks", [])[:2])
    if risks_block:
        parts.append(risks_block)
    apply_line = _format_apply_line(response.get("test_design_techniques", []))
    if apply_line:
        parts.append(apply_line)
    specialty_block = _format_specialty_block(response.get("specialty_testing_needs", []))
    if specialty_block:
        parts.append(specialty_block)
    missing = response.get("missing_information", [])[:2]
    if missing:
        parts.append("Need: " + "; ".join(missing))
    return "\n\n".join(p for p in parts if p)


def _render_test_plan(response: dict[str, Any]) -> str:
    parts: list[str] = [
        _format_approach_line(response.get("recommended_approach", {})),
        response.get("headline", ""),
    ]
    plan = response.get("test_plan", {}) or {}

    scope_in = plan.get("scope_in", [])[:4]
    if scope_in:
        parts.append("In scope:\n" + "\n".join(f"- {item}" for item in scope_in))

    entry = plan.get("entry_criteria", [])[:3]
    if entry:
        parts.append("Entry:\n" + "\n".join(f"- {item}" for item in entry))

    phases = plan.get("phases", [])
    if phases:
        phase_lines: list[str] = ["Phases:"]
        for phase in phases:
            name = phase.get("name", "")
            purpose = phase.get("purpose", "")
            deliverables = phase.get("deliverables", [])[:2]
            phase_lines.append(f"- {name} - {purpose}")
            for deliverable in deliverables:
                phase_lines.append(f"  * {deliverable}")
        parts.append("\n".join(phase_lines))

    exit_criteria = plan.get("exit_criteria", [])[:4]
    if exit_criteria:
        parts.append("Exit:\n" + "\n".join(f"- {item}" for item in exit_criteria))

    specialty_block = _format_specialty_block(response.get("specialty_testing_needs", []))
    if specialty_block:
        parts.append(specialty_block)

    open_qs = plan.get("open_questions", [])[:2]
    if open_qs:
        parts.append("Open questions:\n" + "\n".join(f"- {q}" for q in open_qs))

    return "\n\n".join(p for p in parts if p)


def _render_decide_approach(response: dict[str, Any]) -> str:
    decision = response.get("recommended_approach", {}) or {}
    parts: list[str] = [_format_approach_line(decision)]
    rationale = decision.get("rationale")
    if rationale:
        parts.append(f"Why: {rationale}")
    follow_up = decision.get("follow_up")
    if follow_up:
        parts.append(f"Then: {follow_up}")
    alternatives = decision.get("alternatives", [])[:2]
    if alternatives:
        lines = ["Alternatives:"]
        for alt in alternatives:
            lines.append(f"- {alt.get('approach', '')} - {alt.get('when', '')}")
        parts.append("\n".join(lines))
    return "\n\n".join(p for p in parts if p)


def _render_scaffold(response: dict[str, Any]) -> str:
    parts: list[str] = [
        _format_approach_line(response.get("recommended_approach", {})),
        response.get("headline", ""),
    ]
    tasks = response.get("tasks", []) or []
    if tasks:
        lines = ["Tasks:"]
        for task in tasks:
            level = task.get("level", "")
            tid = task.get("id", "")
            path = task.get("file_path", "")
            framework = task.get("framework", "")
            n_assertions = len(task.get("assertions", []))
            specialty = task.get("specialty")
            tag = f" [specialty: {specialty}]" if specialty else ""
            lines.append(
                f"- [{level}] {tid} {path} ({framework}, {n_assertions} assertions){tag}"
            )
        parts.append("\n".join(lines))
    order = response.get("execution_order", []) or []
    if order:
        parts.append("Order: " + " -> ".join(order))
    specialty_block = _format_specialty_block(response.get("specialty_testing_needs", []))
    if specialty_block:
        parts.append(specialty_block)
    missing = response.get("missing_information", [])[:2]
    if missing:
        parts.append("Need: " + "; ".join(missing))
    if tasks:
        first = tasks[0]
        parts.append(
            f"Confirm to start: write {first['id']} ({first['file_path']}) - "
            f"verify with `{first['verify_command']}`. The skeleton is in `tasks[0].skeleton`."
        )
    return "\n\n".join(p for p in parts if p)


def _format_approach_line(decision: dict[str, Any]) -> str:
    if not decision:
        return ""
    approach = decision.get("approach", "")
    confidence = decision.get("confidence", "")
    next_action = decision.get("next_action") or {}
    next_tool = next_action.get("tool") if isinstance(next_action, dict) else None
    suffix = f" -> next: {next_tool}" if next_tool else " -> next: (no tool)"
    confidence_part = f" ({confidence} confidence)" if confidence else ""
    return f"APPROACH: {approach}{confidence_part}{suffix}"


def _format_apply_line(techniques: list[str]) -> str:
    items = [t for t in techniques[:2] if t]
    if not items:
        return ""
    return "Apply: " + "; ".join(items)


def _format_specialty_block(needs: list[dict[str, Any]]) -> str:
    """Render up to 2 specialty-routing recommendations as a 'Pull in:' block."""
    if not needs:
        return ""
    lines = ["Pull in:"]
    for entry in needs[:2]:
        approach = entry.get("approach", "")
        tools = entry.get("well_known_tools", []) or []
        tools_text = ", ".join(tools[:3])
        lines.append(f"- {approach} (e.g. {tools_text})")
    return "\n".join(lines)


def _format_risks(risks: list[dict[str, Any]]) -> str:
    if not risks:
        return ""
    lines: list[str] = ["Risks:"]
    for risk in risks:
        severity = risk.get("severity", "medium")
        category = risk.get("category", "")
        description = _shorten(risk.get("description", ""), 18)
        lines.append(f"- [{severity}] {category} - {description}")
    return "\n".join(lines)


def _format_findings(findings: list[dict[str, Any]]) -> str:
    if not findings:
        return ""
    lines: list[str] = ["Findings:"]
    for finding in findings:
        severity = finding.get("severity", "medium")
        text = _shorten(finding.get("finding", ""), 22)
        path = finding.get("recommended_test_path")
        suffix = f" ({path})" if path else ""
        lines.append(f"- [{severity}] {text}{suffix}")
    return "\n".join(lines)


def _format_flat_tests(suggested: dict[str, list[str]], limit: int) -> str:
    if not suggested:
        return ""
    flat: list[str] = []
    # Iterate in the same order sumo_qa.models.SuggestedTests.flatten() uses.
    for level in ("unit", "integration", "contract", "functional", "nonfunctional"):
        for item in suggested.get(level, []):
            flat.append(item)
            if len(flat) >= limit:
                break
        if len(flat) >= limit:
            break
    if not flat:
        return ""
    lines = ["Tests:"]
    for item in flat:
        lines.append(f"- {_shorten(item, 18)}")
    return "\n".join(lines)


def _shorten(text: str, max_words: int) -> str:
    """Shorten a single field's text at a clause or word boundary - no ellipsis.

    Bullets are visibly summaries; an ellipsis is noise. We prefer cutting at
    a sentence/clause boundary; otherwise we cut cleanly at a word boundary.
    """
    words = text.split()
    if len(words) <= max_words:
        return text
    # Try to cut at the nearest sentence/clause boundary near the target.
    head = " ".join(words[: max_words * 2])
    for terminator in (". ", "; ", " - ", ": "):
        idx = head.find(terminator, 0, _approx_chars(max_words))
        if idx > 0:
            return head[: idx + 1].rstrip()
    # Clean word-boundary cut, no ellipsis.
    return " ".join(words[:max_words]).rstrip(",;.:")


def _approx_chars(words: int) -> int:
    return words * 7  # rough average word length plus space
