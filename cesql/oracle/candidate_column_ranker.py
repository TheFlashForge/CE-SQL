"""Rank schema-grounded oracle candidates from safe inference inputs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from cesql.oracle.schema_grounding import (
    column_names,
    likely_identifier,
    primary_key,
    table_names,
    token_overlap_score,
    tokens,
)
from cesql.oracle.value_grounding import columns_containing_value
from cesql.sql.components import extract_sql_components


@dataclass(frozen=True)
class PredicateCandidate:
    table: str
    column: str
    value: str
    score: float
    reasons: list[str]
    source_alias: str | None = None


@dataclass(frozen=True)
class CountDistinctCandidate:
    entity_table: str
    id_column: str
    score: float
    reasons: list[str]
    source_alias: str | None = None


def propose_oracle_candidates(
    question: str,
    schema: dict[str, Any],
    candidate_sql: str,
    evidence: str | None = None,
    limit: int = 8,
) -> dict[str, Any]:
    """Return ranked predicate and count-distinct oracle candidates."""

    components = extract_sql_components(candidate_sql, schema=schema)
    query_tables = {
        component.table
        for component in components
        if component.component_type == "table_alias" and component.table
    }
    text = " ".join(item for item in [question, evidence or ""] if item)
    return {
        "predicate_candidates": [
            _candidate_payload(candidate)
            for candidate in _predicate_candidates(text, evidence or "", schema, components, query_tables, limit)
        ],
        "count_distinct_candidates": [
            _count_payload(candidate)
            for candidate in _count_candidates(question, schema, components, query_tables, limit)
        ],
    }


def _predicate_candidates(
    text: str,
    evidence: str,
    schema: dict[str, Any],
    components: list[Any],
    query_tables: set[str],
    limit: int,
) -> list[PredicateCandidate]:
    candidates: list[PredicateCandidate] = []
    predicates = [
        component
        for component in components
        if component.component_type == "where_predicate"
        and component.operator in {"=", "LIKE"}
        and component.value is not None
    ]
    for predicate in predicates:
        value = str(predicate.value).strip("'\"")
        if _text_confirms_predicate(evidence, predicate.table, predicate.column, value):
            continue
        scoped_tables = sorted(query_tables) if query_tables else table_names(schema, query_tables)
        value_matches = columns_containing_value(
            schema,
            value,
            tables=scoped_tables,
        )
        for table in scoped_tables:
            for column in column_names(schema, table):
                if table == predicate.table and column == predicate.column:
                    continue
                score = 0.0
                reasons: list[str] = []
                if (table, column) in value_matches:
                    score += 3.0
                    reasons.append("value_match")
                overlap = token_overlap_score(text, table, column)
                if overlap:
                    score += min(overlap, 2.0)
                    reasons.append("question_overlap")
                if table == predicate.table:
                    score += 0.5
                    reasons.append("same_table_neighbor")
                if table in query_tables:
                    score += 0.25
                    reasons.append("query_scope")
                if score <= 0:
                    continue
                candidates.append(
                    PredicateCandidate(
                        table=table,
                        column=column,
                        value=value,
                        score=round(score, 6),
                        reasons=sorted(set(reasons)),
                        source_alias=predicate.alias,
                    )
                )
    return _dedupe_predicate(candidates)[:limit]


def _count_candidates(
    question: str,
    schema: dict[str, Any],
    components: list[Any],
    query_tables: set[str],
    limit: int,
) -> list[CountDistinctCandidate]:
    if not _asks_entity_count(question):
        return []
    has_count_star = any(
        component.component_type == "aggregation"
        and component.expression.upper() in {"COUNT(*)", "COUNT(1)"}
        for component in components
    )
    has_join = any(component.component_type == "join" for component in components)
    if not (has_count_star and has_join):
        return []
    candidates = []
    text = " ".join(tokens(question))
    for table in table_names(schema, query_tables):
        pk = primary_key(schema, table)
        id_column = pk or next((column for column in column_names(schema, table) if likely_identifier(column)), None)
        if not id_column:
            continue
        score = 0.0
        reasons: list[str] = []
        if pk:
            score += 1.5
            reasons.append("primary_key")
        if table in query_tables:
            score += 1.0
            reasons.append("join_duplicate_risk")
        overlap = token_overlap_score(text, table, id_column)
        if overlap:
            score += min(overlap, 1.0)
            reasons.append("entity_mention")
        if score:
            candidates.append(
                CountDistinctCandidate(
                    entity_table=table,
                    id_column=id_column,
                    score=round(score, 6),
                    reasons=sorted(set(reasons)),
                    source_alias=_alias_for_table(table, components),
                )
            )
    return sorted(candidates, key=lambda item: (-item.score, item.entity_table, item.id_column))[:limit]


def _asks_entity_count(question: str) -> bool:
    lowered = question.lower()
    if "how many rows" in lowered or "how many records" in lowered:
        return False
    return "how many" in lowered or "number of" in lowered or "count of" in lowered


def _alias_for_table(table: str, components: list[Any]) -> str | None:
    aliases = [
        component.alias
        for component in components
        if component.component_type == "table_alias" and component.table == table
    ]
    return aliases[0] if len(aliases) == 1 else None


def _candidate_payload(candidate: PredicateCandidate) -> dict[str, Any]:
    return {
        "table": candidate.table,
        "column": candidate.column,
        "value": candidate.value,
        "score": candidate.score,
        "reasons": candidate.reasons,
        "source_alias": candidate.source_alias,
    }


def _count_payload(candidate: CountDistinctCandidate) -> dict[str, Any]:
    return {
        "entity_table": candidate.entity_table,
        "id_column": candidate.id_column,
        "score": candidate.score,
        "reasons": candidate.reasons,
        "source_alias": candidate.source_alias,
    }


def _dedupe_predicate(candidates: list[PredicateCandidate]) -> list[PredicateCandidate]:
    best: dict[tuple[str, str, str], PredicateCandidate] = {}
    for candidate in candidates:
        key = (candidate.table, candidate.column, candidate.value.lower())
        current = best.get(key)
        if current is None or candidate.score > current.score:
            best[key] = candidate
    return sorted(best.values(), key=lambda item: (-item.score, item.table, item.column, item.value))


def _text_confirms_predicate(
    text: str,
    table: str | None,
    column: str | None,
    value: str,
) -> bool:
    if not column or not value:
        return False
    normalized_text = _normalize_text(text)
    if not normalized_text:
        return False
    column_tokens = tokens(column)
    value_tokens = tokens(value)
    if not column_tokens or not value_tokens:
        return False
    table_tokens = tokens(table or "")
    has_column = all(token in normalized_text for token in column_tokens)
    has_value = all(token in normalized_text for token in value_tokens)
    has_table = not table_tokens or any(token in normalized_text for token in table_tokens)
    return has_column and has_value and has_table


def _normalize_text(text: str) -> set[str]:
    return set(tokens(text))
