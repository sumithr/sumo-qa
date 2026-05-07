"""Console entrypoint: invoke a QA tool, render it the way a sleek host should.

Lets the maintainer (or any user) iterate on the MCP without touching a real
host UI. Costs zero LLM tokens.

Usage:
  qa-shift-left-render prepare --work-item "add bundle variant validation"
  qa-shift-left-render review  --change-summary "Changed API payload" --touched-files src/orders/api.py
  qa-shift-left-render question --question "How do I test webhook retries?"

Output:
  - The rendered text a well-behaved MCP host would show the user.
  - The word count vs the cap.
  - On --raw, the underlying JSON for inspection.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from sumo_qa.render_preview import render_response
from sumo_qa.tools import QAShiftLeftService


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="qa-shift-left-render")
    parser.add_argument(
        "--standards-path",
        type=Path,
        default=None,
        help="Override the standards/packs directory (defaults to bundled or cwd).",
    )
    parser.add_argument(
        "--raw",
        action="store_true",
        help="Print the raw JSON response on stderr in addition to the rendered output on stdout.",
    )
    parser.add_argument(
        "--stats",
        action="store_true",
        help="Print word-count stats on stderr.",
    )
    sub = parser.add_subparsers(dest="tool", required=True)

    prepare = sub.add_parser("prepare", help="qa_prepare_for_work")
    prepare.add_argument("--work-item", required=True)
    prepare.add_argument("--acceptance-criteria", action="append", default=[])
    prepare.add_argument("--risk-notes", action="append", default=[])

    review = sub.add_parser("review", help="qa_review_local_change")
    review.add_argument("--change-summary", required=True)
    review.add_argument("--diff", default="")
    review.add_argument("--touched-files", action="append", default=[])
    review.add_argument("--test-evidence", action="append", default=[])

    question = sub.add_parser("question", help="qa_answer_testing_question")
    question.add_argument("--question", required=True)
    question.add_argument("--context", default="")

    testplan = sub.add_parser("testplan", help="qa_create_test_plan")
    testplan.add_argument("--work-item", required=True)
    testplan.add_argument("--scope-size", default="medium", choices=["small", "medium", "large"])
    testplan.add_argument("--acceptance-criteria", action="append", default=[])
    testplan.add_argument("--risk-notes", action="append", default=[])

    decide = sub.add_parser("decide", help="qa_decide_approach")
    decide.add_argument("--intent", required=True)
    decide.add_argument("--target-path", action="append", default=[], dest="target_paths")

    scaffold = sub.add_parser("scaffold", help="qa_scaffold_tests")
    scaffold.add_argument("--work-item", required=True)
    scaffold.add_argument("--test-condition", action="append", default=[], dest="test_conditions")
    scaffold.add_argument("--target-path", action="append", default=[], dest="target_paths")

    args = parser.parse_args(argv)

    service = _build_service(args.standards_path)
    response = _dispatch(service, args)
    rendered = render_response(response)

    # Stdout: only the rendered output a host would show the user.
    print(rendered)

    # Stderr: opt-in diagnostics for the maintainer iterating on hints.
    if args.stats:
        cap = response["presentation"]["max_words"]
        word_count = len(rendered.split())
        print(f"[stats] {word_count} words (soft target {cap})", file=sys.stderr)
    if args.raw:
        print(json.dumps(response, indent=2), file=sys.stderr)
    return 0


def _build_service(standards_path: Path | None) -> QAShiftLeftService:
    if standards_path is None:
        return QAShiftLeftService.from_standards_path()
    return QAShiftLeftService.from_standards_path(standards_path)


def _dispatch(service: QAShiftLeftService, args: argparse.Namespace) -> dict[str, Any]:
    if args.tool == "prepare":
        return service.qa_prepare_for_work(
            work_item=args.work_item,
            acceptance_criteria=args.acceptance_criteria or None,
            risk_notes=args.risk_notes or None,
        )
    if args.tool == "review":
        return service.qa_review_local_change(
            change_summary=args.change_summary,
            diff=args.diff or None,
            touched_files=args.touched_files or None,
            test_evidence=args.test_evidence or None,
        )
    if args.tool == "testplan":
        return service.qa_create_test_plan(
            work_item=args.work_item,
            scope_size=args.scope_size,
            acceptance_criteria=args.acceptance_criteria or None,
            risk_notes=args.risk_notes or None,
        )
    if args.tool == "decide":
        return service.qa_decide_approach(
            intent_text=args.intent,
            target_paths=args.target_paths or None,
        )
    if args.tool == "scaffold":
        return service.qa_scaffold_tests(
            work_item=args.work_item,
            test_conditions=args.test_conditions or None,
            target_paths=args.target_paths or None,
        )
    return service.qa_answer_testing_question(
        question=args.question,
        context=args.context or None,
    )


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
