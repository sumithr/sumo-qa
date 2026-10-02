# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Tests for `load_skill_context(mode="bundle")`.

The bundle hands a routed skill its working context in ONE call: the body,
the requested modules, the classification entries, and the standards and
rules for the change type. Every part must be byte-identical to what the
separate loaders return for the same argument, so a host that switches to the bundle cites exactly
the same catalogue text it would have loaded one call at a time.
"""

from __future__ import annotations

import json

import pytest

from sumo_qa import skill_manifest as sm
from sumo_qa.knowledge_loaders import (
    load_catalogue_entry,
    sumo_qa_load_rules,
    sumo_qa_load_standards,
)

REVIEW = "sumo-qa-reviewing-before-merge"


def _bundle(**kwargs):
    return sm.load_skill_context(REVIEW, "bundle", **kwargs)


def _module_text(module_id: str) -> str:
    return sm.load_skill_context(REVIEW, "module", module=module_id)["content"]


@pytest.mark.parametrize(
    "classification",
    ["business_logic_change", "security_change", "frontend_change", "test_change"],
)
def test_bundle_parts_match_the_separate_loaders(classification):
    out = _bundle(classification=classification, modules="runtime-scope,coverage-ledger")
    assert "error" not in out, out
    assert out["classification"] == [classification]
    assert out["rules"] == sumo_qa_load_rules(classification=classification)
    assert out["standards"] == sumo_qa_load_standards(classification=classification)
    entry = load_catalogue_entry("classifications", name=classification)
    assert out["classifications"] == entry["text"]
    assert [m["id"] for m in out["modules"]] == ["runtime-scope", "coverage-ledger"]
    assert out["modules"][0]["content"] == _module_text("runtime-scope")
    assert out["modules"][1]["content"] == _module_text("coverage-ledger")
    assert out["body"] == sm.load_skill_context(REVIEW, "full")["content"]


def test_bundle_carries_rules_for_an_aliased_classification():
    """`frontend_change` holds its rules under the legacy `ui_only_change` key;
    the bundle must not silently return empty rules for it."""
    out = _bundle(classification="frontend_change")
    assert out["rules"].strip() not in ("", "{}")


def test_multiple_classifications_are_split_and_each_entry_included():
    out = _bundle(classification="`business_logic_change`, security_change")
    assert out["classification"] == ["business_logic_change", "security_change"]
    assert "## business_logic_change" in out["classifications"]
    assert "## security_change" in out["classifications"]
    assert out["unmatched_classifications"] == []
    assert out["rules"] == sumo_qa_load_rules(
        classification="`business_logic_change`, security_change"
    )


def test_include_body_false_omits_the_body_the_host_already_holds():
    with_body = _bundle(classification="test_change")
    without = _bundle(classification="test_change", include_body=False)
    assert "body" not in without
    assert without["estimated_tokens"] < with_body["estimated_tokens"]


def test_bundle_without_classification_has_no_rules_or_standards():
    out = _bundle(modules="runtime-scope")
    assert out["classification"] == []
    assert "rules" not in out and "standards" not in out and "classifications" not in out


def test_classification_matching_nothing_returns_envelope_listing_catalogue_ids():
    out = _bundle(classification="made_up_change")
    assert out["error"] == "Unknown classification(s) ['made_up_change']."
    assert "business_logic_change" in out["available_classifications"]
    assert out["available_classifications"] == sorted(out["available_classifications"])


def test_a_partially_unmatched_list_reports_the_unmatched_ids():
    value = "made_up_change, business_logic_change"
    out = _bundle(classification=value)
    assert "error" not in out, out
    assert out["classification"] == ["business_logic_change", "made_up_change"]
    assert out["unmatched_classifications"] == ["made_up_change"]
    assert out["rules"] == sumo_qa_load_rules(classification=value)
    assert out["standards"] == sumo_qa_load_standards(classification=value)
    entry = load_catalogue_entry("classifications", name="business_logic_change")
    assert out["classifications"] == entry["text"]


def test_unknown_module_returns_envelope_listing_available():
    out = _bundle(modules="runtime-scope,no-such-module")
    assert "no-such-module" in out["error"]
    assert "runtime-scope" in out["available_modules"]


def test_module_path_traversal_is_rejected():
    out = _bundle(modules="../SKILL")
    assert "traversal" in out["error"]


def test_estimated_tokens_and_hash_describe_the_served_payload():
    out = _bundle(classification="test_change", modules="test-only-diff")
    payload = {k: v for k, v in out.items() if k not in ("estimated_tokens", "content_hash")}
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    assert out["estimated_tokens"] == sm._approx_tokens(text)
    assert out["content_hash"] == sm._content_hash(text)


def test_known_hash_round_trip_reports_unchanged_without_content():
    first = _bundle(classification="test_change", modules="test-only-diff")
    again = _bundle(
        classification="test_change", modules="test-only-diff", known_hash=first["content_hash"]
    )
    assert again["changed"] is False
    assert again["content_hash"] == first["content_hash"]
    assert not {"body", "modules", "rules", "standards", "classifications"} & set(again)
    stale = _bundle(classification="test_change", modules="test-only-diff", known_hash="stale")
    assert stale["changed"] is True
    assert stale["rules"] == first["rules"]


def test_rules_only_classification_is_accepted():
    """`ui_only_change` is a key in the change rules but not a catalogue entry."""
    out = _bundle(classification="ui_only_change")
    assert "error" not in out, out
    assert out["classification"] == ["ui_only_change"]
    assert out["unmatched_classifications"] == ["ui_only_change"]
    assert out["rules"] == sumo_qa_load_rules(classification="ui_only_change")
    assert out["rules"].strip() != "{}"
    assert out["classifications"] == ""


def test_missing_rules_path_returns_envelope_not_raise(monkeypatch, tmp_path):
    monkeypatch.setenv("QA_RULES_PATH", str(tmp_path / "absent.yaml"))
    out = _bundle(classification="business_logic_change")
    assert "unreadable" in out["error"]


def test_catalogue_is_not_read_without_a_classification(monkeypatch):
    def _fail(_catalogue):
        raise AssertionError("catalogue read without a classification")

    monkeypatch.setattr(sm, "list_catalogue_entries", _fail)
    out = _bundle(modules="runtime-scope")
    assert "error" not in out, out


def test_over_cap_bundle_returns_sized_envelope_without_content():
    out = _bundle(classification="business_logic_change", modules="runtime-scope", token_cap=500)
    assert out["oversize"] is True
    assert out["estimated_tokens"] > 500
    assert "body" not in out and "modules" not in out
    assert set(out["part_tokens"]) >= {"body", "modules", "rules", "standards"}


def test_bundle_for_a_skill_without_modules_rejects_module_ids():
    out = sm.load_skill_context("sumo-qa-finding-test-data", "bundle", modules="anything")
    assert "no modules" in out["error"]


def test_bundle_is_listed_as_a_valid_mode():
    out = sm.load_skill_context(REVIEW, "nope")
    assert "bundle" in out["available_modes"]


def test_unreadable_classification_catalogue_returns_envelope_not_raise(monkeypatch):
    """`load_skill_context` never raises: a missing catalogue is an envelope."""

    def _missing(_catalogue):
        raise FileNotFoundError("classifications.md")

    monkeypatch.setattr(sm, "list_catalogue_entries", _missing)
    out = _bundle(classification="test_change")
    assert "unreadable" in out["error"]


@pytest.mark.parametrize(
    ("source", "body"),
    [
        ("rules", "business_logic_change:\n  reviewed: 2026-02-30\n"),
        ("standards", "classifications: [business_logic_change]\ndate: 2026-13-01\n"),
        ("standards", "- business_logic_change\n"),
        ("rules", "b: " + "[" * 5000 + "]" * 5000 + "\n"),
    ],
)
def test_a_source_the_loaders_cannot_parse_returns_an_envelope(monkeypatch, tmp_path, source, body):
    if source == "rules":
        _rules_file(monkeypatch, tmp_path, body)
    else:
        (tmp_path / "packs").mkdir()
        (tmp_path / "packs" / "p.yaml").write_text(body, "utf-8")
        monkeypatch.setenv("QA_STANDARDS_PATH", str(tmp_path))
    out = _bundle(classification="business_logic_change")
    assert "unreadable" in out["error"]


def _rules_file(monkeypatch, tmp_path, body: str) -> None:
    rules = tmp_path / "change_rules.yaml"
    rules.write_text(body, encoding="utf-8")
    monkeypatch.setenv("QA_RULES_PATH", str(rules))


def test_mixed_case_ids_get_exactly_what_the_single_loaders_return():
    """Ids match exactly, as in the single loaders: a mixed-case id selects
    nothing on its own, and alongside a known id it is reported unmatched."""
    assert sumo_qa_load_rules(classification="Business_Logic_Change") == "{}\n"
    assert sumo_qa_load_standards(classification="Business_Logic_Change") == ""
    assert "Business_Logic_Change" in _bundle(classification="Business_Logic_Change")["error"]
    value = "Business_Logic_Change,security_change"
    out = _bundle(classification=value)
    assert out["unmatched_classifications"] == ["Business_Logic_Change"]
    assert out["rules"] == sumo_qa_load_rules(classification=value)
    assert out["standards"] == sumo_qa_load_standards(classification=value)


def test_a_standards_only_id_is_accepted(monkeypatch, tmp_path):
    (tmp_path / "packs").mkdir()
    (tmp_path / "packs" / "p.yaml").write_text(
        "applies_to_classifications: [pack_only_change]\n", "utf-8"
    )
    monkeypatch.setenv("QA_STANDARDS_PATH", str(tmp_path))
    out = _bundle(classification="pack_only_change")
    assert "error" not in out, out
    assert out["unmatched_classifications"] == ["pack_only_change"]
    assert out["rules"] == "{}\n"
    assert out["standards"] == sumo_qa_load_standards(classification="pack_only_change")
    assert out["standards"].startswith("# p.yaml")


def test_a_rules_file_the_loader_returns_raw_counts_as_a_match(monkeypatch, tmp_path):
    """A rules file that is not a mapping comes back from the loader whole."""
    _rules_file(monkeypatch, tmp_path, "- just\n- a list\n")
    out = _bundle(classification="made_up_change")
    assert out["rules"] == "- just\n- a list\n"
    assert out["unmatched_classifications"] == ["made_up_change"]


def test_module_ids_are_matched_exactly_as_in_module_mode(monkeypatch):
    records = sm._skill_records()
    review = records[REVIEW]
    review["modules"] = [dict(m, id=m["id"].title()) for m in review["modules"]]
    monkeypatch.setattr(sm, "_skill_records", lambda: records)
    upper = review["modules"][0]["id"]
    assert upper != upper.lower()
    single = sm.load_skill_context(REVIEW, "module", module=upper)
    bundled = _bundle(modules=upper)
    assert bundled["modules"] == [
        {"id": upper, "path": review["modules"][0]["path"], "content": single["content"]}
    ]
    lower = upper.lower()
    for mode_out in (_bundle(modules=lower), sm.load_skill_context(REVIEW, "module", module=lower)):
        assert mode_out["error"] == f"Unknown module {lower!r} for skill {REVIEW!r}."


def test_unknown_module_error_echoes_the_id_as_sent():
    out = _bundle(modules="Runtime-Scope")
    assert out["error"] == f"Unknown module 'Runtime-Scope' for skill {REVIEW!r}."
    assert out == sm.load_skill_context(REVIEW, "module", module="Runtime-Scope")


def test_module_ids_are_not_unquoted():
    out = _bundle(modules=" `runtime-scope` ")
    assert out == sm.load_skill_context(REVIEW, "module", module="`runtime-scope`")
    assert "`runtime-scope`" in out["error"]


def test_module_ids_split_on_commas_and_strip_whitespace():
    out = _bundle(modules=" runtime-scope ,, coverage-ledger ")
    assert [m["id"] for m in out["modules"]] == ["runtime-scope", "coverage-ledger"]
