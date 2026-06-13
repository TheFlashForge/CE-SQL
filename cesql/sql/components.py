"""Reusable SQL component extraction based on sqlglot AST traversal."""

from __future__ import annotations

from typing import Any, Iterable

import sqlglot
from sqlglot import exp

from cesql.core.types import SQLComponent


def extract_sql_components(sql: str, schema: dict[str, Any] | None = None) -> list[SQLComponent]:
    """Extract predicates, aggregations, grouping, joins, and aliases."""

    tree = sqlglot.parse_one(sql, read="sqlite")
    aliases = _extract_aliases(tree)
    resolver = _ColumnResolver(aliases, schema or {})
    components: list[SQLComponent] = []

    components.extend(
        SQLComponent(
            component_type="table_alias",
            expression=f"{table} AS {alias}",
            table=table,
            alias=alias,
        )
        for alias, table in aliases.items()
    )
    from_table = tree.args.get("from")
    if from_table is not None and isinstance(from_table.this, exp.Table):
        table = from_table.this
        components.append(
            SQLComponent(
                component_type="from",
                expression=table.sql(dialect="sqlite"),
                table=table.name,
                alias=table.alias_or_name,
            )
        )
    components.extend(_extract_join_components(tree))
    components.extend(
        _extract_predicate_components(tree.args.get("where"), "where_predicate", resolver)
    )
    components.extend(_extract_aggregation_components(tree))
    components.extend(_extract_group_by_components(tree, resolver))
    components.extend(
        _extract_predicate_components(tree.args.get("having"), "having_predicate", resolver)
    )
    return components


def _extract_aliases(tree: exp.Expression) -> dict[str, str]:
    aliases: dict[str, str] = {}
    for table in tree.find_all(exp.Table):
        table_name = table.name
        alias = table.alias_or_name
        aliases[alias] = table_name
    return aliases


def _extract_join_components(tree: exp.Expression) -> list[SQLComponent]:
    components: list[SQLComponent] = []
    for join in tree.find_all(exp.Join):
        table = join.this
        if not isinstance(table, exp.Table):
            continue
        components.append(
            SQLComponent(
                component_type="join",
                expression=join.sql(dialect="sqlite"),
                table=table.name,
                alias=table.alias_or_name,
                metadata={"on": join.args.get("on").sql(dialect="sqlite") if join.args.get("on") else None},
            )
        )
    return components


def _extract_predicate_components(
    clause: exp.Expression | None, component_type: str, resolver: "_ColumnResolver"
) -> list[SQLComponent]:
    if clause is None:
        return []
    root = clause.this if isinstance(clause, (exp.Where, exp.Having)) else clause
    return [
        _predicate_component(predicate, component_type, resolver)
        for predicate in _split_and(root)
    ]


def _extract_aggregation_components(tree: exp.Expression) -> list[SQLComponent]:
    return [
        SQLComponent(component_type="aggregation", expression=count.sql(dialect="sqlite"))
        for count in tree.find_all(exp.Count)
    ]


def _extract_group_by_components(
    tree: exp.Expression, resolver: "_ColumnResolver"
) -> list[SQLComponent]:
    group = tree.args.get("group")
    if group is None:
        return []
    return [
        _column_component(expression, "group_by", resolver)
        if isinstance(expression, exp.Column)
        else SQLComponent(component_type="group_by", expression=expression.sql(dialect="sqlite"))
        for expression in group.expressions
    ]


def _split_and(expression: exp.Expression) -> Iterable[exp.Expression]:
    if isinstance(expression, exp.And):
        yield from _split_and(expression.left)
        yield from _split_and(expression.right)
    else:
        yield expression


