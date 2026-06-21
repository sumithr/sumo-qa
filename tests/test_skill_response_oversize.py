# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Over-cap skill-response contract (#393).

A full-body skill response that exceeds the host's per-response token cap is
refused by the host ("result … exceeds maximum allowed tokens") and saved to a
file instead of loaded inline — so the canonical load fails opaquely. The
largest skill, ``sumo-qa-reviewing-before-merge`` (~17.8k est. tokens), is the
first to cross that wall.

Both full-body entry paths must instead detect the over-cap body and return a
compact, actionable pointer to the progressive-loading slices
(``sumo_qa_load_skill_context`` manifest / section / module) WITHOUT returning
the oversized content:

  * the per-skill zero-argument tool (``skill_prompts._make_skill_callable``);
  * ``skill_manifest.load_skill_context(mode="full")``.

Under-cap skills MUST keep returning the body byte-for-byte (the existing
contract is unchanged for them).

Discipline:
  * decision tables — the served response is a conjunction of
    (entry path) × (body est-tokens vs cap); each combination pins one output.
  * boundary value analysis — the cap comparison is strict ``>``: a body at
    exactly the cap stays full; one est-token over degrades to a pointer.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sumo_qa import skill_manifest as sm
from sumo_qa import skill_prompts
from sumo_qa.skill_prompts import (
    DEFAULT_SKILL_RESPONSE_TOKEN_CAP,
    _approx_tokens,
    _make_skill_callable,
    _response_token_cap,
)

# Route names the pointer MUST mention so the host can navigate
# progressive-loading without the oversized body.
_ROUTE_TOKENS = ("sumo_qa_load_skill_context", "manifest", "section", "module")


def _write_skill(skill_dir: Path, body: str) -> Path:
    """Write a SKILL.md of *body* under *skill_dir* and return its path."""
    skill_dir.mkdir(parents=True, exist_ok=True)
    path = skill_dir / "SKILL.md"
    path.write_text(body, encoding="utf-8")
    return path


# --------------------------------------------------------------------------
# _response_token_cap resolution: explicit override > env var > default
# (decision table over (override?, env present?, env valid+positive?))
# --------------------------------------------------------------------------


def test_cap_default_when_no_override_and_no_env(monkeypatch):
    monkeypatch.delenv("SUMO_QA_SKILL_RESPONSE_TOKEN_CAP", raising=False)
    assert _response_token_cap() == DEFAULT_SKILL_RESPONSE_TOKEN_CAP


def test_cap_explicit_override_wins_over_env(monkeypatch):
    monkeypatch.setenv("SUMO_QA_SKILL_RESPONSE_TOKEN_CAP", "9999")
    assert _response_token_cap(123) == 123


def test_cap_env_overrides_default(monkeypatch):
    monkeypatch.setenv("SUMO_QA_SKILL_RESPONSE_TOKEN_CAP", "4321")
    assert _response_token_cap() == 4321


@pytest.mark.parametrize("bad", ["", "abc", "0", "-50", "12.5"])
def test_cap_garbage_or_nonpositive_env_falls_back_to_default(monkeypatch, bad):
    # A misconfigured host cannot disable the guard with a non-integer or
    # non-positive value — it falls back to the documented default.
    monkeypatch.setenv("SUMO_QA_SKILL_RESPONSE_TOKEN_CAP", bad)
    assert _response_token_cap() == DEFAULT_SKILL_RESPONSE_TOKEN_CAP


# --------------------------------------------------------------------------
# Per-skill tool body (skill_prompts._make_skill_callable) — boundary
# --------------------------------------------------------------------------


def test_per_skill_tool_at_cap_returns_body_byte_for_byte(tmp_path):
    # boundary: tokens == cap is NOT over (strict >). Body returned unchanged.
    body = "# sumo-qa-fake\n\n" + ("word body line\n" * 40)
    path = _write_skill(tmp_path / "sumo-qa-fake", body)
    tokens = _approx_tokens(body)
    out = _make_skill_callable(path, token_cap=tokens)()
    assert out == body


