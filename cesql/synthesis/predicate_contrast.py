"""Predicate-grounding counterexample generation."""

from __future__ import annotations

from typing import Any

import sqlglot
from sqlglot import exp

from cesql.core.types import CounterexampleSlice, TestSpec
from cesql.synthesis.schema_rows import condition_value, fk_between, new_row, primary_key


class PredicateContrastSynthesizer:
    """Build slices that separate oracle and candidate predicate grounding."""

    def synthesize(self, spec: TestSpec) -> CounterexampleSlice:
        if not spec.schema:
            return _running_example_slice(spec)
        oracle = spec.oracle_predicate or {}
        candidate = spec.candidate_predicate or {}
        grouping = spec.grouping_key or candidate
        oracle_table = oracle["table"]
        candidate_table = candidate["table"]
        oracle_pk = primary_key(spec.schema, oracle_table)
        candidate_pk = primary_key(spec.schema, candidate_table)
        candidate_value = _matching_value(candidate.get("value", "CandidateValue"))
        oracle_value = _matching_value(oracle.get("value", "OracleValue"))
        group_a_value = "Math" if candidate_value == "CS" else "GroupA"
        tables: dict[str, list[dict[str, Any]]] = {
            table["table"]: [] for table in spec.query_tables if table.get("table")
        }

        if oracle_table == candidate_table:
            tables[oracle_table] = _same_table_contrast_rows(
                spec,
                oracle_table,
                oracle_pk,
                oracle,
                candidate,
                oracle_value,
                candidate_value,
            )
            _add_activation_rows(spec, tables, [1, 2, 3, 4])
            _add_join_support_rows(spec, tables)
            return CounterexampleSlice(
                name="predicate_contrast",
                test_type=spec.test_type,
                purpose="Expose oracle predicate grounding versus candidate grounding",
                test_spec=spec,
                tables=tables,
                schema=spec.schema,
            )

        tables[candidate_table] = [
            new_row(
                spec.schema,
                candidate_table,
                1,
                {candidate_pk: 1, grouping["column"]: group_a_value},
            ),
            new_row(
                spec.schema,
                candidate_table,
                2,
                {candidate_pk: 2, grouping["column"]: candidate_value, candidate["column"]: candidate_value},
            ),
        ]

        target_rows = []
        for sid, value, group_id in (
            (1, oracle_value, 1),
            (2, oracle_value, 1),
            (3, f"not_{oracle_value}", 2),
            (4, f"other_{oracle_value}", 2),
        ):
            overrides = {oracle_pk: sid, oracle["column"]: value}
            target_rows.append(new_row(spec.schema, oracle_table, sid, overrides))
        tables[oracle_table] = target_rows
        if not _connect_oracle_candidate_join(spec, tables, oracle, candidate):
            oracle_to_candidate = fk_between(spec.schema, oracle_table, candidate_table)
            if oracle_to_candidate is not None:
                for index, group_id in enumerate((1, 1, 2, 2)):
                    tables[oracle_table][index][oracle_to_candidate["from_column"]] = group_id

        _add_activation_rows(spec, tables, [1, 2, 3, 4])
        _add_join_support_rows(spec, tables)
        return CounterexampleSlice(
            name="predicate_contrast",
            test_type=spec.test_type,
            purpose="Expose oracle predicate grounding versus candidate grounding",
            test_spec=spec,
            tables=tables,
            schema=spec.schema,
        )


def _same_table_contrast_rows(
    spec: TestSpec,
    table: str,
    primary_key_column: str,
    oracle: dict[str, Any],
    candidate: dict[str, Any],
    oracle_value: Any,
    candidate_value: Any,
) -> list[dict[str, Any]]:
    rows = []
    for seed, oracle_cell, candidate_cell in (
        (10, oracle_value, _non_matching_value(candidate_value)),
        (20, oracle_value, _non_matching_value(candidate_value)),
        (1, _non_matching_value(oracle_value), candidate_value),
        (40, _non_matching_value(oracle_value), _non_matching_value(candidate_value)),
    ):
        rows.append(
            new_row(
                spec.schema,
                table,
                seed,
                {
                    primary_key_column: seed,
                    oracle["column"]: oracle_cell,
                    candidate["column"]: candidate_cell,
                },
            )
        )
    return rows


