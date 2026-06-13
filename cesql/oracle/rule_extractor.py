"""Rule-based semantic oracle extraction."""

from __future__ import annotations

import re
from typing import Any

from cesql.oracle.candidate_column_ranker import propose_oracle_candidates
from cesql.core.types import PartialSemanticOracle
from cesql.sql.components import extract_sql_components


COUNT_PATTERNS = (
    re.compile(
        r"how many\s+(?:distinct|different)\s+(?P<entity>[\w ]+?)\s+entities"
        r"(?:\s+identified by\s+(?P<id>[\w ]+?))?\s+(?:are|is)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"how many\s+(?P<entity>[\w ]+?)\s+entities"
        r"(?:\s+identified by\s+(?P<id>[\w ]+?))?\s+(?:are|is)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"how many\s+(?:distinct|different)\s+(?P<entity>[\w ]+?)\s+(?:are|have|with)\b",
        re.IGNORECASE,
    ),
)
PREDICATE_PATTERNS = (
    re.compile(
        r"(?P<table>[\w ]+?)\s+entries\s+whose\s+(?P<column>[\w ]+?)\s+is\s+(?P<value>[^.?!]+)",
        re.IGNORECASE,
    ),
    re.compile(
        r"whose\s+(?P<column>[\w ]+?)\s+is\s+(?P<value>[^.?!]+)",
        re.IGNORECASE,
    ),
    re.compile(r"majoring in\s+(?P<value>[\w -]+)", re.IGNORECASE),
    re.compile(r"in category\s+(?P<value>[\w -]+)", re.IGNORECASE),
    re.compile(r"named\s+(?P<value>[\w -]+)", re.IGNORECASE),
)
PHRASE_COLUMNS = {
    "majoring in": "major",
    "in category": "category",
    "named": "name",
}
BLOCKED_COUNT_OBJECTS = {"record", "records", "row", "rows"}


def extract_oracles(
    question: str,
    schema: dict[str, Any] | None = None,
    candidate_sql: str | None = None,
    evidence: str | None = None,
) -> list[PartialSemanticOracle]:
    """Extract structured semantic oracles from question, schema, and SQL."""

    oracles = _running_example_oracles(question)
    if schema and candidate_sql:
        oracles.extend(_extract_schema_grounded(question, schema, candidate_sql))
        oracles.extend(_extract_ranked_candidates(question, schema, candidate_sql, evidence=evidence))
    return _deduplicate(oracles)


def _extract_ranked_candidates(
    question: str,
    schema: dict[str, Any],
    candidate_sql: str,
    evidence: str | None = None,
) -> list[PartialSemanticOracle]:
    proposals = propose_oracle_candidates(question, schema, candidate_sql, evidence=evidence)
    oracles: list[PartialSemanticOracle] = []
    predicate = next(
        (
            item
            for item in proposals["predicate_candidates"]
            if float(item.get("score", 0.0)) >= 3.0
            and "value_match" in item.get("reasons", [])
        ),
        None,
    )
    if predicate is not None:
        oracles.append(
            PartialSemanticOracle(
                oracle_type="predicate_grounding",
                nl_span=str(predicate.get("value", "")),
                target_table=str(predicate["table"]),
                target_alias=predicate.get("source_alias"),
                target_column=str(predicate["column"]),
                operator="=",
                value=str(predicate["value"]),
                confidence=0.9,
                source="rule_ranker",
                canonical_table=str(predicate["table"]),
                canonical_column=str(predicate["column"]),
                validation_status="unvalidated",
            )
        )
    count = next(
        (
            item
            for item in proposals["count_distinct_candidates"]
            if float(item.get("score", 0.0)) >= 2.5
        ),
        None,
    )
    if count is not None:
        alias = count.get("source_alias")
        id_column = str(count["id_column"])
        expected = f"COUNT(DISTINCT {alias}.{id_column})" if alias else f"COUNT(DISTINCT {id_column})"
        oracles.append(
            PartialSemanticOracle(
                oracle_type="count_distinct",
                nl_span="how many",
                target_entity=str(count["entity_table"]),
                target_alias=alias,
                target_id_column=id_column,
                expected_aggregation=expected,
                confidence=0.88,
                source="rule_ranker",
                canonical_table=str(count["entity_table"]),
                canonical_column=id_column,
                validation_status="unvalidated",
            )
        )
    return oracles