def test_per_skill_tool_one_token_over_cap_returns_pointer(tmp_path):
    # boundary: tokens == cap + 1 IS over. A pointer replaces the body.
    body = "# sumo-qa-fake\n\n" + ("word body line\n" * 40)
    path = _write_skill(tmp_path / "sumo-qa-fake", body)
    tokens = _approx_tokens(body)
    out = _make_skill_callable(path, token_cap=tokens - 1)()
    assert out != body
    assert body not in out  # the oversized content is NOT returned
    assert "sumo-qa-fake" in out  # names the skill
    for token in _ROUTE_TOKENS:  # names the progressive-loading route
        assert token in out, f"pointer missing route token {token!r}"


def test_per_skill_tool_pointer_is_smaller_than_a_realistic_cap(tmp_path):
    # The pointer is a compact constant — under any realistic host cap, so it
    # never itself trips the wall it exists to route around.
    body = "# sumo-qa-fake\n\n" + ("filler line of text\n" * 200)
    path = _write_skill(tmp_path / "sumo-qa-fake", body)
    out = _make_skill_callable(path, token_cap=DEFAULT_SKILL_RESPONSE_TOKEN_CAP)()
    # body is far under the default cap here, so confirm the SUBJECT first:
    big = "x" * (DEFAULT_SKILL_RESPONSE_TOKEN_CAP * 4 + 4)
    big_path = _write_skill(tmp_path / "sumo-qa-big", "# sumo-qa-big\n" + big)
    pointer = _make_skill_callable(big_path)()
    assert _approx_tokens(pointer) <= DEFAULT_SKILL_RESPONSE_TOKEN_CAP
    # the small one is returned in full (sanity that the helper isn't a no-op)
    assert out.endswith("filler line of text\n")


# --------------------------------------------------------------------------
# Loader mode="full" (skill_manifest.load_skill_context) — boundary
# --------------------------------------------------------------------------


def _fake_skill_with_sections(monkeypatch, tmp_path, body: str | None = None) -> str:
    name = "sumo-qa-fake"
    body = body or (
        "---\nname: sumo-qa-fake\ndescription: d\n---\n\n"
        "# Title\n\n## The Iron Law\n\nbody one\n\n## Checklist\n\nbody two\n"
    )
    _write_skill(tmp_path / name, body)
    monkeypatch.setattr(sm, "_skills_dir", lambda: tmp_path)
    return name


def test_loader_full_at_cap_returns_body(monkeypatch, tmp_path):
    name = _fake_skill_with_sections(monkeypatch, tmp_path)
    body = (tmp_path / name / "SKILL.md").read_text(encoding="utf-8")
    out = sm.load_skill_context(name, "full", token_cap=_approx_tokens(body))
    assert out["mode"] == "full"
    assert out["content"] == body
    assert "oversize" not in out


def test_loader_full_over_cap_returns_pointer_envelope_without_body(monkeypatch, tmp_path):
    name = _fake_skill_with_sections(monkeypatch, tmp_path)
    body = (tmp_path / name / "SKILL.md").read_text(encoding="utf-8")
    out = sm.load_skill_context(name, "full", token_cap=_approx_tokens(body) - 1)
    assert out["mode"] == "full"
    assert out["oversize"] is True
    assert "content" not in out  # the oversized body is NOT returned
    # names the progressive-loading route, actionably
    assert out["available_modes"] == ["manifest", "section", "module"]
    assert [s["id"] for s in out["sections"]]  # the section index is carried
    assert out["estimated_tokens_full"] == _approx_tokens(body)
    assert out["token_cap"] == _approx_tokens(body) - 1
    assert len(out["content_hash"]) == 64  # change-detection parity preserved
    assert "load_skill_context" in out["error"]


def test_loader_full_pointer_sections_carry_only_public_fields(monkeypatch, tmp_path):
    name = _fake_skill_with_sections(monkeypatch, tmp_path)
    body = (tmp_path / name / "SKILL.md").read_text(encoding="utf-8")
    out = sm.load_skill_context(name, "full", token_cap=_approx_tokens(body) - 1)
    for section in out["sections"]:
        assert "_text" not in section
        assert set(section) == {"id", "heading", "level", "estimated_tokens", "required"}


