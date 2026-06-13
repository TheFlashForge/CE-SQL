"""End-to-end CE-SQL oracle-testspec-synthesis pipeline (Demo).

This is a simplified version for paper submission demonstration.
LLM oracle extraction and hybrid strategies are excluded.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from cesql.compiler.test_spec import compile_test_specs
from cesql.core.types import (
    OracleExtractionResult,
    PartialSemanticOracle,
    partial_semantic_oracle_from_record,
    to_jsonable,
)
from cesql.diagnosis.diagnoser import diagnose
from cesql.oracle.oracle_adapter import adapt_oracles_to_sql_scope
from cesql.oracle.rule_extractor import extract_oracles
from cesql.repair.repair_engine import repair_sql
from cesql.sql.components import extract_sql_components
from cesql.sql.parser import validate_sql
from cesql.suspicious.detector import detect_suspicious_units
from cesql.synthesis.synthesizer import synthesize_slices
from cesql.testing.verifier import verify


def run_pipeline(
    question: str,
    candidate_sql: str,
    schema: dict[str, Any] | None = None,
    provided_oracles: list[PartialSemanticOracle | dict[str, Any]] | None = None,
    oracle_mode: str = "provided",
    evidence: str | None = None,
) -> dict[str, Any]:
    """Run oracle extraction, checking, diagnosis, repair, and re-verification.

    Supported oracle_mode values:
        - "provided": use caller-supplied oracles, fall back to rule extraction
        - "rule":     use rule-based extraction only
    """

    validate_sql(candidate_sql)
    extraction = _extract_oracles(
        question=question,
        candidate_sql=candidate_sql,
        schema=schema,
        provided_oracles=provided_oracles,
        oracle_mode=oracle_mode,
        evidence=evidence,
    )
    sql_components = extract_sql_components(candidate_sql, schema=schema)
    oracles, adapter_logs = adapt_oracles_to_sql_scope(
        extraction.oracles, candidate_sql, schema=schema
    )
    suspicious_units = detect_suspicious_units(oracles, sql_components)
    test_specs = compile_test_specs(suspicious_units, sql_components, schema=schema)
    slices = synthesize_slices(test_specs)
    initial_verification = verify(candidate_sql, slices)
    violations = initial_verification.violations
    repair_actions = diagnose(violations, suspicious_units)
    if repair_actions:
        repaired_sql = repair_sql(candidate_sql, repair_actions, schema=schema)
        validate_sql(repaired_sql)
        repaired_verification = verify(repaired_sql, slices)
    else:
        repaired_sql = candidate_sql
        repaired_verification = initial_verification

    status = "repaired" if repaired_verification.passed and repair_actions else "no_repair"
    if repair_actions and not repaired_verification.passed:
        status = "repair_failed"

    return to_jsonable(
        {
            "status": status,
            "original_sql": candidate_sql,
            "repaired_sql": repaired_sql,
            "schema": schema or {},
            "oracles": oracles,
            "extracted_oracles": extraction.oracles,
            "adapter_logs": adapter_logs,
            "oracle_mode": oracle_mode,
            "rejected_oracles": extraction.rejected_oracles,
            "low_confidence_oracles": extraction.low_confidence_oracles,
            "sql_components": sql_components,
            "suspicious_units": suspicious_units,
            "test_specs": test_specs,
            "generated_slices": slices,
            "violations": violations,
            "repair_actions": repair_actions,
            "verification": {
                "initial": initial_verification,
                "repaired": repaired_verification,
            },
        }
    )


def _extract_oracles(
    question: str,
    candidate_sql: str,
    schema: dict[str, Any] | None,
    provided_oracles: list[PartialSemanticOracle | dict[str, Any]] | None,
    oracle_mode: str,
    evidence: str | None,
) -> OracleExtractionResult:
    if oracle_mode not in {"provided", "rule"}:
        raise ValueError(f"Unsupported oracle_mode: {oracle_mode}")
    if oracle_mode == "provided" and provided_oracles is not None:
        return OracleExtractionResult(oracles=_provided_oracles(provided_oracles))
    # Fall back to rule extraction for both "provided" (no oracles given) and "rule"
    return OracleExtractionResult(
        oracles=extract_oracles(question, schema=schema, candidate_sql=candidate_sql, evidence=evidence)
    )


def _provided_oracles(
    provided_oracles: list[PartialSemanticOracle | dict[str, Any]]
) -> list[PartialSemanticOracle]:
    return [partial_semantic_oracle_from_record(oracle) for oracle in provided_oracles]


def run_running_example(repo_root: Path | None = None) -> dict[str, Any]:
    """Load and run the repository's deterministic running example."""

    root = repo_root or Path(__file__).resolve().parents[2]
    question = (root / "examples" / "running_example" / "question.txt").read_text(encoding="utf-8")
    candidate_sql = (root / "examples" / "running_example" / "candidate.sql").read_text(encoding="utf-8")
    return run_pipeline(question=question, candidate_sql=candidate_sql)
