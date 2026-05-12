from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from sumo_qa.tdm_models import TestDataEntry


class TestDataCatalogue:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self._entries_cache: list[TestDataEntry] | None = None

    def _invalidate_cache(self) -> None:
        self._entries_cache = None

    def list_entries(self) -> list[TestDataEntry]:
        if self._entries_cache is not None:
            return list(self._entries_cache)
        if not self.root.exists():
            self._entries_cache = []
            return []
        entries: list[TestDataEntry] = []
        for path in sorted(self.root.glob("*/*.y*ml")):
            for index, raw_entry in enumerate(_load_entries(path)):
                if not isinstance(raw_entry, dict):
                    raise ValueError(
                        f"Invalid test data file {path}: entry at index {index} is "
                        f"{type(raw_entry).__name__}, expected mapping"
                    )
                identifier = raw_entry.get("id") or f"index {index}"
                try:
                    entries.append(TestDataEntry(**raw_entry))
                except ValidationError as exc:
                    raise ValueError(
                        f"Invalid test data entry '{identifier}' in {path}: {exc}"
                    ) from exc
        self._entries_cache = entries
        return list(entries)

    def get(self, entry_id: str) -> TestDataEntry | None:
        for entry in self.list_entries():
            if entry.id == entry_id:
                return entry
        return None

    def find(
        self,
        environment: str | None = None,
        domain: str | None = None,
        scenario_tags: list[str] | None = None,
        known_valid_for: list[str] | None = None,
        product_id: str | None = None,
        sku: str | None = None,
    ) -> list[TestDataEntry]:
        tags = {item.lower() for item in scenario_tags or []}
        valid_for = {item.lower() for item in known_valid_for or []}
        results = []
        for entry in self.list_entries():
            if environment and entry.environment.lower() != environment.lower():
                continue
            if domain and entry.domain.lower() != domain.lower():
                continue
            if product_id and (entry.product_id or "").lower() != product_id.lower():
                continue
            if sku and (entry.sku or "").lower() != sku.lower():
                continue
            entry_tags = {item.lower() for item in entry.scenario_tags}
            entry_valid_for = {item.lower() for item in entry.known_valid_for}
            if tags and not tags.issubset(entry_tags):
                continue
            if valid_for and not valid_for.intersection(entry_valid_for):
                continue
            results.append(entry)
        return results

    def register(self, entry: TestDataEntry) -> tuple[str, TestDataEntry, str, str | None]:
        self.root.mkdir(parents=True, exist_ok=True)
        path = self._path_for(entry.domain)
        payload = _load_file(path)
        entries = payload.setdefault("entries", [])

        duplicate = self._find_duplicate(entry)
        if duplicate and duplicate.id != entry.id:
            return "duplicate", duplicate, path.as_posix(), duplicate.id

        updated_entry = _touch_entry(entry)
        for index, raw_entry in enumerate(entries):
            if raw_entry.get("id") == updated_entry.id:
                entries[index] = _dump_entry(updated_entry)
                _write_file(path, payload)
                self._invalidate_cache()
                return "updated", updated_entry, path.as_posix(), None

        entries.append(_dump_entry(updated_entry))
        entries.sort(key=lambda item: str(item.get("id", "")))
        _write_file(path, payload)
        self._invalidate_cache()
        return "created", updated_entry, path.as_posix(), None

    def _path_for(self, domain: str) -> Path:
        domain_dir = self.root / _slug(domain)
        domain_dir.mkdir(parents=True, exist_ok=True)
        return domain_dir / "known_good.yaml"

    def _find_duplicate(self, entry: TestDataEntry) -> TestDataEntry | None:
        entry_tags = set(entry.scenario_tags)
        entry_valid_for = set(entry.known_valid_for)
        for existing in self.list_entries():
            if existing.id == entry.id:
                return existing
            same_identity = (
                existing.environment == entry.environment
                and existing.domain == entry.domain
                and existing.product_id == entry.product_id
                and existing.sku == entry.sku
            )
            if (
                same_identity
                and entry_tags.intersection(existing.scenario_tags)
                and entry_valid_for.intersection(existing.known_valid_for)
            ):
                return existing
        return None


def _load_entries(path: Path) -> list[Any]:
    payload = _load_file(path)
    raw_entries = payload.get("entries", [])
    if not isinstance(raw_entries, list):
        raise ValueError(
            f"Invalid test data file {path}: 'entries' must be a list, "
            f"got {type(raw_entries).__name__}"
        )
    return list(raw_entries)


def _load_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"entries": []}
    with path.open("r", encoding="utf-8") as handle:
        try:
            loaded = yaml.safe_load(handle)
        except yaml.YAMLError as exc:
            raise ValueError(f"Invalid YAML in test data file {path}: {exc}") from exc
    if loaded is None:
        return {"entries": []}
    if not isinstance(loaded, dict):
        raise ValueError(
            f"Invalid test data file {path}: top-level value must be a mapping, "
            f"got {type(loaded).__name__}"
        )
    return loaded


def _write_file(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(payload, handle, sort_keys=False, allow_unicode=False)


def _dump_entry(entry: TestDataEntry) -> dict[str, Any]:
    payload = entry.model_dump(mode="json")
    return {key: value for key, value in payload.items() if value not in (None, [], "")}


def _touch_entry(entry: TestDataEntry) -> TestDataEntry:
    return entry.model_copy(update={"last_validated_at": datetime.now(timezone.utc)})


def _slug(value: str) -> str:
    return (
        "".join(character if character.isalnum() else "_" for character in value.lower()).strip("_")
        or "general"
    )
