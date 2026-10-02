# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Tests for `load_skill_context(mode="bundle")` (#512).

The bundle hands a routed skill its working context in ONE call: the body,
the requested modules, the classification entries, and the standards and
rules for the change type. Every part must be byte-identical to what the
separate loaders return, so a host that switches to the bundle cites exactly
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
    assert out["rules"] == sumo_qa_load_rules(
        classification="business_logic_change,security_change"
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


def test_unknown_classification_returns_envelope_listing_valid_ids():
    out = _bundle(classification="business_logic_change,made_up_change")
    assert "made_up_change" in out["error"]
    assert "business_logic_change" in out["available_classifications"]


def test_unknown_module_returns_envelope_listing_available():
    out = _bundle(modules="runtime-scope,no-such-module")
    assert "no-such-module" in out["error"]
    assert "runtime-scope" in out["available_modules"]


def test_module_path_traversal_is_rejected():
    out = _bundle(modules="../SKILL")
    assert "traversal" in out["error"]


def test_estimated_tokens_and_hash_describe_the_returned_payload():
    out = _bundle(classification="test_change", modules="test-only-diff")
    payload = {k: v for k, v in out.items() if k not in ("estimated_tokens", "content_hash")}
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    assert out["estimated_tokens"] == sm._approx_tokens(text)
    assert out["content_hash"] == sm._content_hash(text)


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
