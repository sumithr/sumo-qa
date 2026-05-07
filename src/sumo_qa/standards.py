from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError


class _RawCheck(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    title: str
    applies_to: list[str] = Field(min_length=1)
    severity: Literal["low", "medium", "high"]
    qa_focus: str
    pass_criteria: list[str] = Field(min_length=1)


class _RawPack(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    version: str
    name: str
    description: str | None = None
    domain: str | None = None
    checks: list[_RawCheck] = Field(min_length=1)


@dataclass(frozen=True)
class StandardCheck:
    id: str
    title: str
    applies_to: tuple[str, ...]
    severity: str
    qa_focus: str
    pass_criteria: tuple[str, ...]


@dataclass(frozen=True)
class StandardsPack:
    id: str
    version: str
    name: str
    checks: tuple[StandardCheck, ...]
    source: Path


@dataclass(frozen=True)
class StandardsEvaluation:
    workflow: str
    pack_versions: list[str]
    checks: list[dict[str, Any]]
    prompts: list[str]


class StandardsEngine:
    def __init__(self, packs: list[StandardsPack]) -> None:
        self._packs = packs

    @classmethod
    def from_directory(cls, directory: str | Path) -> "StandardsEngine":
        root = Path(directory)
        if not root.exists():
            raise FileNotFoundError(f"Standards directory not found: {root}")

        packs = [cls._load_pack(path) for path in sorted(root.glob("*.y*ml"))]
        if not packs:
            raise ValueError(f"No standards YAML packs found in {root}")
        return cls(packs)

    @staticmethod
    def _load_pack(path: Path) -> StandardsPack:
        with path.open("r", encoding="utf-8") as handle:
            raw = yaml.safe_load(handle) or {}

        try:
            parsed = _RawPack.model_validate(raw)
        except ValidationError as exc:
            raise ValueError(f"Invalid standards pack at {path}: {exc}") from exc

        checks = tuple(
            StandardCheck(
                id=check.id,
                title=check.title,
                applies_to=tuple(check.applies_to),
                severity=check.severity,
                qa_focus=check.qa_focus,
                pass_criteria=tuple(check.pass_criteria),
            )
            for check in parsed.checks
        )
        return StandardsPack(
            id=parsed.id,
            version=parsed.version,
            name=parsed.name,
            checks=checks,
            source=path,
        )

    def evaluate(self, workflow: str) -> StandardsEvaluation:
        matched: list[dict[str, Any]] = []
        prompts: list[str] = []

        for pack in self._packs:
            for check in pack.checks:
                if workflow in check.applies_to:
                    matched.append(
                        {
                            "id": check.id,
                            "title": check.title,
                            "severity": check.severity,
                            "qa_focus": check.qa_focus,
                            "pass_criteria": list(check.pass_criteria),
                        }
                    )
                    prompts.append(f"{check.title}: {check.qa_focus}")

        return StandardsEvaluation(
            workflow=workflow,
            pack_versions=[f"{pack.id}@{pack.version}" for pack in self._packs],
            checks=matched,
            prompts=prompts,
        )