def _non_matching_value(value: Any) -> str:
    normalized = _normalize_cell_value(value)
    return f"not_{normalized}" if normalized else "not_match"


def _matching_value(value: Any) -> str:
    normalized = _normalize_cell_value(value)
    return normalized.replace("%", "match") if "%" in normalized else normalized


def _normalize_cell_value(value: Any) -> str:
    text = str(value)
    previous = None
    while text != previous:
        previous = text
        text = text.strip().strip("'\"")
    return text


def build_predicate_contrast_slice(spec: TestSpec) -> CounterexampleSlice:
    """Compatibility wrapper for predicate contrast synthesis."""

    return PredicateContrastSynthesizer().synthesize(spec)


def _add_activation_rows(
    spec: TestSpec, tables: dict[str, list[dict[str, Any]]], target_ids: list[int]
) -> None:
    if not spec.activation_conditions or not spec.oracle_predicate:
        return
    target_table = spec.oracle_predicate["table"]
    target_pk = primary_key(spec.schema, target_table)
    for condition in spec.activation_conditions:
        activation_table = condition["table"]
        if activation_table == target_table:
            for row in tables.get(target_table, []):
                row[condition["column"]] = condition_value(condition)
            continue
        activation_pk = primary_key(spec.schema, activation_table)
        tables[activation_table] = [
            new_row(
                spec.schema,
                activation_table,
                10,
                {activation_pk: 10, condition["column"]: condition_value(condition)},
            )
        ]
        direct = fk_between(spec.schema, target_table, activation_table)
        if direct is not None:
            for row in tables[target_table]:
                row[direct["from_column"]] = 10
            continue
        reverse = fk_between(spec.schema, activation_table, target_table)
        if reverse is not None:
            target_rows = tables.get(target_table, [])
            target_key = reverse["to_column"]
            tables[activation_table] = [
                new_row(
                    spec.schema,
                    activation_table,
                    index + 10,
                    {
                        activation_pk: index + 10,
                        reverse["from_column"]: row[target_key],
                        condition["column"]: condition_value(condition),
                    },
                )
                for index, row in enumerate(target_rows)
            ]
            continue
        bridge = _bridge_table(spec.schema, target_table, activation_table)
        if bridge is None:
            continue
        bridge_table, target_fk, activation_fk = bridge
        tables[bridge_table] = [
            new_row(
                spec.schema,
                bridge_table,
                index + 1,
                {
                    target_fk["from_column"]: target_id,
                    activation_fk["from_column"]: 10,
                },
            )
            for index, target_id in enumerate(target_ids)
        ]


def _connect_oracle_candidate_join(
    spec: TestSpec,
    tables: dict[str, list[dict[str, Any]]],
    oracle: dict[str, Any],
    candidate: dict[str, Any],
) -> bool:
    oracle_alias = oracle.get("alias")
    candidate_alias = candidate.get("alias")
    oracle_table = oracle.get("table")
    candidate_table = candidate.get("table")
    if not oracle_alias or not candidate_alias or not oracle_table or not candidate_table:
        return False
    join_columns = _join_columns_between(spec, oracle_alias, candidate_alias)
    if join_columns is None:
        return False
    oracle_column, candidate_column = join_columns
    candidate_rows = tables.get(candidate_table, [])
    oracle_rows = tables.get(oracle_table, [])
    if len(candidate_rows) < 2 or len(oracle_rows) < 4:
        return False
    for index, group_index in enumerate((0, 0, 1, 1)):
        oracle_rows[index][oracle_column] = candidate_rows[group_index][candidate_column]
    return True


