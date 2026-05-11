from __future__ import annotations

from pathlib import Path
from typing import Any

from sumo_qa.tdm_catalogue import TestDataCatalogue
from sumo_qa.tdm_service import TestDataAssistant
from sumo_qa.tdm_validation import TestDataValidator


DEFAULT_STANDARDS_PATH = Path("standards/packs")
DEFAULT_RULES_PATH = Path("standards/rules/change_rules.yaml")
DEFAULT_TEST_DATA_PATH = Path("knowledge/test_data")


def _resolve_data_path(user_path: str | Path, default: Path, *bundled_parts: str) -> Path:
    """Pick the right path for a data resource.

    Resolution order (only when the caller passed the default sentinel):
      1. cwd-relative default (development from a repo clone)
      2. The bundled copy under sumo_qa/_data/ (installed via wheel)
      3. The default itself (which will surface a clear error downstream)

    When the caller passed an explicit path, it is honoured as-is.
    """
    candidate = Path(user_path)
    if candidate != default:
        return candidate
    if candidate.exists():
        return candidate
    bundled = _bundled_data_path(*bundled_parts)
    if bundled is not None and bundled.exists():
        return bundled
    return candidate


def _bundled_data_path(*parts: str) -> Path | None:
    """Return the on-disk path for a bundled data resource, or None."""
    try:
        import importlib.resources as resources
    except ImportError:  # pragma: no cover - Python <3.9
        return None
    try:
        anchor = resources.files("sumo_qa") / "_data"
    except (ModuleNotFoundError, FileNotFoundError):
        return None
    for part in parts:
        anchor = anchor / part
    try:
        as_path = Path(str(anchor))
    except Exception:  # pragma: no cover - defensive
        return None
    return as_path


class QAShiftLeftService:
    """Test-data flows backed by the local YAML catalogue.

    The heavy QA reasoning tools were removed in Phase 4 of the superpowers
    restructure; the host LLM now drives that reasoning via skill prompts
    and knowledge loaders. This service only exposes the 4 test-data tools.
    """

    def __init__(
        self,
        test_data_assistant: TestDataAssistant | None = None,
        test_data_catalogue: TestDataCatalogue | None = None,
        test_data_validator: TestDataValidator | None = None,
    ) -> None:
        self.test_data_assistant = test_data_assistant or TestDataAssistant(
            test_data_catalogue or TestDataCatalogue(DEFAULT_TEST_DATA_PATH),
            test_data_validator,
        )

    @classmethod
    def from_standards_path(
        cls,
        path: str | Path = DEFAULT_STANDARDS_PATH,
        rules_path: str | Path = DEFAULT_RULES_PATH,
        test_data_path: str | Path = DEFAULT_TEST_DATA_PATH,
    ) -> "QAShiftLeftService":
        # standards_path / rules_path are kept in the signature for backward
        # compatibility with build_service() and existing tests, even though
        # the slimmed service no longer evaluates standards or rules.
        del path, rules_path  # unused after Phase 4 deletion
        resolved_test_data_path = _resolve_data_path(
            test_data_path, DEFAULT_TEST_DATA_PATH, "knowledge", "test_data"
        )
        return cls(
            test_data_catalogue=TestDataCatalogue(resolved_test_data_path),
        )

    def qa_explain_test_data_requirements(
        self,
        question: str,
        environment: str | None = None,
        domain: str | None = None,
    ) -> dict[str, Any]:
        return self.test_data_assistant.explain_requirements(question, environment, domain)

    def qa_find_test_data(
        self,
        environment: str | None = None,
        domain: str | None = None,
        scenario_tags: list[str] | None = None,
        known_valid_for: list[str] | None = None,
        product_id: str | None = None,
        sku: str | None = None,
        limit: int = 5,
        offset: int = 0,
    ) -> dict[str, Any]:
        return self.test_data_assistant.find_test_data(
            environment=environment,
            domain=domain,
            scenario_tags=scenario_tags,
            known_valid_for=known_valid_for,
            product_id=product_id,
            sku=sku,
            limit=limit,
            offset=offset,
        )

    def qa_validate_test_data(
        self,
        entry_id: str | None = None,
        entry: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self.test_data_assistant.validate_test_data(entry_id, entry)

    def qa_register_known_good_test_data(self, entry: dict[str, Any]) -> dict[str, Any]:
        return self.test_data_assistant.register_known_good_test_data(entry)

    # Async wrappers — kept for parity with the historical surface. The
    # underlying test-data operations are synchronous file I/O against the
    # local catalogue, so we just delegate.

    async def aqa_explain_test_data_requirements(
        self,
        question: str,
        environment: str | None = None,
        domain: str | None = None,
    ) -> dict[str, Any]:
        return self.qa_explain_test_data_requirements(question, environment, domain)

    async def aqa_find_test_data(
        self,
        environment: str | None = None,
        domain: str | None = None,
        scenario_tags: list[str] | None = None,
        known_valid_for: list[str] | None = None,
        product_id: str | None = None,
        sku: str | None = None,
        limit: int = 5,
        offset: int = 0,
    ) -> dict[str, Any]:
        return self.qa_find_test_data(
            environment=environment,
            domain=domain,
            scenario_tags=scenario_tags,
            known_valid_for=known_valid_for,
            product_id=product_id,
            sku=sku,
            limit=limit,
            offset=offset,
        )

    async def aqa_validate_test_data(
        self,
        entry_id: str | None = None,
        entry: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self.qa_validate_test_data(entry_id, entry)

    async def aqa_register_known_good_test_data(self, entry: dict[str, Any]) -> dict[str, Any]:
        return self.qa_register_known_good_test_data(entry)
