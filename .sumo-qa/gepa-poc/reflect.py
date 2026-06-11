"""claude -p reflection wrapper. Prepends the writing-skills authoring standard to every
prompt GEPA composes. RUBRIC-PROPOSAL lines are logged to proposals.md, never applied."""

import subprocess
import time
from pathlib import Path
from typing import Any

_WS = Path.home() / (
    ".claude/plugins/cache/claude-plugins-official/superpowers/5.1.0/skills/writing-skills"
)
STANDARD = (
    (_WS / "SKILL.md").read_text(encoding="utf-8")
    + "\n\n"
    + (_WS / "anthropic-best-practices.md").read_text(encoding="utf-8")
)
PROPOSALS = Path(__file__).resolve().parent / "proposals.md"

PREAMBLE = f"""You are improving a SKILL.md for an LLM agent. Conform to this authoring \
standard when writing any skill text:
<authoring-standard>
{STANDARD}
</authoring-standard>
Compression objective: preserve EVERY behavioural rule, trigger phrase, named check, gate \
and verdict format; cut redundancy, duplicated dogfooding patches, repetition and filler \
prose. Shorter is better ONLY when no behaviour is lost.
You MUST NOT propose changes to eval rubrics or test YAML. If you believe a rubric should \
be TIGHTENED, emit a single line starting with 'RUBRIC-PROPOSAL:' describing it, outside \
any code fence.
"""


def _flatten(prompt: str | list[dict[str, Any]]) -> str:
    if isinstance(prompt, str):
        return prompt
    return "\n\n".join(str(m.get("content", "")) for m in prompt)


def _looks_like_skill(text: str) -> bool:
    """The response must contain an actual SKILL.md — frontmatter-led, substantial —
    either as the whole response or inside a fenced block. Catches the observed failure
    where claude returns a task BRIEF about rewriting instead of the rewrite itself."""
    import re

    candidates = [text.strip()]
    candidates += [m.strip() for m in re.findall(r"```(?:markdown|md)?\n(.*?)```", text, re.S)]
    return any(
        c.startswith("---") and "description:" in c[:2000] and len(c) > 2000 for c in candidates
    )


CORRECTIVE = (
    "\n\nIMPORTANT: Output the COMPLETE revised SKILL.md document ITSELF — not a "
    "task description, not a plan, not commentary about rewriting. Exactly one "
    "```markdown fence containing the full SKILL.md, starting with `---` "
    "frontmatter."
)
FAILLOG = Path(__file__).resolve().parent / "reflect-failures.log"


def _call_claude(full: str) -> str | None:
    proc = subprocess.run(
        ["claude", "-p", "--output-format", "text"],
        input=full,
        capture_output=True,
        text=True,
        timeout=1800,
    )
    text = proc.stdout.strip()
    return text if proc.returncode == 0 and text else None


def _wait_for_claude(max_wait_s: int = 8 * 3600) -> None:
    """Usage-limit outage must PAUSE the loop, not bleed it: overnight 2026-06-11 a quota
    hit made every reflection fail and gepa burned all 20 metric calls proposing nothing.
    Block here (cheap ping every 10 min) until claude answers again."""
    waited = 0
    while waited < max_wait_s:
        if _call_claude("reply with exactly: OK") is not None:
            return
        with FAILLOG.open("a") as fh:
            fh.write(f"--- claude unavailable (quota?); waited {waited}s, retrying in 600s\n")
        time.sleep(600)
        waited += 600
    raise RuntimeError(f"claude -p unavailable for {max_wait_s}s — giving up")


def reflection_lm(prompt: str | list[dict[str, Any]]) -> str:
    base = PREAMBLE + "\n\n" + _flatten(prompt)
    full = base
    last_text = None
    for attempt in (1, 2, 3):
        text = _call_claude(full)
        if text is None:
            _wait_for_claude()  # blocks through quota outages; raises only after 8h
            text = _call_claude(full)
        if text is None:
            time.sleep(10)
            continue
        last_text = text
        for line in text.splitlines():
            if line.startswith("RUBRIC-PROPOSAL:"):
                with PROPOSALS.open("a") as fh:
                    fh.write(line + "\n")
        if _looks_like_skill(text):
            return text
        with FAILLOG.open("a") as fh:
            fh.write(f"--- attempt {attempt}: non-skill response head: {text[:200]!r}\n")
        full = base + CORRECTIVE  # retry with the explicit output contract
    if last_text is not None:
        return last_text  # gepa's shape floor rejects it; wastes one rollout, no crash
    raise RuntimeError("claude -p failed every attempt")