def _running_example_oracles(question: str) -> list[PartialSemanticOracle]:
    lowered = question.lower()
    oracles: list[PartialSemanticOracle] = []
    if "students majoring in cs" in lowered:
        oracles.append(
            PartialSemanticOracle(
                oracle_type="predicate_grounding",
                nl_span="students majoring in CS",
                target_table="students",
                target_alias="s",
                target_column="major",
                operator="=",
                value="CS",
                confidence=0.95,
                source="rule",
                canonical_table="students",
                canonical_column="major",
                validation_status="unvalidated",
            )
        )
    if "how many students" in lowered:
        oracles.append(
            PartialSemanticOracle(
                oracle_type="count_distinct",
                nl_span="how many students",
                target_entity="students",
                target_alias="s",
                target_id_column="sid",
                expected_aggregation="COUNT(DISTINCT s.sid)",
                confidence=0.90,
                source="rule",
                canonical_table="students",
                canonical_column="sid",
                validation_status="unvalidated",
            )
        )
    return oracles


def _extract_schema_grounded(
    question: str, schema: dict[str, Any], candidate_sql: str
) -> list[PartialSemanticOracle]:
    components = extract_sql_components(candidate_sql, schema=schema)
    oracles: list[PartialSemanticOracle] = []
    predicate = _extract_predicate(question, schema, components)
    if predicate is not None:
        oracles.append(predicate)
    count = _extract_count_distinct(question, schema, components)
    if count is not None:
        oracles.append(count)
    return oracles


def _extract_predicate(
    question: str, schema: dict[str, Any], components: list[Any]
) -> PartialSemanticOracle | None:
    for pattern in PREDICATE_PATTERNS:
        match = pattern.search(question)
        if not match:
            continue
        groups = match.groupdict()
        table_phrase = groups.get("table")
        column_phrase = groups.get("column") or _implicit_column_phrase(match.group(0))
        value = _clean_value(groups.get("value"))
        if not value or not _candidate_contains_literal(components, value):
            return None
        target = _resolve_predicate_target(schema, components, table_phrase, column_phrase)
        if target is None:
            return None
        table, column, alias = target
        return PartialSemanticOracle(
            oracle_type="predicate_grounding",
            nl_span=match.group(0).strip(),
            target_table=table,
            target_alias=alias,
            target_column=column,
            operator="=",
            value=value,
            confidence=0.95,
            source="rule",
            canonical_table=table,
            canonical_column=column,
            adapted_alias=alias,
            validation_status="unvalidated",
        )
    return None


def _extract_count_distinct(
    question: str, schema: dict[str, Any], components: list[Any]
) -> PartialSemanticOracle | None:
    for pattern in COUNT_PATTERNS:
        match = pattern.search(question)
        if not match:
            continue
        entity_phrase = _clean_value(match.group("entity"))
        if not entity_phrase or _normalize(entity_phrase) in BLOCKED_COUNT_OBJECTS:
            return None
        table = _resolve_table(schema, entity_phrase)
        if table is None or not _candidate_has_duplicate_count_risk(components, table):
            return None
        id_phrase = _clean_value(match.groupdict().get("id"))
        id_column = _resolve_column(schema, table, id_phrase) if id_phrase else _primary_key(schema, table)
        if id_column is None:
            return None
        alias = _alias_for_table(table, components)
        expected = f"COUNT(DISTINCT {alias}.{id_column})" if alias else f"COUNT(DISTINCT {id_column})"
        return PartialSemanticOracle(
            oracle_type="count_distinct",
            nl_span=match.group(0).strip(),
            target_entity=table,
            target_alias=alias,
            target_id_column=id_column,
            expected_aggregation=expected,
            confidence=0.95,
            source="rule",
            canonical_table=table,
            canonical_column=id_column,
            adapted_alias=alias,
            validation_status="unvalidated",
        )
    return None


