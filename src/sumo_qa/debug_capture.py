"""Optional debug capture for the live MCP server.

When `SUMO_QA_DEBUG_DIR` is set, every tool invocation writes its
input + output to a timestamped folder under that directory. This is
for the user's manual review during the FINAL verification round —
not used during the inner iteration loop (subagents grade in their
own context).
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any


def maybe_capture(*, tool: str, args: dict[str, Any], output: dict[str, Any]) -> dict[str, Any]:
    """Persist the tool exchange when SUMO_QA_DEBUG_DIR is set; passthrough always.

    Returns the `output` dict unchanged so callers can wrap returns
    inline: `return maybe_capture(tool=..., args=..., output=...)`.
    """
    debug_dir = os.environ.get("SUMO_QA_DEBUG_DIR")
    if not debug_dir:
        return output
    try:
        base = Path(debug_dir)
        base.mkdir(parents=True, exist_ok=True)
        ts = time.strftime("%Y%m%d-%H%M%S")
        run_dir = base / f"{ts}-{tool}"
        i = 1
        while run_dir.exists():
            run_dir = base / f"{ts}-{tool}-{i}"
            i += 1
        run_dir.mkdir()
        (run_dir / "input.json").write_text(json.dumps(args, indent=2, default=str))
        (run_dir / "output.json").write_text(json.dumps(output, indent=2, default=str))
        (run_dir / "trace.md").write_text(_render_trace(tool, args, output))
    except Exception:  # noqa: BLE001 — debug capture must never break the tool
        pass
    return output


def _render_trace(tool: str, args: dict[str, Any], output: dict[str, Any]) -> str:
    return (
        f"# {tool}\n\n"
        f"## Input\n\n```json\n{json.dumps(args, indent=2, default=str)}\n```\n\n"
        f"## Output\n\n```json\n{json.dumps(output, indent=2, default=str)}\n```\n"
    )
