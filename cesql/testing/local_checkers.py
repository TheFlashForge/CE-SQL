"""Local semantic checkers keyed by test specification type."""

from __future__ import annotations

from typing import Any

import sqlglot
from sqlglot import exp

from cesql.core.types import CounterexampleSlice, TestSpec, Violation
from cesql.sql.execution import execute_sql


def check_predicate_slice(sql: str, data_slice: CounterexampleSlice) -> Violation | None:
    """Compare candidate output with the local predicate-grounding oracle."""

    spec = _require_spec(data_slice)
    observed = execute_sql(sql, data_slice)
    expected = execute_sql(_predicate_oracle_sql(sql, spec), data_slice)
    if not _same_rows(observed, expected):
        return Violation(
            kind="predicate_grounding_mismatch",
            message="Predicate slice exposes candidate grounding versus oracle grounding",
            observed=observed,
            expected=expected,
        )
    return None


def check_count_distinct_slice(sql: str, data_slice: CounterexampleSlice) -> Violation | None:
    """Check whether joined rows outnumber distinct target entities."""

    spec = _require_spec(data_slice)
    observed_count_rows = (
        execute_sql(_oracle_sql(spec, "COUNT(*)"), data_slice)
        if "COUNT(*)" in sql.upper() or "COUNT(1)" in sql.upper()
        else execute_sql(sql, data_slice)
    )
    expected = execute_sql(_oracle_sql(spec, spec.oracle_aggregation), data_slice)
    if not _same_rows(observed_count_rows, expected):
        return Violation(
            kind="duplicate_counting",
            message="Count-distinct slice exposes 3 enrollment rows versus 2 students",
            observed=observed_count_rows,
            expected=expected,
        )
    return None


def run_local_checkers(
    sql: str, slices: list[CounterexampleSlice]
) -> tuple[list[Violation], dict[str, list[dict[str, Any]]]]:
    """Execute SQL on every slice and run the slice-specific semantic checks."""

    violations: list[Violation] = []
    candidate_results: dict[str, list[dict[str, Any]]] = {}
    for data_slice in slices:
        candidate_results[data_slice.name] = execute_sql(sql, data_slice)
        if data_slice.test_type == "predicate_contrast":
            violation = check_predicate_slice(sql, data_slice)
        elif data_slice.test_type == "count_distinct_contrast":
            violation = check_count_distinct_slice(sql, data_slice)
        else:
            violation = None
        if violation is not None:
            violations.append(violation)
    return violations, candidate_results


def _require_spec(data_slice: CounterexampleSlice) -> TestSpec:
    if data_slice.test_spec is None:
        raise ValueError(f"Slice {data_slice.name} is missing a test spec")
    return data_slice.test_spec


def _oracle_sql(spec: TestSpec, aggregation: str | None) -> str:
    threshold = spec.threshold or 2
    predicates = []
    if spec.oracle_predicate is not None:
        predicates.append(_predicate_sql(spec.oracle_predicate))
    predicates.extend(_predicate_sql(condition) for condition in spec.activation_conditions)
    where_sql = f"WHERE {' AND '.join(predicates)}" if predicates else ""
    count_expr = aggregation or _predicate_aggregation(spec)
    from_sql = _from_sql(spec)
    if spec.grouping_key is None:
        return f"""
SELECT {count_expr} AS num_students
{from_sql}
{where_sql}
"""
    grouping = spec.grouping_key
    return f"""
SELECT {grouping["alias"]}.{grouping["column"]}, {count_expr} AS num_students
{from_sql}
{where_sql}
GROUP BY {grouping["alias"]}.{grouping["column"]}
HAVING {count_expr} >= {threshold}
"""


