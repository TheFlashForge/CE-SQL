"""Verification helpers for original and repaired SQL."""

from __future__ import annotations

from cesql.core.types import CounterexampleSlice, VerificationResult
from cesql.sql.parser import validate_sql
from cesql.testing.local_checkers import run_local_checkers


def verify(sql: str, slices: list[CounterexampleSlice]) -> VerificationResult:
    """Return semantic verification status over all generated slices."""

    parses = validate_sql(sql)
    violations, candidate_results = run_local_checkers(sql, slices)
    return VerificationResult(
        passed=not violations and parses,
        candidate_results=candidate_results,
        violations=violations,
        parses=parses,
    )
