"""Detect suspicious SQL units by comparing oracles and components."""

from __future__ import annotations

from cesql.core.types import PartialSemanticOracle, SQLComponent, SuspiciousUnit


def detect_suspicious_units(
    oracles: list[PartialSemanticOracle], components: list[SQLComponent]
) -> list[SuspiciousUnit]:
    """Detect the two supported MVP suspicious-unit types."""

    units: list[SuspiciousUnit] = []
    for oracle in oracles:
        if oracle.oracle_type == "predicate_grounding":
            units.extend(_detect_predicate_grounding(oracle, components))
        elif oracle.oracle_type == "count_distinct":
            unit = _detect_count_distinct(oracle, components)
            if unit is not None:
                units.append(unit)
    return units


def _detect_predicate_grounding(
    oracle: PartialSemanticOracle, components: list[SQLComponent]
) -> list[SuspiciousUnit]:
    units: list[SuspiciousUnit] = []
    for component in components:
        if component.component_type != "where_predicate":
            continue
        same_value = (
            _normalize_value(component.value) == _normalize_value(oracle.value)
            and component.operator == oracle.operator
        )
        same_target = (
            component.column == oracle.target_column
            and (
                (component.table is not None and component.table == oracle.target_table)
                or (
                    component.table is None
                    and component.alias is not None
                    and component.alias == oracle.target_alias
                )
            )
        )
        if same_value and not same_target:
            units.append(
                SuspiciousUnit(
                    kind="predicate_grounding_mismatch",
                    sql_fragment=component.expression,
                    reason="Predicate value matches the oracle but is grounded on another column",
                    oracle=oracle,
                    component=component,
                )
            )
    return units


def _normalize_value(value: object) -> str:
    text = str(value or "").strip()
    previous = None
    while text != previous:
        previous = text
        text = text.strip().strip("'\"")
    return " ".join(text.lower().split())


def _detect_count_distinct(
    oracle: PartialSemanticOracle, components: list[SQLComponent]
) -> SuspiciousUnit | None:
    has_count_star = any(
        component.component_type == "aggregation"
        and component.expression.upper() in {"COUNT(*)", "COUNT(1)"}
        for component in components
    )
    tables = {
        component.table
        for component in components
        if component.component_type in {"table_alias", "join"}
    }
    has_join = any(component.component_type == "join" for component in components)
    target_in_query = oracle.target_entity in tables
    if has_count_star and has_join and target_in_query:
        return SuspiciousUnit(
            kind="possible_duplicate_counting",
            sql_fragment="COUNT(*)",
            reason="COUNT(*) can count joined rows instead of distinct students",
            oracle=oracle,
            component=next(
                component
                for component in components
                if component.component_type == "aggregation"
                and component.expression.upper() in {"COUNT(*)", "COUNT(1)"}
            )
        )
    return None
