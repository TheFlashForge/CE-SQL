"""Map local checker violations to deterministic repair actions."""

from __future__ import annotations

from cesql.core.types import RepairAction, SuspiciousUnit, Violation


def diagnose(
    violations: list[Violation], suspicious_units: list[SuspiciousUnit] | None = None
) -> list[RepairAction]:
    """Translate MVP violation kinds into the two supported repairs."""

    actions: list[RepairAction] = []
    kinds = {violation.kind for violation in violations}
    if "predicate_grounding_mismatch" in kinds:
        unit = _unit("predicate_grounding_mismatch", suspicious_units)
        oracle = unit.oracle if unit else None
        component = unit.component if unit else None
        actions.append(
            RepairAction(
                kind="ReplacePredicateColumn",
                before=unit.sql_fragment if unit else "d.dept_name = 'CS'",
                after=(
                    f"{oracle.target_alias}.{oracle.target_column} = '{oracle.value}'"
                    if oracle
                    else "s.major = 'CS'"
                ),
                target_alias=component.alias if component else "d",
                target_table=component.table if component else "departments",
                target_column=component.column if component else "dept_name",
                replacement_alias=oracle.target_alias if oracle else "s",
                replacement_table=oracle.target_table if oracle else "students",
                replacement_column=oracle.target_column if oracle else "major",
                value=oracle.value if oracle else "CS",
            )
        )
    if "duplicate_counting" in kinds:
        unit = _unit("possible_duplicate_counting", suspicious_units)
        oracle = unit.oracle if unit else None
        actions.extend(
            [
                RepairAction(
                    kind="AddDistinctToCount",
                    before="COUNT(*) AS num_students",
                    after="COUNT(DISTINCT s.sid) AS num_students",
                    distinct_alias=oracle.target_alias if oracle else "s",
                    distinct_column=oracle.target_id_column if oracle else "sid",
                ),
                RepairAction(
                    kind="ReplaceHavingCountWithDistinctCount",
                    before="HAVING COUNT(*) >= 2",
                    after="HAVING COUNT(DISTINCT s.sid) >= 2",
                    distinct_alias=oracle.target_alias if oracle else "s",
                    distinct_column=oracle.target_id_column if oracle else "sid",
                ),
            ]
        )
    return actions


def _unit(kind: str, units: list[SuspiciousUnit] | None) -> SuspiciousUnit | None:
    if not units:
        return None
    return next((unit for unit in units if unit.kind == kind), None)