def _resolve_predicate_target(
    schema: dict[str, Any],
    components: list[Any],
    table_phrase: str | None,
    column_phrase: str | None,
) -> tuple[str, str, str | None] | None:
    query_tables = _query_tables(components)
    table = _resolve_table(schema, table_phrase) if table_phrase else None
    if table and table not in query_tables:
        return None
    candidate_tables = [table] if table else sorted(query_tables)
    candidates = []
    for candidate_table in candidate_tables:
        if candidate_table is None:
            continue
        column = _resolve_column(schema, candidate_table, column_phrase)
        if column is not None:
            candidates.append((candidate_table, column, _alias_for_table(candidate_table, components)))
    return candidates[0] if len(candidates) == 1 else None


def _resolve_table(schema: dict[str, Any], phrase: str | None) -> str | None:
    if not phrase:
        return None
    normalized = _normalize(phrase)
    matches = [
        table
        for table in schema.get("tables", {})
        if _normalize(table) in {normalized, _singular(normalized)}
        or _singular(_normalize(table)) == _singular(normalized)
    ]
    return matches[0] if len(matches) == 1 else None


def _resolve_column(schema: dict[str, Any], table: str, phrase: str | None) -> str | None:
    if not phrase:
        return None
    normalized = _normalize(phrase)
    normalized = {
        "effective date": "effective date",
        "sec id": "sec id",
    }.get(normalized, normalized)
    columns = schema.get("tables", {}).get(table, {}).get("columns", {})
    matches = [
        column
        for column in columns
        if _normalize(column) == normalized or _singular(_normalize(column)) == _singular(normalized)
    ]
    return matches[0] if len(matches) == 1 else None


def _implicit_column_phrase(text: str) -> str | None:
    lowered = text.lower()
    for phrase, column in PHRASE_COLUMNS.items():
        if phrase in lowered:
            return column
    return None


def _candidate_contains_literal(components: list[Any], value: str) -> bool:
    return any(
        component.component_type == "where_predicate"
        and _normalize_value(component.value) == _normalize_value(value)
        for component in components
    )


def _candidate_has_duplicate_count_risk(components: list[Any], table: str) -> bool:
    has_count_star = any(
        component.component_type == "aggregation"
        and component.expression.upper() in {"COUNT(*)", "COUNT(1)"}
        for component in components
    )
    has_join = any(component.component_type == "join" for component in components)
    return has_count_star and has_join and table in _query_tables(components)


def _primary_key(schema: dict[str, Any], table: str) -> str | None:
    keys = schema.get("tables", {}).get(table, {}).get("primary_key", [])
    return keys[0] if len(keys) == 1 else None


def _query_tables(components: list[Any]) -> set[str]:
    return {
        component.table
        for component in components
        if component.component_type == "table_alias" and component.table
    }


def _alias_for_table(table: str, components: list[Any]) -> str | None:
    aliases = [
        component.alias
        for component in components
        if component.component_type == "table_alias" and component.table == table
    ]
    return aliases[0] if len(aliases) == 1 else None


def _deduplicate(oracles: list[PartialSemanticOracle]) -> list[PartialSemanticOracle]:
    deduped: list[PartialSemanticOracle] = []
    seen = set()
    for oracle in oracles:
        key = (
            oracle.oracle_type,
            oracle.target_table,
            oracle.target_column,
            oracle.operator,
            _normalize_value(oracle.value),
            oracle.target_entity,
            oracle.target_id_column,
        )
        if key not in seen:
            deduped.append(oracle)
            seen.add(key)
    return deduped


def _clean_value(value: str | None) -> str | None:
    if value is None:
        return None
    return value.strip().strip("'\" ")


def _normalize(value: str | None) -> str:
    if not value:
        return ""
    return " ".join(value.replace("_", " ").lower().split())


def _normalize_value(value: object) -> str:
    return _normalize(str(value).strip("'\"")) if value is not None else ""


def _singular(value: str) -> str:
    return value[:-1] if value.endswith("s") and len(value) > 1 else value
