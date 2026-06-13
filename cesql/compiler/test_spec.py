"""Compile suspicious units into reusable test specifications."""

from __future__ import annotations

from cesql.core.types import SQLComponent, SuspiciousUnit, TestSpec


def compile_test_specs(
    suspicious_units: list[SuspiciousUnit],
    components: list[SQLComponent],
    schema: dict | None = None,
) -> list[TestSpec]:
    """Compile detected suspicious units into deterministic test specs."""

    specs: list[TestSpec] = []
    for unit in suspicious_units:
        if unit.kind == "predicate_grounding_mismatch":
            specs.append(_predicate_contrast_spec(unit, components, schema or {}))
        elif unit.kind == "possible_duplicate_counting":
            specs.append(_count_distinct_spec(unit, components, schema or {}))
    return specs


def _predicate_contrast_spec(
    unit: SuspiciousUnit, components: list[SQLComponent], schema: dict
) -> TestSpec:
    oracle = unit.oracle
    candidate = unit.component
    if oracle is None or candidate is None:
        raise ValueError("Predicate suspicious unit is missing oracle or component")
    oracle_alias = _alias_for_table(oracle.target_table, components) or oracle.target_alias
    return TestSpec(
        test_type="predicate_contrast",
        oracle_predicate={
            "table": oracle.target_table,
            "alias": oracle_alias,
            "column": oracle.target_column,
            "operator": oracle.operator,
            "value": oracle.value,
        },
        candidate_predicate={
            "table": candidate.table or _table_for_alias(candidate.alias, components),
            "alias": candidate.alias,
            "column": candidate.column,
            "operator": candidate.operator,
            "value": candidate.value,
        },
        candidate_aggregation=_first_count_aggregation(components),
        grouping_key=_first_grouping_key(components),
        threshold=_having_threshold(components),
        activation_conditions=_activation_conditions(
            components,
            exclude=candidate,
            allowed_operators={"=", "LIKE", "BETWEEN", "<", "<=", ">", ">=", "IS"},
        ),
        target_entity=_target_entity_from_oracle(oracle, schema, oracle_alias),
        query_tables=_query_tables(components),
        joins=_joins(components),
        schema=schema,
    )


def _count_distinct_spec(
    unit: SuspiciousUnit, components: list[SQLComponent], schema: dict
) -> TestSpec:
    oracle = unit.oracle
    if oracle is None:
        raise ValueError("Count suspicious unit is missing oracle")
    return TestSpec(
        test_type="count_distinct_contrast",
        target_entity={
            "table": oracle.target_entity,
            "alias": oracle.target_alias,
            "id_column": oracle.target_id_column,
        },
        candidate_aggregation=unit.sql_fragment,
        oracle_aggregation=oracle.expected_aggregation,
        join_path_hint=_joined_table_names(components),
        activation_conditions=_activation_conditions(components, allowed_operators={"LIKE"}),
        oracle_predicate=_oracle_predicate_from_oracle(oracle, components),
        grouping_key=_first_grouping_key(components),
        threshold=_having_threshold(components),
        query_tables=_query_tables(components),
        joins=_joins(components),
        schema=schema,
    )


def _activation_conditions(
    components: list[SQLComponent],
    exclude: SQLComponent | None = None,
    allowed_operators: set[str] | None = None,
) -> list[dict[str, str | None]]:
    conditions = []
    allowed = allowed_operators or {"LIKE"}
    for component in components:
        if component.component_type != "where_predicate" or component == exclude:
            continue
        if component.operator == "IS" and "IS" in allowed and component.column:
            conditions.append(_predicate_dict(component, components))
        elif component.operator in allowed and component.column and component.value is not None:
            conditions.append(_predicate_dict(component, components))
    return conditions


def _oracle_predicate_from_oracle(
    oracle, components: list[SQLComponent]
) -> dict[str, str | None] | None:
    predicate = next(
        (
            component
            for component in components
            if component.component_type == "where_predicate"
            and component.alias == oracle.target_alias
        ),
        None,
    )
    if predicate is not None:
        return _predicate_dict(predicate, components)
    if oracle.target_alias and oracle.target_column and oracle.value:
        return {
            "table": _table_for_alias(oracle.target_alias, components),
            "alias": oracle.target_alias,
            "column": oracle.target_column,
            "operator": oracle.operator or "=",
            "value": oracle.value,
        }
    return None


def _target_entity_from_oracle(
    oracle, schema: dict, alias: str | None = None
) -> dict[str, str | None]:
    table = oracle.target_table
    primary_key = None
    if table:
        primary_key = next(iter(schema.get("tables", {}).get(table, {}).get("primary_key", [])), None)
    return {"table": table, "alias": alias or oracle.target_alias, "id_column": primary_key}


def _first_grouping_key(components: list[SQLComponent]) -> dict[str, str | None] | None:
    group = next((component for component in components if component.component_type == "group_by"), None)
    if group is None:
        return None
    return {
        "table": group.table or _table_for_alias(group.alias, components),
        "alias": group.alias,
        "column": group.column,
    }


def _having_threshold(components: list[SQLComponent]) -> int | None:
    for component in components:
        if component.component_type == "having_predicate" and component.operator == ">=":
            return int(component.value) if component.value is not None else None
    return None


def _predicate_dict(
    component: SQLComponent, components: list[SQLComponent]
) -> dict[str, object]:
    payload = {
        "table": component.table or _table_for_alias(component.alias, components),
        "alias": component.alias,
        "column": component.column,
        "operator": component.operator,
        "value": component.value,
    }
    if component.metadata.get("wrapped_expression"):
        payload["wrapped_expression"] = component.metadata["wrapped_expression"]
    return payload


def _first_count_aggregation(components: list[SQLComponent]) -> str | None:
    for component in components:
        if component.component_type == "aggregation":
            return component.expression
    return None


def _table_for_alias(alias: str | None, components: list[SQLComponent]) -> str | None:
    for component in components:
        if component.component_type == "table_alias" and component.alias == alias:
            return component.table
    return None


def _alias_for_table(table: str | None, components: list[SQLComponent]) -> str | None:
    aliases = [
        component.alias
        for component in components
        if component.component_type == "table_alias" and component.table == table
    ]
    return aliases[0] if len(aliases) == 1 else None


def _query_tables(components: list[SQLComponent]) -> list[dict[str, str | None]]:
    return [
        {"table": component.table, "alias": component.alias}
        for component in components
        if component.component_type == "table_alias"
    ]


def _joins(components: list[SQLComponent]) -> list[dict[str, str | None]]:
    return [
        {
            "table": component.table,
            "alias": component.alias,
            "on": component.metadata.get("on"),
        }
        for component in components
        if component.component_type == "join"
    ]


def _joined_table_names(components: list[SQLComponent]) -> list[str]:
    return [
        component.table
        for component in components
        if component.component_type in {"table_alias", "join"} and component.table is not None
    ]
