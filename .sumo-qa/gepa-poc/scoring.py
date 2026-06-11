"""Candidate scoring: pass-rate minus token penalty; hard floors for .ab and shape."""

import tiktoken

ENC = tiktoken.get_encoding("o200k_base")
LAMBDA = 0.5  # token-pressure weight (spec: no reward below the 50% target)
TARGET_RATIO = 0.5


def token_count(text: str) -> int:
    return len(ENC.encode(text))


def shape_ok(text: str) -> bool:
    """Cheap malformed-candidate guard: must still look like a SKILL.md."""
    head = text[:2000]
    return text.strip().startswith("---") and "description:" in head and len(text) > 2000


class EnvironmentDrift(RuntimeError):
    """Ablation arms passed — the eval environment shifted; halt, don't blame the candidate."""


def ab_score(rows: list[dict]) -> float:
    """Graded lift signal from the .ab control (binary floor abandoned: at repeat=3 the
    CURRENT skill's B arm passes only 2/9 on this tier — not a stark control, so binary
    would zero the seed itself; per project doctrine, read lift not binary).
    Score = B-arm pass-rate (seed bar: 0.22). Ablation arms are candidate-INDEPENDENT —
    any ablation pass means environment drift: raise, never zero the candidate for it."""
    full = [r for r in rows if r.get("arm", "").startswith("B")]
    ablation = [r for r in rows if r.get("arm", "").startswith(("A0", "A1"))]
    abl_passes = sum(r["success"] for r in ablation)
    if abl_passes >= 2:
        raise EnvironmentDrift(
            f"{abl_passes} A0/A1 ablation rows PASSED — grades this round are suspect"
        )
    if abl_passes == 1:
        # Singleton = judge wobble at the measured ~3%/row base rate (1st seen 2026-06-11
        # 11:26 after ~36 clean rows) — log it, don't burn a watchdog life on noise.
        from pathlib import Path

        with (Path(__file__).resolve().parent / "drift-ledger.log").open("a") as fh:
            fh.write(
                "singleton ablation pass: "
                + "; ".join(r["arm"][:20] + "::" + r["desc"][:60] for r in ablation if r["success"])
                + "\n"
            )
    if not full:
        return 0.0
    return sum(r["success"] for r in full) / len(full)


def ab_floor_ok(rows: list[dict]) -> bool:
    """Report-only convenience (baseline.py): seed-bar check at the measured 2/9 = 0.22."""
    try:
        return ab_score(rows) >= 0.22
    except EnvironmentDrift:
        return False


def candidate_score(rows: list[dict], cand_tokens: int, seed_tokens: int) -> float:
    pass_rate = sum(r["success"] for r in rows) / max(len(rows), 1)
    penalty = LAMBDA * max(0.0, cand_tokens / seed_tokens - TARGET_RATIO)
    return max(0.0, pass_rate - penalty)