def test_loader_full_over_cap_honours_known_hash(monkeypatch, tmp_path):
    # The known_hash change-detection affordance still applies on the over-cap
    # path: a match reports changed=False, a mismatch changed=True, and the
    # oversized body is NEVER returned either way (only ever a pointer).
    name = _fake_skill_with_sections(monkeypatch, tmp_path)
    body = (tmp_path / name / "SKILL.md").read_text(encoding="utf-8")
    cap = _approx_tokens(body) - 1
    live_hash = sm.load_skill_context(name, "full", token_cap=cap)["content_hash"]
    matched = sm.load_skill_context(name, "full", token_cap=cap, known_hash=live_hash)
    assert matched["oversize"] is True
    assert matched["changed"] is False
    assert "content" not in matched
    mismatched = sm.load_skill_context(name, "full", token_cap=cap, known_hash="nope")
    assert mismatched["oversize"] is True
    assert mismatched["changed"] is True
    assert "content" not in mismatched


def test_loader_full_over_cap_without_known_hash_has_no_changed_flag(monkeypatch, tmp_path):
    # No known_hash (the default) → no `changed` field, matching the no-cache
    # default of the normal full slice.
    name = _fake_skill_with_sections(monkeypatch, tmp_path)
    body = (tmp_path / name / "SKILL.md").read_text(encoding="utf-8")
    out = sm.load_skill_context(name, "full", token_cap=_approx_tokens(body) - 1)
    assert out["oversize"] is True
    assert "changed" not in out


# --------------------------------------------------------------------------
# AC guard (#393): at the REAL default cap, NO served full-body response
# exceeds the cap — every bundled skill is byte-identical (under) OR a
# graceful pointer (over). Covers BOTH entry paths over the real library.
# --------------------------------------------------------------------------


def _bundled_skill_paths() -> list[Path]:
    skills_dir = skill_prompts._skills_dir()
    return sorted(
        d / "SKILL.md" for d in skills_dir.iterdir() if d.is_dir() and (d / "SKILL.md").is_file()
    )


def test_no_served_full_body_exceeds_the_default_cap():
    cap = DEFAULT_SKILL_RESPONSE_TOKEN_CAP
    over, under = [], []
    for path in _bundled_skill_paths():
        name = path.parent.name
        body = path.read_text(encoding="utf-8")
        tool_body = _make_skill_callable(path)()
        loaded = sm.load_skill_context(name, "full")
        if _approx_tokens(body) > cap:
            over.append(name)
            # per-skill tool: pointer, not the body, naming the route, under cap
            assert tool_body != body
            assert body not in tool_body
            assert _approx_tokens(tool_body) <= cap
            for token in _ROUTE_TOKENS:
                assert token in tool_body, f"{name} tool pointer missing {token!r}"
            # loader: oversize pointer, body omitted, route named
            assert loaded.get("oversize") is True
            assert "content" not in loaded
            assert loaded["available_modes"] == ["manifest", "section", "module"]
        else:
            under.append(name)
            assert tool_body == body  # byte-for-byte preserved
            assert loaded["content"] == body
    assert over, (
        "no bundled skill exceeds the default response cap; the over-cap guard "
        "has no subject — revisit DEFAULT_SKILL_RESPONSE_TOKEN_CAP."
    )
    assert under, "expected most skills to stay under the cap (byte-identical)"


def test_reviewing_before_merge_is_the_over_cap_skill():
    # The concrete subject this issue was filed about: the heaviest skill must
    # degrade rather than return an over-cap body the host refuses.
    name = "sumo-qa-reviewing-before-merge"
    path = skill_prompts._skills_dir() / name / "SKILL.md"
    assert path.is_file()
    body = path.read_text(encoding="utf-8")
    assert _approx_tokens(body) > DEFAULT_SKILL_RESPONSE_TOKEN_CAP
    tool_body = _make_skill_callable(path)()
    assert body not in tool_body
    loaded = sm.load_skill_context(name, "full")
    assert loaded.get("oversize") is True
    assert "content" not in loaded
