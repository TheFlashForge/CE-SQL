"""Small SQL validation wrapper around sqlglot."""

from __future__ import annotations

import sqlglot


def validate_sql(sql: str) -> bool:
    """Return True when SQL is parseable by sqlglot."""

    sqlglot.parse_one(sql, read="sqlite")
    return True
