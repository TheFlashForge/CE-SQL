"""SQLite value grounding helpers for oracle extraction."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

_VALUE_CACHE: dict[tuple[str, str, tuple[str, ...], int], set[tuple[str, str]]] = {}


def columns_containing_value(
    schema: dict[str, Any],
    value: Any,
    *,
    tables: list[str] | None = None,
    max_columns: int = 200,
) -> set[tuple[str, str]]:
    """Find schema columns whose original DB values contain a literal."""

    sqlite_path = (schema or {}).get("sqlite_path")
    if not sqlite_path or not Path(sqlite_path).exists():
        return set()
    normalized = _normalize_value(value)
    if not normalized:
        return set()
    table_names = tables or list((schema or {}).get("tables", {}))
    cache_key = (str(sqlite_path), normalized, tuple(sorted(table_names)), max_columns)
    if cache_key in _VALUE_CACHE:
        return set(_VALUE_CACHE[cache_key])
    matches: set[tuple[str, str]] = set()
    checked = 0
    try:
        with sqlite3.connect(sqlite_path) as conn:
            for table in table_names:
                for column in (schema or {}).get("tables", {}).get(table, {}).get("columns", {}):
                    checked += 1
                    if checked > max_columns:
                        _VALUE_CACHE[cache_key] = set(matches)
                        return matches
                    if _column_contains(conn, table, column, normalized):
                        matches.add((table, column))
    except sqlite3.Error:
        return matches
    _VALUE_CACHE[cache_key] = set(matches)
    return matches


def _column_contains(conn: sqlite3.Connection, table: str, column: str, value: str) -> bool:
    sql = (
        f"SELECT {_quote_identifier(column)} FROM {_quote_identifier(table)} "
        "WHERE "
        f"{_quote_identifier(column)} IS NOT NULL "
        "LIMIT 500"
    )
    try:
        for (cell,) in conn.execute(sql):
            normalized = _normalize_value(cell)
            if normalized in {value, f"'{value}'", f'"{value}"'}:
                return True
        return False
    except sqlite3.Error:
        return False


def _quote_identifier(identifier: str) -> str:
    return f'"{identifier.replace(chr(34), chr(34) + chr(34))}"'


def _normalize_value(value: Any) -> str:
    return str(value or "").strip().strip("'\"").lower()
