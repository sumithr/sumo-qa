# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Deterministic context-cost audit: what sumo-qa puts in a host's context.

Measures, with the repository's canonical estimator
(``sumo_qa.skill_manifest._approx_tokens``, ``(chars + 3) // 4``):

* **bootstrap**: the SessionStart ``additionalContext`` the real hook emits on
  a healthy Claude Code session (compact path), plus the full-router fallback
  for reference, with the plugin root replaced by a fixed stand-in path;
* **tools/list**: the compact JSON of every advertised MCP tool, once per
  profile (``core`` and ``full``, from ``sumo_qa.tool_registry``), plus one
  report-only row per capability group (tool count, how many are core, and the
  description vs name/schema/annotations split) so a regression is attributable;
* **root skills**: every ``skills/*/SKILL.md``;
* **workflows**: the MCP tool results a routed skill loads, through the real
  server's ``call_tool``. Each workflow is reported twice: the per-loader
  chain (classifications, standards, rules, one call per module) and the
  bundled path (one ``sumo_qa_load_skill_context(mode="bundle")`` call), with
  call counts and a re-sent estimate (an agent loop re-sends every earlier
  result on each later turn, so N results cost the sum of their prefixes).
  The workflows run on the ``core`` server, so every audited workflow is
  proven to run under ``core``;
* **end-to-end**: per workflow and profile, the model-visible total of one
  bundled run: compact bootstrap + that profile's tools/list + the results,
  with the bootstrap and tools/list riding every turn in the re-sent figure.

Budgets live in ``[tool.sumo-qa.context-budget]`` in pyproject.toml. A budget
that is absent is report-only. Exit 1 when any configured budget is exceeded.

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
from unittest import mock

from mcp.server.mcpserver.exceptions import ToolError

from sumo_qa.skill_manifest import _approx_tokens as approx_tokens
from sumo_qa.tool_registry import PROFILE_ENV, PROFILES, TOOLS

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


def resent_tokens(sizes: list[int]) -> int:
    """Tokens an agent loop re-sends: result i rides along on every later turn."""
    return sum(size * (len(sizes) - i) for i, size in enumerate(sizes))


# The compact bootstrap names the router by absolute path; measuring it with a
# fixed stand-in keeps the count independent of where the repo is cloned.
STAND_IN_ROOT = "/path/to/sumo-qa"


def measure_bootstrap(repo: Path, mode: str) -> str:
    """Run the real SessionStart hook as Claude Code would, with uvx on PATH,
    and return its context with the plugin root replaced by ``STAND_IN_ROOT``."""
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
    context = json.loads(out)["hookSpecificOutput"]["additionalContext"]
    # The hook may print the root as given or, on Windows, in its `cygpath -m`
    # (forward-slash) form; both stand in for the same root.
    return context.replace(str(repo), STAND_IN_ROOT).replace(repo.as_posix(), STAND_IN_ROOT)


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


def _compact(value: Any) -> str:
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False)


def _run(server: Any, calls: list[tuple[str, dict[str, Any]]], profile: str) -> list[str]:
    """Run ``calls`` on ``server``; a tool the profile does not serve raises
    ``LookupError`` naming the tool and the profile."""
    texts = []
    for name, args in calls:
        try:
            texts.append(_text(asyncio.run(server.call_tool(name, args))))
        except ToolError as exc:
            raise LookupError(f"tool {name} failed under profile {profile}: {exc}") from exc
    return texts


def validate_tools_list(budgets: Any) -> None:
    """Raise ``ValueError`` unless ``tools_list`` maps registry profiles to budgets."""
    if not isinstance(budgets, dict):
        raise ValueError(
            "context-budget tools_list must be a table keyed by profile "
            f"({', '.join(PROFILES)}), got {type(budgets).__name__}"
        )
    unknown = sorted(set(budgets) - set(PROFILES))
    if unknown:
        raise ValueError(
            f"context-budget tools_list names unknown profile(s) {', '.join(unknown)}; "
            f"valid profiles: {', '.join(PROFILES)}"
        )


def _check_bundle(wf: dict[str, Any], text: str, failures: list[str], profile: str = "") -> None:
    bundle = json.loads(text)
    if "error" in bundle:
        where = f" ({profile})" if profile else ""
        failures.append(f"workflow {wf['name']}{where}: bundle failed: {bundle['error']}")


def audit(config: dict[str, Any], repo: Path = REPO) -> tuple[list[dict[str, Any]], list[str]]:
    """Return (rows, failures). Each row: area, name, chars, tokens, budget."""
    from sumo_qa.server import build_mcp_server

    servers = {}
    for profile in PROFILES:
        with mock.patch.dict(os.environ, {PROFILE_ENV: profile}):
            servers[profile] = build_mcp_server()
    rows: list[dict[str, Any]] = []

    def row(area: str, name: str, text: str, budget: int | None = None, **extra: Any) -> None:
        tokens = approx_tokens(text)
        rows.append(
            {"area": area, "name": name, "chars": len(text), "tokens": tokens, "budget": budget}
            | extra
        )

    bootstrap = measure_bootstrap(repo, "compact")
    row("bootstrap", "compact (default)", bootstrap, config.get("bootstrap"))
    row("bootstrap", "full fallback", measure_bootstrap(repo, "full"))

    list_budgets = config.get("tools_list", {})
    validate_tools_list(list_budgets)
    tools_json: dict[str, str] = {}
    entries: dict[str, list[dict[str, Any]]] = {}
    for profile, server in servers.items():
        tools = asyncio.run(server.list_tools())
        entries[profile] = [
            t.model_dump(mode="json", by_alias=True, exclude_none=True) for t in tools
        ]
        tools_json[profile] = _compact(entries[profile])
        row(
            "tools/list",
            f"{profile}: {len(tools)} tools",
            tools_json[profile],
            list_budgets.get(profile),
            profile=profile,
        )
    by_name = {e["name"]: e for e in entries["full"]}
    meta = {t.name: t for t in TOOLS}
    for group in dict.fromkeys(t.group for t in TOOLS):
        members = [meta[n] for n in by_name if n in meta and meta[n].group == group]
        group_entries = [by_name[t.name] for t in members]
        core = sum(t.core for t in members)
        row(
            "tool group",
            f"{group}: {len(members)} tools ({core} core)",
            _compact(group_entries),
            group=group,
            tools=len(members),
            core=core,
            desc=sum(approx_tokens(e.get("description", "")) for e in group_entries),
            schema=sum(
                approx_tokens(_compact({k: v for k, v in e.items() if k != "description"}))
                for e in group_entries
            ),
        )

    for path in sorted((repo / "skills").glob("*/SKILL.md")):
        row(
            "root skill",
            path.parent.name,
            path.read_text(encoding="utf-8"),
            config.get("root_skill"),
        )

    failures: list[str] = []
    for wf in config.get("workflow", []):
        try:
            for bundled in (False, True):
                texts = _run(servers["core"], _workflow_calls(wf, bundled), "core")
                if bundled:
                    _check_bundle(wf, texts[-1], failures)
                    row("bundle", wf["name"], texts[-1], wf.get("bundle"))
                sizes = [approx_tokens(t) for t in texts]
                row(
                    "workflow",
                    f"{wf['name']} ({'bundled' if bundled else 'per-loader'})",
                    "".join(texts),
                    calls=len(texts),
                    resent=resent_tokens(sizes),
                )
            for profile, server in servers.items():
                prefix = bootstrap + tools_json[profile]
                texts = _run(server, _workflow_calls(wf, bundled=True), profile)
                _check_bundle(wf, texts[-1], failures, profile)
                row(
                    "end-to-end",
                    f"{wf['name']} ({profile})",
                    prefix + "".join(texts),
                    workflow=wf["name"],
                    profile=profile,
                    calls=len(texts),
                    resent=resent_tokens([approx_tokens(t) for t in (prefix, *texts)]),
                )
        except LookupError as exc:
            failures.append(f"workflow {wf['name']}: {exc}")

    failures += [
        f"{r['area']} {r['name']}: ~{r['tokens']} est. tokens > budget {r['budget']}"
        for r in rows
        if r["budget"] is not None and r["tokens"] > r["budget"]
    ]
    return rows, failures


def render(rows: list[dict[str, Any]]) -> str:
    lines = [
        f"{'area':<11} {'name':<52} {'chars':>7} {'tokens':>7} {'budget':>7} {'calls':>5} "
        f"{'re-sent':>8} {'desc':>5} {'schema':>6}"
    ]
    for r in rows:
        budget = "-" if r["budget"] is None else str(r["budget"])
        over = " OVER" if r["budget"] is not None and r["tokens"] > r["budget"] else ""
        lines.append(
            f"{r['area']:<11} {r['name']:<52} {r['chars']:>7} {r['tokens']:>7} {budget:>7} "
            f"{r.get('calls', ''):>5} {r.get('resent', ''):>8} {r.get('desc', ''):>5} "
            f"{r.get('schema', ''):>6}{over}"
        )
    return "\n".join(lines)


def load_config(path: Path) -> dict[str, Any]:
    with path.open("rb") as fh:
        return tomllib.load(fh)["tool"]["sumo-qa"]["context-budget"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--config", type=Path, default=REPO / "pyproject.toml")
    args = parser.parse_args(argv)
    try:
        rows, failures = audit(load_config(args.config))
    except ValueError as exc:
        print(f"config error: {exc}", file=sys.stderr)
        return 2
    print(render(rows))
    for failure in failures:
        print(f"FAIL {failure}")
    print("context budget: FAILED" if failures else "context budget: OK")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
