from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Protocol


KnowledgeConfidence = Literal["low", "medium", "high"]


@dataclass(frozen=True)
class KnowledgeCitation:
    source_id: str
    title: str
    url: str | None = None
    locator: str | None = None


@dataclass(frozen=True)
class KnowledgeSource:
    id: str
    name: str
    source_type: str
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class KnowledgeItem:
    id: str
    title: str
    content: str
    source_id: str
    domain_ids: list[str] = field(default_factory=list)
    confidence: KnowledgeConfidence = "medium"
    citations: list[KnowledgeCitation] = field(default_factory=list)
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class KnowledgeContext:
    """Domain context returned by a knowledge provider."""

    query: str
    items: list[KnowledgeItem] = field(default_factory=list)
    sources: list[KnowledgeSource] = field(default_factory=list)
    domain_ids: list[str] = field(default_factory=list)
    confidence: KnowledgeConfidence = "low"
    metadata: dict[str, str] = field(default_factory=dict)


class KnowledgeProvider(Protocol):
    """Interface for future Jira, Confluence, GitLab, or KB providers."""

    provider_name: str

    def fetch_context(
        self,
        query: str,
        scope: str | None = None,
        domain_ids: list[str] | None = None,
    ) -> KnowledgeContext:
        """Return relevant domain context for a QA workflow."""


class NullKnowledgeProvider:
    """Default provider used when no external knowledge systems are configured."""

    provider_name = "null"

    def fetch_context(
        self,
        query: str,
        scope: str | None = None,
        domain_ids: list[str] | None = None,
    ) -> KnowledgeContext:
        return KnowledgeContext(
            query=query,
            items=[],
            sources=[],
            domain_ids=domain_ids or [],
            confidence="low",
            metadata={
                "provider": self.provider_name,
                "scope": scope or "unspecified",
                "status": "no external knowledge provider configured",
            },
        )
