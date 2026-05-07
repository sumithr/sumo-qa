from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


TDMConfidenceLevel = Literal["low", "medium", "high"]
FreshnessStatus = Literal["fresh", "aging", "stale", "unknown", "not_applicable"]


class FreshnessMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: FreshnessStatus
    last_validated_at: datetime | None = None
    age_days: int | None = None
    reason: str


class TestDataConfidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    level: TDMConfidenceLevel
    reason: str


class TestDataEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    environment: str
    domain: str
    product_id: str | None = None
    sku: str | None = None
    scenario_tags: list[str] = Field(default_factory=list)
    known_valid_for: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    owner: str
    last_validated_at: datetime | None = None
    confidence: TDMConfidenceLevel = "low"
    source: str
    notes: str = ""
    validation_source: str = "catalogue"


class ValidationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entry_id: str
    valid: bool
    confidence: TestDataConfidence
    freshness: FreshnessMetadata
    validation_source: str
    validation_reason: str
    checked_at: datetime
    issues: list[str] = Field(default_factory=list)


class TestDataRequirements(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool: Literal["qa_explain_test_data_requirements"] = "qa_explain_test_data_requirements"
    summary: str
    domain: str
    environment: str | None = None
    required_product_characteristics: list[str] = Field(default_factory=list)
    stock_conditions: list[str] = Field(default_factory=list)
    fulfilment_conditions: list[str] = Field(default_factory=list)
    downstream_dependencies: list[str] = Field(default_factory=list)
    edge_case_recommendations: list[str] = Field(default_factory=list)
    what_not_to_use: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    confidence: TestDataConfidence
    freshness: FreshnessMetadata
    validation_source: str


class TestDataSearchResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entry: TestDataEntry
    validation: ValidationResult
    suitability_reason: str
    rank_score: int


class TestDataFindResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool: Literal["qa_find_test_data"] = "qa_find_test_data"
    query: dict[str, object]
    results: list[TestDataSearchResult]
    total_count: int = 0
    has_more: bool = False
    next_offset: int | None = None
    missing_information: list[str] = Field(default_factory=list)
    confidence: TestDataConfidence
    freshness: FreshnessMetadata
    validation_source: str


class TestDataValidateResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool: Literal["qa_validate_test_data"] = "qa_validate_test_data"
    entry: TestDataEntry
    validation: ValidationResult


class TestDataRegisterResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool: Literal["qa_register_known_good_test_data"] = "qa_register_known_good_test_data"
    action: Literal["created", "updated", "duplicate"]
    entry: TestDataEntry
    validation: ValidationResult
    catalogue_path: str
    duplicate_of: str | None = None