def _predicate_component(
    predicate: exp.Expression, component_type: str, resolver: "_ColumnResolver"
) -> SQLComponent:
    operator = _operator(predicate)
    left = predicate.left if hasattr(predicate, "left") else predicate.args.get("this")
    right = predicate.right if hasattr(predicate, "right") else predicate.args.get("expression")
    value = _predicate_value(predicate, right)
    if isinstance(left, exp.Column):
        table = resolver.table_for(left)
        return SQLComponent(
            component_type=component_type,
            expression=predicate.sql(dialect="sqlite"),
            table=table,
            alias=left.table or resolver.alias_for(left),
            column=left.name,
            operator=operator,
            value=value,
        )
    if isinstance(right, exp.Column):
        table = resolver.table_for(right)
        return SQLComponent(
            component_type=component_type,
            expression=predicate.sql(dialect="sqlite"),
            table=table,
            alias=right.table or resolver.alias_for(right),
            column=right.name,
            operator=operator,
            value=_literal_value(left),
            metadata={"reversed": True},
        )
    wrapped_column = _single_column(left if left is not None else predicate.args.get("this"))
    if wrapped_column is not None:
        table = resolver.table_for(wrapped_column)
        return SQLComponent(
            component_type=component_type,
            expression=predicate.sql(dialect="sqlite"),
            table=table,
            alias=wrapped_column.table or resolver.alias_for(wrapped_column),
            column=wrapped_column.name,
            operator=operator,
            value=value,
            metadata={"wrapped_expression": (left or predicate.args.get("this")).sql(dialect="sqlite")},
        )
    return SQLComponent(
        component_type=component_type,
        expression=predicate.sql(dialect="sqlite"),
        operator=operator,
        value=value,
    )


def _column_component(
    column: exp.Column, component_type: str, resolver: "_ColumnResolver"
) -> SQLComponent:
    return SQLComponent(
        component_type=component_type,
        expression=column.sql(dialect="sqlite"),
        table=resolver.table_for(column),
        alias=column.table or resolver.alias_for(column),
        column=column.name,
    )


def _operator(predicate: exp.Expression) -> str | None:
    if isinstance(predicate, exp.EQ):
        return "="
    if isinstance(predicate, exp.Like):
        return "LIKE"
    if isinstance(predicate, exp.GTE):
        return ">="
    if isinstance(predicate, exp.GT):
        return ">"
    if isinstance(predicate, exp.LT):
        return "<"
    if isinstance(predicate, exp.LTE):
        return "<="
    if isinstance(predicate, exp.Between):
        return "BETWEEN"
    if isinstance(predicate, exp.Is):
        return "IS"
    return predicate.key.upper() if predicate.key else None


def _predicate_value(predicate: exp.Expression, right: exp.Expression | None) -> str | int | float | None:
    if isinstance(predicate, exp.Between):
        low = _literal_value(predicate.args.get("low"))
        high = _literal_value(predicate.args.get("high"))
        return f"{low} AND {high}" if high is not None else low
    return _literal_value(right)


def _literal_value(expression: exp.Expression | None) -> str | int | float | None:
    if isinstance(expression, exp.Literal):
        return expression.this
    if isinstance(expression, exp.Null):
        return None
    return expression.sql(dialect="sqlite") if expression is not None else None


def _single_column(expression: exp.Expression | None) -> exp.Column | None:
    if expression is None:
        return None
    columns = list(expression.find_all(exp.Column))
    return columns[0] if len(columns) == 1 else None


class _ColumnResolver:
    def __init__(self, aliases: dict[str, str], schema: dict[str, Any]) -> None:
        self.aliases = aliases
        self.schema = schema

    def table_for(self, column: exp.Column) -> str | None:
        if column.table:
            return self.aliases.get(column.table)
        candidates = [
            table
            for table in self.aliases.values()
            if column.name in self.schema.get("tables", {}).get(table, {}).get("columns", {})
        ]
        return candidates[0] if len(candidates) == 1 else None

    def alias_for(self, column: exp.Column) -> str | None:
        if column.table:
            return column.table
        table = self.table_for(column)
        if table is None:
            return None
        aliases = [alias for alias, alias_table in self.aliases.items() if alias_table == table]
        return aliases[0] if len(aliases) == 1 else None
