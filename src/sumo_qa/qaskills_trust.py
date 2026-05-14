# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Publisher-trust and category-keyword config for the qaskills.sh integration.

The registry is a hand-edited JSON file shipped under
`skills/sumo-qa-suggesting-external-skill/registry.json`. It controls:

- Which publishers sumo-qa surfaces without an extra confirmation step.
- Which publishers are blocked outright.
- Which keywords route an intent to a known QA category.
"""
from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

TrustDecision = Literal["trusted", "untrusted", "blocked"]


class RegistryError(Exception):
    """Raised when the registry file is malformed."""


@dataclass(frozen=True)
class Registry:
    trusted_publishers: tuple[str, ...]
    blocked_publishers: tuple[str, ...]
    category_keywords: Mapping[str, tuple[str, ...]] = field(default_factory=dict)


def load(path: Path) -> Registry:
    """Load the registry from disk; missing file → empty registry."""
    if not path.is_file():
        return Registry(trusted_publishers=(), blocked_publishers=(), category_keywords={})
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RegistryError(f"registry at {path} is not valid JSON: {exc}") from exc
    return Registry(
        trusted_publishers=tuple(raw.get("trusted_publishers", ())),
        blocked_publishers=tuple(raw.get("blocked_publishers", ())),
        category_keywords={k: tuple(v) for k, v in raw.get("category_keywords", {}).items()},
    )


def decide(registry: Registry, publisher: str) -> TrustDecision:
    """Decide whether a publisher is trusted, untrusted, or blocked.

    Blocked takes precedence — if a publisher is on both lists somehow,
    we err on the side of safety.
    """
    if publisher in registry.blocked_publishers:
        return "blocked"
    if publisher in registry.trusted_publishers:
        return "trusted"
    return "untrusted"


def category_for_intent(registry: Registry, intent: str) -> str | None:
    """Return the category whose keywords appear in `intent`, else None.

    Case-insensitive substring match. The first matching category wins —
    callers needing tighter matching should refine the keywords in the
    registry.
    """
    lowered = intent.lower()
    for category, keywords in registry.category_keywords.items():
        if any(kw.lower() in lowered for kw in keywords):
            return category
    return None
