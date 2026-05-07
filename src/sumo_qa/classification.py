from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Iterable


def _signal_confidence(signals: list[str]) -> str:
    unique = len(set(signals))
    if unique >= 3:
        return "high"
    if unique == 2:
        return "medium"
    return "low"


# Canonical change-classification names. The team's standards / rules YAML
# packs are keyed on these names — they are the team's vocabulary, not a
# detection mechanism. The AI-sampling path classifies a change against
# this enumeration; the harness no longer pattern-matches paths or text.
CHANGE_CLASSIFICATIONS = {
    "api_contract_change",
    "business_logic_change",
    "state_transition_change",
    "ui_only_change",
    "configuration_change",
    "data_mapping_change",
    "error_handling_change",
    "async_flow_change",
    "caching_change",
    "security_change",
}


@dataclass(frozen=True)
class ChangeClassification:
    name: str
    confidence: str
    signals: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ClassificationResult:
    classifications: list[ChangeClassification]
    inspected_files: list[str]
    inspected_keywords: list[str]

    @property
    def primary(self) -> str | None:
        return self.classifications[0].name if self.classifications else None

    def names(self) -> list[str]:
        return [classification.name for classification in self.classifications]

    def to_dict(self) -> dict[str, object]:
        return {
            "primary": self.primary,
            "primary_confidence": self.classifications[0].confidence if self.classifications else "low",
            "confidence_note": self._confidence_note(),
            "classifications": [asdict(item) for item in self.classifications],
            "inspected_files": self.inspected_files,
            "inspected_keywords": self.inspected_keywords,
        }

    def _confidence_note(self) -> str:
        if not self.classifications:
            return (
                "Unsure: deterministic harness does not classify changes. "
                "Approve MCP sampling so the AI can classify the change "
                "against the team's canonical change-classification "
                "enumeration, or pass an explicit `signals` override."
            )
        primary = self.classifications[0]
        if primary.confidence == "low":
            others = [item.name for item in self.classifications[1:3]]
            also = f" Could also be: {', '.join(others)}." if others else ""
            return (
                f"Low confidence: '{primary.name}' was inferred from {len(primary.signals)} "
                f"weak signal(s).{also}"
            )
        if primary.confidence == "medium":
            return f"Medium confidence: '{primary.name}' from {len(primary.signals)} signal(s)."
        return f"High confidence: '{primary.name}' backed by {len(primary.signals)} signals."


class ChangeClassificationEngine:
    """Deterministic-fallback classifier.

    The AI-sampling path is the brain. The deterministic harness deliberately
    does NOT pattern-match the change_summary, the diff, or the file paths
    to guess a classification — pattern matching can't keep up with how
    languages / repo conventions / domain vocabularies vary, and the AI is
    grounded against the canonical change-classification enumeration via
    the system prompt.

    This engine accepts caller-supplied classifications (e.g. when a wrapper
    has already AI-classified the change) and otherwise returns an empty
    result. The empty result's `confidence_note` tells the caller to enable
    MCP sampling or pass explicit classifications.
    """

    def classify(
        self,
        change_summary: str = "",
        changed_file_paths: Iterable[str] | None = None,
        diff_snippet: str = "",
        explicit_classifications: list[str] | None = None,
    ) -> ClassificationResult:
        files = sorted(set(changed_file_paths or []))
        # If a caller has classified the change explicitly (e.g. an AI
        # classifier upstream, or a known-good signal), honour that.
        if explicit_classifications:
            classifications = [
                ChangeClassification(
                    name=name,
                    confidence="high",
                    signals=["explicit"],
                )
                for name in explicit_classifications
                if name in CHANGE_CLASSIFICATIONS
            ]
            return ClassificationResult(
                classifications=classifications,
                inspected_files=files,
                inspected_keywords=[],
            )
        # No pattern matching. Empty result — the AI path or an explicit
        # signal is the only way to get a classification.
        return ClassificationResult(
            classifications=[],
            inspected_files=files,
            inspected_keywords=[],
        )
