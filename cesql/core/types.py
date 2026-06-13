"""Shared data structures for the CE-SQL mini-framework."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class PartialSemanticOracle:
    oracle_type: str
    nl_span: str
    confidence: float
    target_table: str | None = None
    target_alias: str | None = None
    target_column: str | None = None
    operator: str | None = None
    value: str | None = None
    target_entity: str | None = None
    target_id_column: str | None = None
    expected_aggregation: str | None = None
    source: str | None = None
    canonical_table: str | None = None
    canonical_column: str | None = None
    adapted_alias: str | None = None
    validation_status: str | None = None
    adapter_status: str | None = None


@dataclass(frozen=True)
class OracleExtractionResult:
    oracles: list[PartialSemanticOracle]
    rejected_oracles: list[dict[str, Any]] = field(default_factory=list)
    low_confidence_oracles: list[dict[str, Any]] = field(default_factory=list)
    llm_usage: dict[str, Any] = field(default_factory=dict)
    diagnostics: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SQLComponent:
    component_type: str
    expression: str
    table: str | None = None
    alias: str | None = None
    column: str | None = None
    operator: str | None = None
    value: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SuspiciousUnit:
    kind: str
    sql_fragment: str
    reason: str
    oracle: PartialSemanticOracle | None = None
    component: SQLComponent | None = None


@dataclass(frozen=True)
class TestSpec:
    test_type: str
    oracle_predicate: dict[str, Any] | None = None
    candidate_predicate: dict[str, Any] | None = None
    grouping_key: dict[str, Any] | None = None
    threshold: int | None = None
    activation_conditions: list[dict[str, Any]] = field(default_factory=list)
    target_entity: dict[str, Any] | None = None
    candidate_aggregation: str | None = None
    oracle_aggregation: str | None = None
    join_path_hint: list[str] = field(default_factory=list)
    query_tables: list[dict[str, Any]] = field(default_factory=list)
    joins: list[dict[str, Any]] = field(default_factory=list)
    schema: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CounterexampleSlice:
    name: str
    test_type: str
    purpose: str
    tables: dict[str, list[dict[str, Any]]]
    test_spec: TestSpec | None = None
    schema: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Violation:
    kind: str
    message: str
    observed: Any
    expected: Any


@dataclass(frozen=True)
class RepairAction:
    kind: str
    before: str | None = None
    after: str | None = None
    target_alias: str | None = None
    target_table: str | None = None
    target_column: str | None = None
    replacement_alias: str | None = None
    replacement_table: str | None = None
    replacement_column: str | None = None
    value: str | None = None
    distinct_alias: str | None = None
    distinct_column: str | None = None


@dataclass(frozen=True)
class VerificationResult:
    passed: bool
    candidate_results: dict[str, list[dict[str, Any]]]
    violations: list[Violation]
    parses: bool = True


SemanticOracle = PartialSemanticOracle


def partial_semantic_oracle_from_record(
    oracle: PartialSemanticOracle | dict[str, Any],
) -> PartialSemanticOracle:
    """Coerce persisted oracle records into the runtime dataclass."""

    if isinstance(oracle, PartialSemanticOracle):
        return oracle
    fields = PartialSemanticOracle.__dataclass_fields__
    payload = {key: value for key, value in oracle.items() if key in fields}
    payload.setdefault("nl_span", "")
    payload.setdefault("confidence", 1.0)
    return PartialSemanticOracle(**payload)


def to_jsonable(value: Any) -> Any:
    """Convert dataclasses and nested containers into JSON-safe values."""

    if hasattr(value, "__dataclass_fields__"):
        return asdict(value)
    if isinstance(value, list):
        return [to_jsonable(item) for item in value]
    if isinstance(value, tuple):
        return [to_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {key: to_jsonable(item) for key, item in value.items()}
    return value
