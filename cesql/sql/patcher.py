"""Deterministic AST-local SQL patching for the running example."""

from __future__ import annotations

from typing import Any

import sqlglot
from sqlglot import exp

from cesql.core.types import RepairAction


def apply_repairs(
    sql: str, actions: list[RepairAction], schema: dict[str, Any] | None = None
) -> str:
    """Apply MVP repairs by locating and modifying sqlglot AST nodes."""

    tree = sqlglot.parse_one(sql, read="sqlite")
    action_kinds = {action.kind for action in actions}

    for action in actions:
        if action.kind == "ReplacePredicateColumn":
            _replace_predicate_column(tree, action, schema or {})
    if {"AddDistinctToCount", "ReplaceHavingCountWithDistinctCount"} & action_kinds:
        action = next(
            item
            for item in actions
            if item.kind in {"AddDistinctToCount", "ReplaceHavingCountWithDistinctCount"}
        )
        _add_distinct_student_count(tree, action)

    return _format_running_example_sql(tree)


def _replace_predicate_column(
    tree: exp.Expression, action: RepairAction, schema: dict[str, Any]
) -> None:
    """Replace a suspicious predicate column with the oracle-grounded column."""

    replacement_alias = _resolve_replacement_alias(tree, action)
    predicates = [*tree.find_all(exp.EQ), *tree.find_all(exp.Like)]
    for predicate in predicates:
        side = _candidate_column_side(predicate, action, schema, tree)
        if side == "this":
            predicate.set("this", exp.column(action.replacement_column, table=replacement_alias))
            predicate.set("expression", exp.Literal.string(_normalize_literal(action.value)))
            return
        if side == "expression":
            predicate.set(
                "expression",
                exp.column(action.replacement_column, table=replacement_alias),
            )
            predicate.set("this", exp.Literal.string(_normalize_literal(action.value)))
            return
    raise ValueError(f"Repair target not found: {action.before}")


def _add_distinct_student_count(tree: exp.Expression, action: RepairAction) -> None:
    """Replace MVP COUNT(*) nodes with COUNT(DISTINCT target_id)."""

    changed = False
    for count in tree.find_all(exp.Count):
        if isinstance(count.this, exp.Star) or _is_count_one(count):
            count.set(
                "this",
                exp.Distinct(
                    expressions=[
                        exp.column(action.distinct_column, table=action.distinct_alias)
                    ]
                ),
            )
            changed = True
    if not changed:
        raise ValueError("Repair target not found: COUNT(*)")


def _is_count_one(count: exp.Count) -> bool:
    return isinstance(count.this, exp.Literal) and count.this.this == "1"


def _candidate_column_side(
    predicate: exp.EQ,
    action: RepairAction,
    schema: dict[str, Any],
    tree: exp.Expression,
) -> str | None:
    left = predicate.this
    right = predicate.expression
    columns = list(predicate.find_all(exp.Column))
    if len(columns) != 1:
        return None
    if not (
        (_literal_matches(right, action.value) and isinstance(left, exp.Column))
        or (_literal_matches(left, action.value) and isinstance(right, exp.Column))
    ):
        return None
    if isinstance(left, exp.Column) and _column_matches(left, action, schema, tree):
        return "this"
    if isinstance(right, exp.Column) and _column_matches(right, action, schema, tree):
        return "expression"
    return None


def _column_matches(
    column: exp.Column,
    action: RepairAction,
    schema: dict[str, Any],
    tree: exp.Expression,
) -> bool:
    if column.name != action.target_column:
        return False
    aliases = _alias_map(tree)
    if column.table:
        if action.target_alias and column.table == action.target_alias:
            return True
        return bool(action.target_table and aliases.get(column.table) == action.target_table)
    table = _unqualified_column_table(column.name, aliases, schema)
    if table is None:
        return False
    return table == action.target_table


def _literal_matches(expression: exp.Expression | None, value: str | None) -> bool:
    if not isinstance(expression, exp.Literal):
        return False
    return _normalize_literal(expression.this) == _normalize_literal(value)


def _normalize_literal(value: object) -> str:
    text = str(value or "").strip()
    previous = None
    while text != previous:
        previous = text
        text = text.strip().strip("'\"")
    return text


def _resolve_replacement_alias(
    tree: exp.Expression, action: RepairAction
) -> str | None:
    aliases = _alias_map(tree)
    if action.replacement_alias and action.replacement_alias in aliases:
        return action.replacement_alias
    if action.replacement_table:
        candidates = [
            alias for alias, table in aliases.items() if table == action.replacement_table
        ]
        if len(candidates) == 1:
            return candidates[0]
        if not candidates:
            raise ValueError(
                f"Unsupported repair: target_table_not_in_query_scope: {action.replacement_table}"
            )
        raise ValueError(
            f"Unsupported repair: target_alias_unresolved: {action.replacement_table}"
        )
    if action.replacement_alias:
        raise ValueError(
            f"Unsupported repair: target_alias_unresolved: {action.replacement_alias}"
        )
    return None


def _alias_map(tree: exp.Expression) -> dict[str, str]:
    return {
        table.alias_or_name: table.name
        for table in tree.find_all(exp.Table)
    }


def _unqualified_column_table(
    column: str, aliases: dict[str, str], schema: dict[str, Any]
) -> str | None:
    candidates = [
        table
        for table in aliases.values()
        if column in schema.get("tables", {}).get(table, {}).get("columns", {})
    ]
    return candidates[0] if len(candidates) == 1 else None


def _format_running_example_sql(tree: exp.Expression) -> str:
    """Render the patched AST in the stable format expected by the MVP."""

    sql = tree.sql(dialect="sqlite")
    for table, alias in (
        ("students", "s"),
        ("departments", "d"),
        ("enrollments", "e"),
        ("courses", "c"),
    ):
        sql = sql.replace(f"{table} AS {alias}", f"{table} {alias}")

    sql = sql.replace(" FROM ", "\nFROM ")
    sql = sql.replace(" JOIN ", "\nJOIN ")
    sql = sql.replace(" WHERE ", "\nWHERE ")
    sql = sql.replace(" AND ", "\n  AND ")
    sql = sql.replace(" GROUP BY ", "\nGROUP BY ")
    sql = sql.replace(" HAVING ", "\nHAVING ")
    return f"{sql};\n"