def _join_columns_between(
    spec: TestSpec, left_alias: str, right_alias: str
) -> tuple[str, str] | None:
    for join in spec.joins:
        on = join.get("on")
        if not on:
            continue
        try:
            predicate = sqlglot.parse_one(on, read="sqlite")
        except Exception:
            continue
        if not isinstance(predicate, exp.EQ):
            continue
        left = predicate.left
        right = predicate.right
        if not isinstance(left, exp.Column) or not isinstance(right, exp.Column):
            continue
        if left.table == left_alias and right.table == right_alias:
            return left.name, right.name
        if left.table == right_alias and right.table == left_alias:
            return right.name, left.name
    return None


def _add_join_support_rows(spec: TestSpec, tables: dict[str, list[dict[str, Any]]]) -> None:
    alias_to_table = {
        table["alias"]: table["table"]
        for table in spec.query_tables
        if table.get("alias") and table.get("table")
    }
    for _ in range(max(1, len(spec.joins) * 2)):
        changed = False
        for join in spec.joins:
            columns = _join_columns(join.get("on"))
            if columns is None:
                continue
            left, right = columns
            left_table = alias_to_table.get(left.table)
            right_table = alias_to_table.get(right.table)
            changed = (
                _connect_join_table(spec, tables, left_table, left.name, right_table, right.name)
                or _connect_join_table(spec, tables, right_table, right.name, left_table, left.name)
                or changed
            )
        if not changed:
            break


def _join_columns(on_sql: str | None) -> tuple[exp.Column, exp.Column] | None:
    if not on_sql:
        return None
    try:
        predicate = sqlglot.parse_one(on_sql, read="sqlite")
    except Exception:
        return None
    if not isinstance(predicate, exp.EQ):
        return None
    left = predicate.left
    right = predicate.right
    if isinstance(left, exp.Column) and isinstance(right, exp.Column):
        return left, right
    return None


def _connect_join_table(
    spec: TestSpec,
    tables: dict[str, list[dict[str, Any]]],
    source_table: str | None,
    source_column: str,
    target_table: str | None,
    target_column: str,
) -> bool:
    if not source_table or not target_table:
        return False
    source_rows = tables.get(source_table, [])
    if not source_rows or target_table not in tables:
        return False
    target_rows = tables.get(target_table, [])
    if target_rows:
        changed = False
        for index, row in enumerate(target_rows):
            value = source_rows[index % len(source_rows)].get(source_column)
            if row.get(target_column) != value:
                row[target_column] = value
                changed = True
        return changed
    target_pk = primary_key(spec.schema, target_table)
    tables[target_table] = [
        new_row(
            spec.schema,
            target_table,
            index + 100,
            {
                target_pk: index + 100,
                target_column: row[source_column],
            },
        )
        for index, row in enumerate(source_rows)
    ]
    return True


def _bridge_table(schema: dict[str, Any], left_table: str, right_table: str):
    for table in schema.get("tables", {}):
        left_fk = fk_between(schema, table, left_table)
        right_fk = fk_between(schema, table, right_table)
        if left_fk and right_fk:
            return table, left_fk, right_fk
    return None


def _running_example_slice(spec: TestSpec) -> CounterexampleSlice:
    return CounterexampleSlice(
        name="predicate_contrast",
        test_type=spec.test_type,
        purpose="Expose oracle predicate grounding versus candidate grounding",
        test_spec=spec,
        tables={
            "departments": [
                {"dept_id": 1, "dept_name": "Math"},
                {"dept_id": 2, "dept_name": "CS"},
            ],
            "students": [
                {"sid": 1, "name": "Alice", "major": "CS", "dept_id": 1},
                {"sid": 2, "name": "Bob", "major": "CS", "dept_id": 1},
                {"sid": 3, "name": "Carol", "major": "Math", "dept_id": 2},
                {"sid": 4, "name": "Dave", "major": "Physics", "dept_id": 2},
            ],
            "courses": [{"cid": 10, "title": "Database Systems"}],
            "enrollments": [
                {"sid": 1, "cid": 10},
                {"sid": 2, "cid": 10},
                {"sid": 3, "cid": 10},
                {"sid": 4, "cid": 10},
            ],
        },
    )
