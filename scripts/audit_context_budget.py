# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Deterministic context-cost audit: what sumo-qa puts in a host's context.

Measures, with the repository's canonical estimator (``(chars + 3) // 4``,
the one ``skill_manifest`` and the token-budget tests use):

* **bootstrap**: the SessionStart ``additionalContext`` the real hook emits on
  a healthy Claude Code session (compact path), plus the full-router fallback
  for reference;
* **tools/list**: the compact JSON of every advertised MCP tool;
* **root skills**: every ``skills/*/SKILL.md``;
* **workflows**: the MCP tool results a routed skill loads, through the real
  server's ``call_tool``. Each workflow is reported twice: the per-loader
  chain (classifications, standards, rules, one call per module) and the
  bundled path (one ``sumo_qa_load_skill_context(mode="bundle")`` call), with
  call counts and a re-sent estimate (an agent loop re-sends every earlier
  result on each later turn, so N results cost the sum of their prefixes).

Budgets live in ``[tool.sumo-qa.context-budget]`` in pyproject.toml. A budget
that is absent is report-only (the root-skill budget stays report-only until
#798 enforces it). Exit 1 when any configured budget is exceeded.

Usage::

    python scripts/audit_context_budget.py [--config PATH]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - 3.10 only
    import tomli as tomllib

REPO = Path(__file__).resolve().parents[1]
ROUTER_CALLS = (
    ("using_sumo_qa", {}),
    ("sumo_qa_deciding_approach", {}),
    ("sumo_qa_load_classifications", {}),
    ("sumo_qa_load_approaches", {}),
)


def approx_tokens(text: str) -> int:
    return (len(text) + 3) // 4


def resent_tokens(sizes: list[int]) -> int:
    """Tokens an agent loop re-sends: result i rides along on every later turn."""
    return sum(size * (len(sizes) - i) for i, size in enumerate(sizes))


def measure_bootstrap(repo: Path, mode: str) -> str:
    """Run the real SessionStart hook as Claude Code would, with uvx on PATH."""
    bash = shutil.which("bash")
    if bash is None:  # pragma: no cover - the audit runs where bash exists
        raise RuntimeError("bash is required to run hooks/session-start")
    with tempfile.TemporaryDirectory() as bindir:
        stub = Path(bindir) / "uvx"
        stub.write_text("#!/bin/sh\nexit 0\n")
        stub.chmod(0o755)
        env = {
            "HOME": os.environ.get("HOME", bindir),
            "PATH": f"{bindir}{os.pathsep}{os.environ.get('PATH', '')}",
            "CLAUDE_PLUGIN_ROOT": str(repo),
            "SUMO_QA_BOOTSTRAP": mode,
        }
        out = subprocess.run(
            [bash, str(repo / "hooks" / "session-start")],
            env=env,
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
        ).stdout
    return json.loads(out)["hookSpecificOutput"]["additionalContext"]


def _text(result: Any) -> str:
    content = getattr(result, "content", result)
    return "".join(getattr(block, "text", "") for block in content)


def _workflow_calls(wf: dict[str, Any], bundled: bool) -> list[tuple[str, dict[str, Any]]]:
    skill = wf["skill"]
    calls = [*ROUTER_CALLS, (skill.replace("-", "_"), {})]
    if bundled:
        bundle = {
            "skill_name": skill,
            "mode": "bundle",
            "classification": wf["classification"],
            "modules": wf.get("modules", ""),
            "include_body": False,
        }
        return [*calls, ("sumo_qa_load_skill_context", bundle)]
    calls += [
        ("sumo_qa_load_classifications", {}),
        ("sumo_qa_load_standards", {"classification": wf["classification"]}),
        ("sumo_qa_load_rules", {"classification": wf["classification"]}),
    ]
    for module in filter(None, wf.get("modules", "").split(",")):
        args = {"skill_name": skill, "mode": "module", "module": module.strip()}
        calls.append(("sumo_qa_load_skill_context", args))
    return calls


def audit(config: dict[str, Any], repo: Path = REPO) -> tuple[list[dict[str, Any]], list[str]]:
    """Return (rows, failures). Each row: area, name, chars, tokens, budget."""
    from sumo_qa.server import build_mcp_server

    server = build_mcp_server()
    rows: list[dict[str, Any]] = []

    def row(area: str, name: str, text: str, budget: int | None = None, **extra: Any) -> None:
        tokens = approx_tokens(text)
        rows.append(
            {"area": area, "name": name, "chars": len(text), "tokens": tokens, "budget": budget}
            | extra
        )

    row(
        "bootstrap",
        "compact (default)",
        measure_bootstrap(repo, "compact"),
        config.get("bootstrap"),
    )
    row("bootstrap", "full fallback", measure_bootstrap(repo, "full"))

    tools = asyncio.run(server.list_tools())
    dumped = [t.model_dump(mode="json", by_alias=True, exclude_none=True) for t in tools]
    tools_json = json.dumps(dumped, separators=(",", ":"), ensure_ascii=False)
    row("tools/list", f"{len(tools)} tools", tools_json, config.get("tools_list"))

    for path in sorted((repo / "skills").glob("*/SKILL.md")):
        row(
            "root skill",
            path.parent.name,
            path.read_text(encoding="utf-8"),
            config.get("root_skill"),
        )

    failures: list[str] = []
    for wf in config.get("workflow", []):
        for bundled in (False, True):
            texts = [
                _text(asyncio.run(server.call_tool(n, a))) for n, a in _workflow_calls(wf, bundled)
            ]
            if bundled:
                bundle = json.loads(texts[-1])
                if "error" in bundle:
                    failures.append(f"workflow {wf['name']}: bundle failed: {bundle['error']}")
                row("bundle", wf["name"], texts[-1], wf.get("bundle"))
            sizes = [approx_tokens(t) for t in texts]
            row(
                "workflow",
                f"{wf['name']} ({'bundled' if bundled else 'per-loader'})",
                "".join(texts),
                calls=len(texts),
                resent=resent_tokens(sizes),
            )

    failures += [
        f"{r['area']} {r['name']}: ~{r['tokens']} est. tokens > budget {r['budget']}"
        for r in rows
        if r["budget"] is not None and r["tokens"] > r["budget"]
    ]
    return rows, failures


def render(rows: list[dict[str, Any]]) -> str:
    lines = [
        f"{'area':<11} {'name':<52} {'chars':>7} {'tokens':>7} {'budget':>7} {'calls':>5} {'re-sent':>8}"
    ]
    for r in rows:
        budget = "-" if r["budget"] is None else str(r["budget"])
        over = " OVER" if r["budget"] is not None and r["tokens"] > r["budget"] else ""
        lines.append(
            f"{r['area']:<11} {r['name']:<52} {r['chars']:>7} {r['tokens']:>7} {budget:>7} "
            f"{r.get('calls', ''):>5} {r.get('resent', ''):>8}{over}"
        )
    return "\n".join(lines)


def load_config(path: Path) -> dict[str, Any]:
    with path.open("rb") as fh:
        return tomllib.load(fh)["tool"]["sumo-qa"]["context-budget"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--config", type=Path, default=REPO / "pyproject.toml")
    args = parser.parse_args(argv)
    rows, failures = audit(load_config(args.config))
    print(render(rows))
    for failure in failures:
        print(f"FAIL {failure}")
    print("context budget: FAILED" if failures else "context budget: OK")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