def _predicate_oracle_sql(sql: str, spec: TestSpec) -> str:
    candidate = spec.candidate_predicate or {}
    oracle = spec.oracle_predicate or {}
    tree = sqlglot.parse_one(sql, read="sqlite")
    for predicate in tree.find_all(_predicate_expression(candidate.get("operator"))):
        if _replace_matching_predicate(predicate, candidate, oracle):
            return tree.sql(dialect="sqlite")
    if _has_oracle_predicate(tree, oracle, candidate.get("operator")):
        return tree.sql(dialect="sqlite")
    raise ValueError("Oracle predicate target not found")


def _predicate_expression(operator: str | None):
    if operator == "LIKE":
        return exp.Like
    return exp.EQ


def _replace_matching_predicate(
    predicate: exp.Expression,
    candidate: dict[str, Any],
    oracle: dict[str, Any],
) -> bool:
    left = predicate.left if hasattr(predicate, "left") else predicate.args.get("this")
    right = predicate.right if hasattr(predicate, "right") else predicate.args.get("expression")
    if _matches_candidate_side(left, right, candidate):
        predicate.set("this", exp.column(oracle.get("column"), table=oracle.get("alias")))
        predicate.set("expression", _literal(oracle.get("value")))
        return True
    if _matches_candidate_side(right, left, candidate):
        predicate.set("expression", exp.column(oracle.get("column"), table=oracle.get("alias")))
        predicate.set("this", _literal(oracle.get("value")))
        return True
    return False


def _has_oracle_predicate(
    tree: exp.Expression,
    oracle: dict[str, Any],
    operator: str | None,
) -> bool:
    for predicate in tree.find_all(_predicate_expression(operator)):
        left = predicate.left if hasattr(predicate, "left") else predicate.args.get("this")
        right = predicate.right if hasattr(predicate, "right") else predicate.args.get("expression")
        if _matches_candidate_side(left, right, oracle) or _matches_candidate_side(right, left, oracle):
            return True
    return False


def _matches_candidate_side(
    column_expr: exp.Expression | None,
    value_expr: exp.Expression | None,
    candidate: dict[str, Any],
) -> bool:
    if not isinstance(column_expr, exp.Column):
        return False
    if column_expr.name != candidate.get("column"):
        return False
    if candidate.get("alias") and column_expr.table and column_expr.table != candidate.get("alias"):
        return False
    return _literal_matches(value_expr, candidate.get("value"))


def _literal_matches(expression: exp.Expression | None, value: Any) -> bool:
    if not isinstance(expression, exp.Literal):
        return False
    return _normalize_literal(expression.this) == _normalize_literal(value)


def _literal(value: Any) -> exp.Literal:
    text = str(value).strip("'\"")
    return exp.Literal.string(text)


def _normalize_literal(value: Any) -> str:
    return str(value).strip("'\"")


def _predicate_sql(predicate: dict[str, Any]) -> str:
    value = predicate["value"]
    if predicate["operator"] == "LIKE":
        return f"{predicate['alias']}.{predicate['column']} LIKE '{value}'"
    return f"{predicate['alias']}.{predicate['column']} {predicate['operator']} '{value}'"


def _same_rows(left: list[dict[str, Any]], right: list[dict[str, Any]]) -> bool:
    """Compare SQLite rows by ordered values, ignoring output alias names."""

    return [list(row.values()) for row in left] == [list(row.values()) for row in right]


def _predicate_aggregation(spec: TestSpec) -> str:
    target = spec.target_entity or {}
    if target.get("alias") and target.get("id_column"):
        return f"COUNT(DISTINCT {target['alias']}.{target['id_column']})"
    return "COUNT(*)"


def _from_sql(spec: TestSpec) -> str:
    tables = spec.query_tables
    if not tables:
        return """FROM students s
JOIN departments d ON s.dept_id = d.dept_id
JOIN enrollments e ON s.sid = e.sid
JOIN courses c ON e.cid = c.cid"""
    base = tables[0]
    lines = [f"FROM {base['table']} {base['alias']}"]
    for join in spec.joins:
        lines.append(f"JOIN {join['table']} {join['alias']} ON {join['on']}")
    return "\n".join(lines)
