# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Tests for sumo_qa.feedback_memory — explicit review-feedback memory.

Risk-anchored (issue #145):
- R1 sensitive-input rejection (equivalence partitioning: safe-summary vs
  raw-diff / secret / code-snippet / full-body classes).
- R2 required-field validation (decision tables: each required field present
  -> accept, absent -> reject).
- R3 advisory precedence — memory lands in its OWN feedback/ subdir, never a
  bundled knowledge/standards/rules tier, so it cannot shadow a canonical
  catalogue.
- R4 add/update/delete/list round-trip + atomic, scope-isolated writes (state
  transition testing: empty -> added -> updated -> deleted).
- R5 scope isolation (equivalence partitioning: project vs global).
"""

import datetime as dt

import pytest
import yaml

from sumo_qa import feedback_memory as fm
from sumo_qa import paths


def _good_entry(**over):
    base = {
        "scope": "billing service",
        "trigger_signal": "any change touching timezone boundaries in invoicing",
        "recommended_probe": "boundary value analysis on the day-rollover at 23:59 vs 00:00",
        "source_note": "we shipped two off-by-one-day invoice bugs in Q1",
    }
    base.update(over)
    return base


# --- R4: add/update/delete/list round-trip --------------------------------


def test_capture_then_list_round_trips(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    res = fm.capture_feedback(_good_entry(), scope="project")
    assert res["status"] == "captured"
    assert res["advisory"] is True
    listed = fm.list_feedback(scope="project")
    assert listed["count"] == 1
    only = listed["entries"][0]
    assert only["trigger_signal"] == _good_entry()["trigger_signal"]
    # The lesson's own scope field is preserved; the STORE is pack_scope.
    assert only["scope"] == _good_entry()["scope"]
    assert only["pack_scope"] == "project"
    assert only["advisory"] is True


def test_capture_persists_all_five_required_fields(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    fm.capture_feedback(_good_entry(), scope="project")
    stored = yaml.safe_load(paths.feedback_memory_path("project").read_text(encoding="utf-8"))
    entry = stored["entries"][0]
    for field in fm.REQUIRED_FIELDS:
        assert entry.get(field), f"required field {field} missing from stored entry"


def test_last_reviewed_defaults_to_now_when_omitted(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    res = fm.capture_feedback(_good_entry(), scope="project")
    ts = res["entry"]["last_reviewed"]
    # Round-trips as a real ISO-8601 instant (the bug: storing an empty/garbage
    # timestamp would not parse).
    parsed = dt.datetime.fromisoformat(ts.replace("Z", "+00:00"))
    assert parsed.year >= 2026


def test_last_reviewed_explicit_value_is_preserved(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    res = fm.capture_feedback(_good_entry(last_reviewed="2026-01-02T03:04:05Z"), scope="project")
    assert res["entry"]["last_reviewed"] == "2026-01-02T03:04:05Z"


def test_update_replaces_targeted_entry_only(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    a = fm.capture_feedback(_good_entry(trigger_signal="alpha lessons here"), scope="project")
    b = fm.capture_feedback(_good_entry(trigger_signal="beta lessons here"), scope="project")
    assert a["id"] != b["id"]
    fm.update_feedback(
        a["id"],
        _good_entry(trigger_signal="alpha revised", recommended_probe="new probe"),
        scope="project",
    )
    listed = {e["id"]: e for e in fm.list_feedback(scope="project")["entries"]}
    assert listed[a["id"]]["recommended_probe"] == "new probe"
    # The OTHER entry must be untouched — a clobber here is the data-loss bug.
    assert listed[b["id"]]["trigger_signal"] == "beta lessons here"


def test_update_unknown_id_raises(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(fm.FeedbackValidationError, match="no feedback entry with id"):
        fm.update_feedback("does-not-exist", _good_entry(), scope="project")


def test_delete_removes_only_targeted_entry(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    a = fm.capture_feedback(_good_entry(trigger_signal="alpha lessons here"), scope="project")
    b = fm.capture_feedback(_good_entry(trigger_signal="beta lessons here"), scope="project")
    res = fm.delete_feedback(a["id"], scope="project")
    assert res["status"] == "deleted"
    assert res["remaining"] == 1
    remaining_ids = [e["id"] for e in fm.list_feedback(scope="project")["entries"]]
    assert remaining_ids == [b["id"]]


def test_delete_unknown_id_raises(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    fm.capture_feedback(_good_entry(), scope="project")
    with pytest.raises(fm.FeedbackValidationError, match="nothing deleted"):
        fm.delete_feedback("nope", scope="project")


def test_capture_same_id_updates_in_place(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    first = fm.capture_feedback(_good_entry(), scope="project")
    again = fm.capture_feedback(
        {**_good_entry(recommended_probe="revised probe"), "id": first["id"]}, scope="project"
    )
    assert again["status"] == "updated"
    listed = fm.list_feedback(scope="project")
    assert listed["count"] == 1
    assert listed["entries"][0]["recommended_probe"] == "revised probe"


def test_generated_id_collision_appends_instead_of_overwriting(tmp_path, monkeypatch):
    # P2 (#145): DISTINCT lessons whose trigger_signal slugifies to the same
    # first-8-words id must NOT silently overwrite each other. With no explicit
    # id supplied, each collision is disambiguated and ALL lessons survive (the
    # old code took the same-id update branch and destroyed the earlier lesson —
    # data loss; the disambiguation branch was unreachable dead code).
    monkeypatch.chdir(tmp_path)
    base = "we-always-miss-the-timezone-boundary-in-billing"
    a = fm.capture_feedback(
        _good_entry(
            trigger_signal="we always miss the timezone boundary in billing for UTC",
            recommended_probe="probe A",
        ),
        scope="project",
    )
    b = fm.capture_feedback(
        _good_entry(
            trigger_signal="we always miss the timezone boundary in billing for India",
            recommended_probe="probe B",
        ),
        scope="project",
    )
    c = fm.capture_feedback(
        _good_entry(
            trigger_signal="we always miss the timezone boundary in billing for the EU",
            recommended_probe="probe C",
        ),
        scope="project",
    )
    assert a["id"] == base
    assert b["status"] == "captured" and b["id"] == f"{base}-2"
    # The third collision must skip the taken -2 (exercises the _unique_id loop).
    assert c["status"] == "captured" and c["id"] == f"{base}-3"
    listed = fm.list_feedback(scope="project")
    assert listed["count"] == 3  # all three distinct lessons survive
    assert {e["recommended_probe"] for e in listed["entries"]} == {"probe A", "probe B", "probe C"}


def test_list_empty_when_nothing_captured(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    listed = fm.list_feedback(scope="project")
    assert listed["count"] == 0
    assert listed["entries"] == []


def test_list_preserves_lesson_scope_distinct_from_pack_scope(tmp_path, monkeypatch):
    # Discriminating test: the lesson's own scope ("billing service") must NOT
    # be clobbered by the store scope ("project"). A naive {**e, "scope": sc}
    # merge would overwrite it — this asserts the two are kept distinct.
    monkeypatch.chdir(tmp_path)
    fm.capture_feedback(_good_entry(scope="billing service"), scope="project")
    only = fm.list_feedback(scope="project")["entries"][0]
    assert only["scope"] == "billing service"
    assert only["pack_scope"] == "project"


# --- R5: scope isolation ---------------------------------------------------


def test_project_and_global_scopes_are_isolated(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    fm.capture_feedback(_good_entry(trigger_signal="project-only lesson"), scope="project")
    fm.capture_feedback(_good_entry(trigger_signal="global lesson everywhere"), scope="global")
    proj = fm.list_feedback(scope="project")
    glob = fm.list_feedback(scope="global")
    assert proj["count"] == 1
    assert glob["count"] == 1
    assert proj["entries"][0]["trigger_signal"] == "project-only lesson"
    assert glob["entries"][0]["trigger_signal"] == "global lesson everywhere"


def test_list_merges_both_scopes_when_scope_is_none(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    fm.capture_feedback(_good_entry(trigger_signal="project lesson one"), scope="project")
    fm.capture_feedback(_good_entry(trigger_signal="global lesson two"), scope="global")
    merged = fm.list_feedback()
    assert merged["count"] == 2
    pack_scopes = sorted(e["pack_scope"] for e in merged["entries"])
    assert pack_scopes == ["global", "project"]
    # Each lesson's own scope field survives the merge unchanged.
    triggers = sorted(e["trigger_signal"] for e in merged["entries"])
    assert triggers == ["global lesson two", "project lesson one"]


def test_unknown_scope_raises(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(fm.FeedbackValidationError, match="unknown scope"):
        fm.capture_feedback(_good_entry(), scope="nope")
    with pytest.raises(fm.FeedbackValidationError, match="unknown scope"):
        fm.list_feedback(scope="nope")


# --- R3: advisory precedence (own subdir, never a bundled tier) ------------


def test_storage_lives_in_feedback_subdir_not_a_bundled_tier(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    fm.capture_feedback(_good_entry(), scope="project")
    path = paths.feedback_memory_path("project")
    assert path.is_file()
    # The file is under the #92 pack root's OWN feedback/ subdir...
    assert path.parent == paths.user_pack_root("project") / "feedback"
    # ...and must NOT collide with any canonical loader tier, so it can never
    # shadow classifications / standards / rules.
    assert path != paths.knowledge_dir("project") / "classifications.md"
    assert path.parent != paths.knowledge_dir("project")
    assert path.parent != paths.standards_packs_dir("project")
    assert path != paths.rules_path("project")


def test_every_listed_entry_is_advisory_flagged(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    fm.capture_feedback(_good_entry(), scope="project")
    listed = fm.list_feedback(scope="project")
    assert listed["advisory"] is True
    assert all(e["advisory"] is True for e in listed["entries"])
    assert "never override" in listed["note"].lower()


# --- R2: required-field validation (decision table) ------------------------


@pytest.mark.parametrize("missing", ["scope", "trigger_signal", "recommended_probe", "source_note"])
def test_missing_required_field_rejected_and_nothing_written(tmp_path, monkeypatch, missing):
    monkeypatch.chdir(tmp_path)
    entry = _good_entry()
    del entry[missing]
    with pytest.raises(fm.FeedbackValidationError, match="missing required field"):
        fm.capture_feedback(entry, scope="project")
    assert not paths.feedback_memory_path("project").exists()


@pytest.mark.parametrize("blank", ["", "   ", "\n"])
def test_blank_required_field_rejected(tmp_path, monkeypatch, blank):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(fm.FeedbackValidationError, match="missing required field"):
        fm.capture_feedback(_good_entry(scope=blank), scope="project")


def test_unknown_field_rejected(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(fm.FeedbackValidationError, match="unknown field"):
        fm.capture_feedback(_good_entry(raw_diff="oops"), scope="project")


def test_non_mapping_entry_rejected(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(fm.FeedbackValidationError, match="must be a mapping"):
        fm.capture_feedback("not a dict", scope="project")  # type: ignore[arg-type]


def test_malformed_timestamp_rejected(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(fm.FeedbackValidationError, match="ISO-8601"):
        fm.capture_feedback(_good_entry(last_reviewed="last tuesday"), scope="project")


# --- R1: sensitive-input rejection (equivalence partitioning) --------------


def test_rejects_raw_diff_hunk(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    diff = "@@ -10,3 +10,4 @@ def can_view(user):\n-    return True\n+    return user.is_auth"
    with pytest.raises(fm.FeedbackValidationError, match="raw diff hunk"):
        fm.capture_feedback(_good_entry(source_note=diff), scope="project")
    assert not paths.feedback_memory_path("project").exists()


def test_rejects_diff_git_header(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(fm.FeedbackValidationError, match="raw diff hunk"):
        fm.capture_feedback(
            _good_entry(recommended_probe="diff --git a/app/x.py b/app/x.py"), scope="project"
        )


def test_rejects_private_key_block(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    secret = "context: -----BEGIN RSA PRIVATE KEY-----\nMIIEpAIBAAKCAQEA..."
    with pytest.raises(fm.FeedbackValidationError, match="secret or credential"):
        fm.capture_feedback(_good_entry(source_note=secret), scope="project")


def test_rejects_secret_assignment(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(fm.FeedbackValidationError, match="secret or credential"):
        fm.capture_feedback(
            _good_entry(source_note="prod api_key = sk-live-abc123def"), scope="project"
        )


def test_rejects_code_snippet_fenced_block(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    code = "the bug was ```python\ndef apply(x):\n    return x*2\n```"
    with pytest.raises(fm.FeedbackValidationError, match="source-code snippet"):
        fm.capture_feedback(_good_entry(recommended_probe=code), scope="project")


def test_rejects_code_snippet_def_line(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    code = "we forgot to guard\ndef can_view(user, invoice):\n    return True"
    with pytest.raises(fm.FeedbackValidationError, match="source-code snippet"):
        fm.capture_feedback(_good_entry(source_note=code), scope="project")


@pytest.mark.parametrize(
    ("value", "label"),
    [
        # Bare AWS access key id (AKIA/ASIA + 16 chars) — no `key=` framing.
        ("the leaked key was AKIAIOSFODNN7EXAMPLE in our prod logs", "bare AWS access key id"),
        # Bare 40-char AWS secret access key (canonical AWS example, 40 chars).
        ("the secret was wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY in logs", "bare AWS secret"),
        # Bare GitHub personal-access token.
        ("a contractor pasted ghp_16C7e42F292c6912E7710c838347Ae178B4a here", "bare GitHub token"),
        # Bare Slack bot token.
        ("we exposed xoxb-2417-1293847-aBcDeFgHiJkLmNoPq in a screenshot", "bare Slack token"),
        # Bare JWT (three eyJ-led base64url segments).
        (
            "the session header eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dBjftJeZ_x leaked",
            "bare JWT",
        ),
        # Bare email address (PII).
        ("ping joanna.smith@example.com when the dunning job double-charges", "email address"),
        # Credit-card-shaped 16-digit run (PII).
        ("the failing fixture carried card 4111 1111 1111 1111 in the body", "credit-card-shaped"),
    ],
)
def test_rejects_bare_secret_or_pii_values(tmp_path, monkeypatch, value, label):
    # FIX1 (#145): the assignment-shape guard ('secret=...') misses a BARE value
    # pasted with no key= framing — yet the docstring promises a secret/credential
    # fails validation, and #145 AC bars raw-secret persistence. Each class is
    # asserted by its discriminating error label so a future regex change that
    # silently stops catching one class fails here.
    monkeypatch.chdir(tmp_path)
    with pytest.raises(fm.FeedbackValidationError, match=label):
        fm.capture_feedback(_good_entry(source_note=value), scope="project")
    assert not paths.feedback_memory_path("project").exists()


def test_rejects_zero_width_fragmented_secret(tmp_path, monkeypatch):
    # Hardening (#145): a credential broken up by an invisible zero-width joiner
    # must still be rejected. _check_not_sensitive strips zero-width chars (and
    # NFKC-folds confusables) before matching, so the contiguous-run token pattern
    # re-fires on the rejoined token. Without the strip this entry would be stored.
    monkeypatch.chdir(tmp_path)
    token = "ghp_16C7e42F292c6912E7710c838347Ae178B4a"
    fragmented = token[:8] + "\u200b" + token[8:]  # ZWSP hidden inside the token body
    with pytest.raises(fm.FeedbackValidationError, match="GitHub token"):
        fm.capture_feedback(
            _good_entry(source_note=f"a contractor pasted {fragmented} in chat"), scope="project"
        )
    assert not paths.feedback_memory_path("project").exists()


def test_accepts_prose_lesson_ending_in_semicolon(tmp_path, monkeypatch):
    # FIX1b (#145): the source-code tell used to fire on ANY line ending in ';',
    # over-rejecting ordinary prose. The tightened pattern needs a code-shaped
    # line (assignment/call/brace) before the ';', so a prose lesson that happens
    # to end in a semicolon is now ACCEPTED.
    monkeypatch.chdir(tmp_path)
    res = fm.capture_feedback(
        _good_entry(
            source_note="we keep missing the rounding boundary in billing; it recurs each quarter;"
        ),
        scope="project",
    )
    assert res["status"] == "captured"


def test_rejects_pasted_full_issue_body(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    body = (
        "## Problem\n\nlong pasted body. " + ("blah " * 120) + "\n\n## Acceptance criteria\n"
        "- [ ] first\n- [ ] second\n"
    )
    with pytest.raises(fm.FeedbackValidationError, match="full issue/PR body"):
        fm.capture_feedback(_good_entry(source_note=body), scope="project")


def test_accepts_ordinary_prose_summary(tmp_path, monkeypatch):
    # The negative control: a genuine plain-English lesson must NOT trip any
    # sensitive-content guard (otherwise the feature is useless).
    monkeypatch.chdir(tmp_path)
    res = fm.capture_feedback(
        _good_entry(
            source_note="we keep missing the GBP to USD rounding boundary in billing reports",
            recommended_probe="check rounding at the half-cent boundary with 6+ decimal rates",
        ),
        scope="project",
    )
    assert res["status"] == "captured"


# --- malformed store file --------------------------------------------------


def test_malformed_store_file_raises_on_read(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    path = paths.feedback_memory_path("project")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("entries: not-a-list\n", encoding="utf-8")
    with pytest.raises(fm.FeedbackValidationError, match="malformed"):
        fm.list_feedback(scope="project")


def test_empty_store_file_reads_as_no_entries(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    path = paths.feedback_memory_path("project")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("", encoding="utf-8")
    assert fm.list_feedback(scope="project")["count"] == 0


def test_write_cleans_up_temp_on_replace_failure(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    def boom(src, dst):
        raise OSError("replace failed")

    monkeypatch.setattr(fm.os, "replace", boom)
    with pytest.raises(OSError, match="replace failed"):
        fm.capture_feedback(_good_entry(), scope="project")
    # No leftover temp file in the destination directory — the write is atomic.
    dest_dir = paths.feedback_memory_path("project").parent
    assert list(dest_dir.glob(".*tmp*")) == []


# --- MCP tool wrapper ------------------------------------------------------


def _invoke_tool(server, tool_name, **kwargs):
    import asyncio
    import inspect

    tool = server._tool_manager._tools[tool_name]
    fn = tool.fn
    if inspect.iscoroutinefunction(fn):
        return asyncio.run(fn(**kwargs))
    return fn(**kwargs)


def test_feedback_tool_is_registered():
    from sumo_qa.server import build_mcp_server

    server = build_mcp_server()
    assert "sumo_qa_capture_review_feedback" in server._tool_manager._tools


def test_feedback_tool_capture_then_list(tmp_path, monkeypatch):
    from sumo_qa.server import build_mcp_server

    monkeypatch.chdir(tmp_path)
    server = build_mcp_server()
    cap = _invoke_tool(
        server, "sumo_qa_capture_review_feedback", action="capture", entry=_good_entry()
    )
    assert cap["status"] == "captured"
    listed = _invoke_tool(server, "sumo_qa_capture_review_feedback", action="list")
    assert listed["count"] == 1
    assert listed["advisory"] is True


def test_feedback_tool_list_is_default_action(tmp_path, monkeypatch):
    from sumo_qa.server import build_mcp_server

    monkeypatch.chdir(tmp_path)
    server = build_mcp_server()
    listed = _invoke_tool(server, "sumo_qa_capture_review_feedback")
    assert listed["status"] == "listed"
    assert listed["count"] == 0


def test_feedback_tool_update_and_delete(tmp_path, monkeypatch):
    from sumo_qa.server import build_mcp_server

    monkeypatch.chdir(tmp_path)
    server = build_mcp_server()
    cap = _invoke_tool(
        server, "sumo_qa_capture_review_feedback", action="capture", entry=_good_entry()
    )
    upd = _invoke_tool(
        server,
        "sumo_qa_capture_review_feedback",
        action="update",
        entry_id=cap["id"],
        entry=_good_entry(recommended_probe="revised"),
    )
    assert upd["entry"]["recommended_probe"] == "revised"
    deleted = _invoke_tool(
        server, "sumo_qa_capture_review_feedback", action="delete", entry_id=cap["id"]
    )
    assert deleted["status"] == "deleted"
    assert _invoke_tool(server, "sumo_qa_capture_review_feedback", action="list")["count"] == 0


def test_feedback_tool_sensitive_input_returns_error_envelope(tmp_path, monkeypatch):
    from sumo_qa.server import build_mcp_server

    monkeypatch.chdir(tmp_path)
    server = build_mcp_server()
    res = _invoke_tool(
        server,
        "sumo_qa_capture_review_feedback",
        action="capture",
        entry=_good_entry(source_note="@@ -1,2 +1,3 @@\n-old\n+new"),
    )
    assert res.get("isError") is True
    assert res["error"]["actionable_hint"]
    assert not paths.feedback_memory_path("project").exists()


def test_feedback_tool_rejected_entry_is_redacted_from_debug_capture(tmp_path, monkeypatch):
    # P2 (#145): when SUMO_QA_DEBUG_DIR is set, a REJECTED entry's raw content
    # must NOT reach the debug-capture sink — otherwise the secret the validator
    # just refused is flushed verbatim to disk, contradicting "sensitive input is
    # rejected, not stored". Only the entry's field NAMES are recorded on rejection.
    from sumo_qa.server import build_mcp_server

    monkeypatch.chdir(tmp_path)
    debug_dir = tmp_path / "debug"
    monkeypatch.setenv("SUMO_QA_DEBUG_DIR", str(debug_dir))
    secret = "ghp_16C7e42F292c6912E7710c838347Ae178B4a"
    server = build_mcp_server()
    res = _invoke_tool(
        server,
        "sumo_qa_capture_review_feedback",
        action="capture",
        entry=_good_entry(source_note=f"a contractor pasted {secret} in chat"),
    )
    assert res.get("isError") is True
    assert not paths.feedback_memory_path("project").exists()
    written = "".join(p.read_text() for p in debug_dir.rglob("*") if p.is_file())
    assert written, "expected the debug capture to have written something"
    assert secret not in written  # the rejected secret must never be persisted
    assert "_redacted_keys" in written  # only the entry's shape is recorded


def test_feedback_tool_unknown_action_returns_error_envelope(tmp_path, monkeypatch):
    from sumo_qa.server import build_mcp_server

    monkeypatch.chdir(tmp_path)
    server = build_mcp_server()
    res = _invoke_tool(server, "sumo_qa_capture_review_feedback", action="frobnicate")
    assert res.get("isError") is True
    assert "unknown action" in res["error"]["message"]


def test_feedback_tool_invalid_scope_returns_error_envelope(tmp_path, monkeypatch):
    # FIX2 (#145): a typo'd scope must NOT be silently coerced to 'project' and
    # written with status=captured. It is passed through to _require_scope, which
    # raises FeedbackValidationError → an error envelope, and nothing is written.
    from sumo_qa.server import build_mcp_server

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    server = build_mcp_server()
    res = _invoke_tool(
        server,
        "sumo_qa_capture_review_feedback",
        action="capture",
        entry=_good_entry(),
        scope="glabal",  # typo for 'global'
    )
    assert res.get("isError") is True
    assert "unknown scope" in res["error"]["message"]
    # The silent-write bug would have created the project store with the entry.
    assert not paths.feedback_memory_path("project").exists()
    assert not paths.feedback_memory_path("global").exists()


def test_feedback_tool_global_scope_routes_to_global(tmp_path, monkeypatch):
    from sumo_qa.server import build_mcp_server

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    server = build_mcp_server()
    _invoke_tool(
        server,
        "sumo_qa_capture_review_feedback",
        action="capture",
        entry=_good_entry(),
        scope="global",
    )
    assert paths.feedback_memory_path("global").is_file()
    assert not paths.feedback_memory_path("project").exists()


# --- CLI -------------------------------------------------------------------


def test_cli_list_outputs_json(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    fm.capture_feedback(_good_entry(), scope="project")
    rc = fm.main(["list", "--scope", "project"])
    assert rc == 0
    out = capsys.readouterr().out
    import json as _json

    parsed = _json.loads(out)
    assert parsed["count"] == 1


def test_cli_delete_removes_entry(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    cap = fm.capture_feedback(_good_entry(), scope="project")
    rc = fm.main(["delete", cap["id"], "--scope", "project"])
    assert rc == 0
    assert "deleted" in capsys.readouterr().out
    assert fm.list_feedback(scope="project")["count"] == 0


def test_cli_delete_unknown_id_errors(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    rc = fm.main(["delete", "nope", "--scope", "project"])
    assert rc == 1
    assert "sumo-qa-feedback" in capsys.readouterr().err
