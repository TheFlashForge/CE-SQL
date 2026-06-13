"""Distinct-count counterexample generation."""

from __future__ import annotations

from typing import Any

from cesql.core.types import CounterexampleSlice, TestSpec
from cesql.synthesis.schema_rows import condition_value, fk_between, new_row, primary_key


class CountDistinctSynthesizer:
    """Build slices where joined rows outnumber distinct target entities."""

    def synthesize(self, spec: TestSpec) -> CounterexampleSlice:
        if not spec.schema:
            return _running_example_slice(spec)
        target = spec.target_entity or {}
        grouping = spec.grouping_key or {}
        target_table = target["table"]
        target_pk = target["id_column"] or primary_key(spec.schema, target_table)
        tables: dict[str, list[dict[str, Any]]] = {
            table["table"]: [] for table in spec.query_tables if table.get("table")
        }

        target_rows = [
            new_row(spec.schema, target_table, 1, {target_pk: 1}),
            new_row(spec.schema, target_table, 2, {target_pk: 2}),
        ]
        if grouping.get("table") == target_table:
            for row in target_rows:
                row[grouping["column"]] = "GroupA"
        tables[target_table] = target_rows

        _add_count_join_rows(spec, tables, target_table, target_pk)
        return CounterexampleSlice(
            name="count_distinct",
            test_type=spec.test_type,
            purpose="Expose COUNT(*) over repeated student-course enrollments",
            test_spec=spec,
            tables=tables,
            schema=spec.schema,
        )


def build_count_distinct_slice(spec: TestSpec) -> CounterexampleSlice:
    """Compatibility wrapper for count-distinct synthesis."""

    return CountDistinctSynthesizer().synthesize(spec)


def _add_count_join_rows(
    spec: TestSpec,
    tables: dict[str, list[dict[str, Any]]],
    target_table: str,
    target_pk: str,
) -> None:
    activation = spec.activation_conditions[0] if spec.activation_conditions else None
    activation_table = activation["table"] if activation else None
    if activation:
        activation_pk = primary_key(spec.schema, activation_table)
        tables[activation_table] = [
            new_row(
                spec.schema,
                activation_table,
                10,
                {activation_pk: 10, activation["column"]: condition_value(activation)},
            ),
            new_row(
                spec.schema,
                activation_table,
                11,
                {activation_pk: 11, activation["column"]: condition_value(activation)},
            ),
        ]

    for table in list(tables):
        if table in {target_table, activation_table}:
            continue
        target_fk = fk_between(spec.schema, table, target_table)
        if target_fk is None:
            continue
        rows = []
        child_pk = primary_key(spec.schema, table)
        activation_fk = fk_between(spec.schema, table, activation_table) if activation_table else None
        for seed, target_id, activation_id in ((1, 1, 10), (2, 1, 11), (3, 2, 10)):
            overrides = {child_pk: seed, target_fk["from_column"]: target_id}
            if activation_fk is not None:
                overrides[activation_fk["from_column"]] = activation_id
            rows.append(new_row(spec.schema, table, seed, overrides))
        tables[table] = rows


def _running_example_slice(spec: TestSpec) -> CounterexampleSlice:
    return CounterexampleSlice(
        name="count_distinct",
        test_type=spec.test_type,
        purpose="Expose COUNT(*) over repeated student-course enrollments",
        test_spec=spec,
        tables={
            "departments": [{"dept_id": 1, "dept_name": "Math"}],
            "students": [
                {"sid": 1, "name": "Alice", "major": "CS", "dept_id": 1},
                {"sid": 2, "name": "Bob", "major": "CS", "dept_id": 1},
            ],
            "courses": [
                {"cid": 10, "title": "Database Systems"},
                {"cid": 11, "title": "Database Design"},
            ],
            "enrollments": [
                {"sid": 1, "cid": 10},
                {"sid": 1, "cid": 11},
                {"sid": 2, "cid": 10},
            ],
        },
    )
