"""Adapt canonical oracles to aliases in a candidate SQL query."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from cesql.core.types import PartialSemanticOracle
from cesql.sql.components import extract_sql_components


def adapt_oracles_to_sql_scope(
    oracles: list[PartialSemanticOracle],
    candidate_sql: str,
    schema: dict[str, Any] | None = None,
) -> tuple[list[PartialSemanticOracle], list[dict[str, Any]]]:
    """Attach query aliases to canonical table-based oracles when safe."""

    components = extract_sql_components(candidate_sql, schema=schema)
    table_aliases: dict[str, list[str]] = {}
    for component in components:
        if component.component_type == "table_alias" and component.table and component.alias:
            table_aliases.setdefault(component.table, []).append(component.alias)

    adapted: list[PartialSemanticOracle] = []
    logs: list[dict[str, Any]] = []
    for oracle in oracles:
        table = _oracle_table(oracle)
        if not table:
            adapted.append(replace(oracle, adapter_status="adapter_success"))
            logs.append({"status": "adapter_success", "oracle": oracle})
            continue
        aliases = table_aliases.get(table, [])
        if oracle.target_alias and oracle.target_alias in aliases:
            adapted.append(
                replace(
                    oracle,
                    adapted_alias=oracle.target_alias,
                    adapter_status="adapter_success",
                )
            )
            logs.append({"status": "adapter_success", "oracle": oracle})
            continue
        if len(aliases) == 1:
            alias = aliases[0]
            adapted_oracle = replace(
                oracle,
                target_alias=alias,
                adapted_alias=alias,
                adapter_status="adapter_success",
            )
            adapted.append(adapted_oracle)
            logs.append(
                {
                    "status": "adapter_success",
                    "table": table,
                    "alias": alias,
                    "oracle": oracle,
                }
            )
            continue
        if len(aliases) > 1:
            logs.append(
                {
                    "status": "adapter_ambiguous_alias",
                    "table": table,
                    "aliases": aliases,
                    "oracle": oracle,
                }
            )
        else:
            logs.append(
                {
                    "status": "adapter_table_not_in_query",
                    "table": table,
                    "oracle": oracle,
                }
            )
    return adapted, logs


def _oracle_table(oracle: PartialSemanticOracle) -> str | None:
    if oracle.oracle_type == "predicate_grounding":
        return oracle.target_table
    if oracle.oracle_type == "count_distinct":
        return oracle.target_entity
    return None
