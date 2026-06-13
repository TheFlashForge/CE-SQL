"""Deterministic repair engine for CE-SQL MVP."""

from __future__ import annotations

from typing import Any

from cesql.core.types import RepairAction
from cesql.sql.patcher import apply_repairs


def repair_sql(
    sql: str, actions: list[RepairAction], schema: dict[str, Any] | None = None
) -> str:
    """Apply diagnosed repair actions to the candidate SQL."""

    return apply_repairs(sql, actions, schema=schema)
