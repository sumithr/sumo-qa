# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
from __future__ import annotations

import json
from pathlib import Path

import pytest

from sumo_qa import qaskills_trust


def _write_registry(path: Path, payload: dict) -> Path:
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_load_returns_parsed_registry(tmp_path: Path) -> None:
    reg_path = _write_registry(
        tmp_path / "registry.json",
        {
            "version": 1,
            "trusted_publishers": ["thetestingacademy"],
            "blocked_publishers": ["sketchy"],
            "category_keywords": {"e2e": ["playwright", "cypress"]},
        },
    )
    reg = qaskills_trust.load(reg_path)
    assert reg.trusted_publishers == ("thetestingacademy",)
    assert reg.blocked_publishers == ("sketchy",)
    assert reg.category_keywords["e2e"] == ("playwright", "cypress")


def test_load_handles_missing_file_with_empty_registry(tmp_path: Path) -> None:
    reg = qaskills_trust.load(tmp_path / "does-not-exist.json")
    assert reg.trusted_publishers == ()
    assert reg.blocked_publishers == ()
    assert reg.category_keywords == {}


def test_load_raises_on_malformed_json(tmp_path: Path) -> None:
    bad = tmp_path / "registry.json"
    bad.write_text("not json", encoding="utf-8")
    with pytest.raises(qaskills_trust.RegistryError):
        qaskills_trust.load(bad)


def test_decide_returns_trusted_for_known_publisher() -> None:
    reg = qaskills_trust.Registry(
        trusted_publishers=("thetestingacademy",),
        blocked_publishers=(),
        category_keywords={},
    )
    assert qaskills_trust.decide(reg, "thetestingacademy") == "trusted"


def test_decide_returns_blocked_for_blocklisted_publisher() -> None:
    reg = qaskills_trust.Registry(
        trusted_publishers=("thetestingacademy",),
        blocked_publishers=("sketchy",),
        category_keywords={},
    )
    assert qaskills_trust.decide(reg, "sketchy") == "blocked"


def test_decide_returns_untrusted_for_unknown_publisher() -> None:
    reg = qaskills_trust.Registry(
        trusted_publishers=("thetestingacademy",),
        blocked_publishers=(),
        category_keywords={},
    )
    assert qaskills_trust.decide(reg, "newcomer") == "untrusted"


def test_decide_blocked_overrides_trusted() -> None:
    # Defensive: if a publisher somehow ends up on both lists, blocked wins.
    reg = qaskills_trust.Registry(
        trusted_publishers=("ambiguous",),
        blocked_publishers=("ambiguous",),
        category_keywords={},
    )
    assert qaskills_trust.decide(reg, "ambiguous") == "blocked"


def test_category_for_intent_matches_keyword() -> None:
    reg = qaskills_trust.Registry(
        trusted_publishers=(),
        blocked_publishers=(),
        category_keywords={"e2e": ("playwright", "cypress"), "a11y": ("accessibility", "axe")},
    )
    assert qaskills_trust.category_for_intent(reg, "set up Playwright tests") == "e2e"
    assert qaskills_trust.category_for_intent(reg, "audit Accessibility") == "a11y"
    assert qaskills_trust.category_for_intent(reg, "refactor pricing") is None


def test_category_for_intent_is_case_insensitive() -> None:
    reg = qaskills_trust.Registry(
        trusted_publishers=(),
        blocked_publishers=(),
        category_keywords={"perf": ("k6", "Load Test")},
    )
    assert qaskills_trust.category_for_intent(reg, "k6 LOAD TEST") == "perf"
    assert qaskills_trust.category_for_intent(reg, "K6") == "perf"
