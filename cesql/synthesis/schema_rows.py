"""Small deterministic row builders for schema-driven benchmark slices."""

from __future__ import annotations

from typing import Any


def primary_key(schema: dict[str, Any], table: str) -> str:
    keys = schema.get("tables", {}).get(table, {}).get("primary_key", [])
    return keys[0] if keys else "id"


def columns(schema: dict[str, Any], table: str) -> dict[str, str]:
    return schema.get("tables", {}).get(table, {}).get("columns", {})


def fk_between(schema: dict[str, Any], from_table: str, to_table: str) -> dict[str, str] | None:
    for fk in schema.get("foreign_keys", []):
        if fk["from_table"] == from_table and fk["to_table"] == to_table:
            return fk
    return None


def new_row(schema: dict[str, Any], table: str, seed: int, overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    """Create a valid row with deterministic defaults and overrides."""

    overrides = overrides or {}
    row: dict[str, Any] = {}
    pk = primary_key(schema, table)
    for column, column_type in columns(schema, table).items():
        if column in overrides:
            row[column] = overrides[column]
        elif column == pk:
            row[column] = seed
        elif column_type == "int":
            row[column] = seed
        else:
            row[column] = f"{table}_{column}_{seed}"
    return row


def condition_value(condition: dict[str, Any]) -> str:
    value = _normalize_literal(condition["value"])
    if condition.get("operator") == "LIKE":
        return value.replace("%", "") or "match"
    if condition.get("operator") == "BETWEEN":
        return value.split(" AND ", 1)[0]
    if condition.get("operator") in {"<", "<="}:
        return _numeric_offset(value, -1)
    if condition.get("operator") in {">", ">="}:
        return _numeric_offset(value, 1)
    if condition.get("operator") == "IS" and value.upper() == "NONE":
        return None
    wrapped = str(condition.get("wrapped_expression", ""))
    if "STRFTIME" in wrapped.upper() and len(value) == 4 and value.isdigit():
        return f"{value}-01-01"
    return value


def _normalize_literal(value: Any) -> str:
    text = str(value)
    previous = None
    while text != previous:
        previous = text
        text = text.strip().strip("'\"")
    return text


def _numeric_offset(value: str, offset: int) -> str | int | float:
    try:
        number = float(value)
    except ValueError:
        return value
    shifted = number + offset
    return int(shifted) if shifted.is_integer() else shifted
