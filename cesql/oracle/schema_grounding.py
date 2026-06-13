"""Schema text normalization helpers for oracle grounding."""

from __future__ import annotations

import re
from typing import Any


TOKEN_RE = re.compile(r"[A-Za-z0-9]+")


def normalize_text(value: Any) -> str:
    """Normalize schema, question, and literal text for fuzzy matching."""

    return " ".join(tokens(value))


def tokens(value: Any) -> list[str]:
    text = str(value or "").replace("_", " ")
    spaced = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", text)
    return [item.lower() for item in TOKEN_RE.findall(spaced)]


def token_overlap_score(text: str, table: str, column: str) -> float:
    """Return a small lexical score for table/column mentions in text."""

    text_tokens = set(tokens(text))
    if not text_tokens:
        return 0.0
    column_tokens = set(tokens(column))
    table_tokens = set(tokens(table))
    score = 0.0
    if column_tokens:
        score += len(text_tokens & column_tokens) / len(column_tokens)
    if table_tokens:
        score += 0.25 * len(text_tokens & table_tokens) / len(table_tokens)
    phrase = normalize_text(column)
    if phrase and phrase in normalize_text(text):
        score += 1.0
    return score


def table_names(schema: dict[str, Any], query_tables: set[str] | None = None) -> list[str]:
    tables = list((schema or {}).get("tables", {}))
    if query_tables:
        preferred = [table for table in tables if table in query_tables]
        return preferred + [table for table in tables if table not in query_tables]
    return tables


def column_names(schema: dict[str, Any], table: str) -> list[str]:
    return list((schema or {}).get("tables", {}).get(table, {}).get("columns", {}))


def primary_key(schema: dict[str, Any], table: str) -> str | None:
    keys = (schema or {}).get("tables", {}).get(table, {}).get("primary_key", [])
    return keys[0] if len(keys) == 1 else None


def likely_identifier(column: str | None) -> bool:
    if not column:
        return False
    lowered = column.lower()
    return lowered == "id" or lowered.endswith("_id") or lowered.endswith("id")
