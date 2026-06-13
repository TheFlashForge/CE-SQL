"""SQLite execution utilities for deterministic counterexample slices."""

from __future__ import annotations

import sqlite3
from typing import Any

from cesql.core.types import CounterexampleSlice


DEFAULT_SCHEMA = {
    "departments": (
        "CREATE TABLE departments ("
        "dept_id INTEGER PRIMARY KEY, "
        "dept_name TEXT NOT NULL)"
    ),
    "students": (
        "CREATE TABLE students ("
        "sid INTEGER PRIMARY KEY, "
        "name TEXT NOT NULL, "
        "major TEXT NOT NULL, "
        "dept_id INTEGER NOT NULL)"
    ),
    "courses": (
        "CREATE TABLE courses ("
        "cid INTEGER PRIMARY KEY, "
        "title TEXT NOT NULL)"
    ),
    "enrollments": (
        "CREATE TABLE enrollments ("
        "sid INTEGER NOT NULL, "
        "cid INTEGER NOT NULL)"
    ),
}


def load_slice(data_slice: CounterexampleSlice) -> sqlite3.Connection:
    """Load a deterministic slice into an in-memory SQLite database."""

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    for create_statement in _create_statements(data_slice):
        conn.execute(create_statement)

    for table_name, rows in data_slice.tables.items():
        if _is_sqlite_internal_table(table_name):
            continue
        for row in rows:
            columns = list(row)
            placeholders = ", ".join(["?"] * len(columns))
            column_sql = ", ".join(_quote_identifier(column) for column in columns)
            conn.execute(
                f"INSERT INTO {_quote_identifier(table_name)} ({column_sql}) VALUES ({placeholders})",
                [row[column] for column in columns],
            )
    conn.commit()
    return conn


def execute_sql(sql: str, data_slice: CounterexampleSlice) -> list[dict[str, Any]]:
    """Execute SQL over one generated slice and return rows as dictionaries."""

    with load_slice(data_slice) as conn:
        cursor = conn.execute(sql)
        return [dict(row) for row in cursor.fetchall()]


def _create_statements(data_slice: CounterexampleSlice) -> list[str]:
    if not data_slice.schema:
        return list(DEFAULT_SCHEMA.values())

    statements: list[str] = []
    for table_name, table_spec in data_slice.schema.get("tables", {}).items():
        if _is_sqlite_internal_table(table_name):
            continue
        columns = []
        for column_name, column_type in table_spec.get("columns", {}).items():
            sql_type = "INTEGER" if column_type == "int" else "TEXT"
            columns.append(f"{_quote_identifier(column_name)} {sql_type}")
        statements.append(f"CREATE TABLE {_quote_identifier(table_name)} ({', '.join(columns)})")
    return statements


def _quote_identifier(identifier: str) -> str:
    return f'"{identifier.replace(chr(34), chr(34) + chr(34))}"'


def _is_sqlite_internal_table(table_name: str) -> bool:
    return table_name.lower().startswith("sqlite_")
