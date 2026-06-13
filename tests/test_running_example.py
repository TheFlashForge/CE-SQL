"""End-to-end test for the CE-SQL demo running example."""

from pathlib import Path

from cesql.compiler.test_spec import compile_test_specs
from cesql.core.pipeline import run_running_example
from cesql.diagnosis.diagnoser import diagnose
from cesql.oracle.rule_extractor import extract_oracles
from cesql.repair.repair_engine import repair_sql
from cesql.sql.components import extract_sql_components
from cesql.suspicious.detector import detect_suspicious_units
from cesql.synthesis.synthesizer import synthesize_slices
from cesql.testing.local_checkers import run_local_checkers


EXPECTED_REPAIRED_SQL = """SELECT d.dept_name, COUNT(DISTINCT s.sid) AS num_students
FROM students s
JOIN departments d ON s.dept_id = d.dept_id
JOIN enrollments e ON s.sid = e.sid
JOIN courses c ON e.cid = c.cid
WHERE s.major = 'CS'
  AND c.title LIKE '%Database%'
GROUP BY d.dept_name
HAVING COUNT(DISTINCT s.sid) >= 2;
"""
ROOT = Path(__file__).resolve().parents[1]
CANDIDATE_SQL = (ROOT / "examples" / "running_example" / "candidate.sql").read_text()
QUESTION = (ROOT / "examples" / "running_example" / "question.txt").read_text()


def test_running_example_is_repaired():
    result = run_running_example()

    assert result["status"] == "repaired"
    assert result["repaired_sql"] == EXPECTED_REPAIRED_SQL
    assert result["verification"]["repaired"]["passed"] is True
    assert result["verification"]["initial"]["passed"] is False


def test_running_example_reports_required_artifacts():
    result = run_running_example()

    assert {oracle["oracle_type"] for oracle in result["oracles"]} == {
        "predicate_grounding",
        "count_distinct",
    }
    assert {unit["kind"] for unit in result["suspicious_units"]} == {
        "predicate_grounding_mismatch",
        "possible_duplicate_counting",
    }
    assert {s["name"] for s in result["generated_slices"]} == {
        "predicate_contrast",
        "count_distinct",
    }
    assert {v["kind"] for v in result["violations"]} == {
        "predicate_grounding_mismatch",
        "duplicate_counting",
    }
    assert {"sql_components", "test_specs", "verification"}.issubset(result)


def test_sql_component_extraction_finds_running_example_units():
    components = extract_sql_components(CANDIDATE_SQL)

    assert any(
        c.component_type == "where_predicate" and c.expression == "d.dept_name = 'CS'"
        for c in components
    )
    assert any(
        c.component_type == "where_predicate" and c.expression == "c.title LIKE '%Database%'"
        for c in components
    )
    assert any(
        c.component_type == "aggregation" and c.expression == "COUNT(*)"
        for c in components
    )
    assert any(
        c.component_type == "group_by" and c.expression == "d.dept_name"
        for c in components
    )
    assert any(
        c.component_type == "having_predicate" and c.expression == "COUNT(*) >= 2"
        for c in components
    )


def test_oracle_extraction_returns_structured_oracles():
    oracles = extract_oracles(QUESTION)

    predicate = next(o for o in oracles if o.oracle_type == "predicate_grounding")
    count = next(o for o in oracles if o.oracle_type == "count_distinct")

    assert predicate.target_table == "students"
    assert predicate.target_alias == "s"
    assert predicate.target_column == "major"
    assert predicate.value == "CS"
    assert count.expected_aggregation == "COUNT(DISTINCT s.sid)"


def test_suspicious_unit_detection_compares_oracles_and_components():
    oracles = extract_oracles(QUESTION)
    components = extract_sql_components(CANDIDATE_SQL)
    units = detect_suspicious_units(oracles, components)

    assert {u.kind for u in units} == {
        "predicate_grounding_mismatch",
        "possible_duplicate_counting",
    }
    predicate_unit = next(u for u in units if u.kind == "predicate_grounding_mismatch")
    assert predicate_unit.component.column == "dept_name"
    assert predicate_unit.oracle.target_column == "major"


def test_compiler_emits_test_specs():
    oracles = extract_oracles(QUESTION)
    components = extract_sql_components(CANDIDATE_SQL)
    units = detect_suspicious_units(oracles, components)
    specs = compile_test_specs(units, components)

    assert {s.test_type for s in specs} == {"predicate_contrast", "count_distinct_contrast"}
    predicate_spec = next(s for s in specs if s.test_type == "predicate_contrast")
    assert predicate_spec.oracle_predicate["column"] == "major"
    assert predicate_spec.candidate_predicate["column"] == "dept_name"
    assert predicate_spec.grouping_key["column"] == "dept_name"
    assert predicate_spec.threshold == 2


def test_synthesizers_generate_deterministic_tables():
    specs = _test_specs()
    slices = synthesize_slices(specs)

    predicate_slice = next(s for s in slices if s.name == "predicate_contrast")
    count_slice = next(s for s in slices if s.name == "count_distinct")

    assert len(predicate_slice.tables["students"]) == 4
    assert predicate_slice.tables["students"][0]["major"] == "CS"
    assert len(count_slice.tables["students"]) == 2
    assert count_slice.tables["enrollments"].count({"sid": 1, "cid": 10}) == 1
    assert sum(row["sid"] == 1 for row in count_slice.tables["enrollments"]) == 2


def test_local_checkers_detect_both_violations():
    slices = synthesize_slices(_test_specs())
    violations, candidate_results = run_local_checkers(CANDIDATE_SQL, slices)

    assert candidate_results["predicate_contrast"] == [{"dept_name": "CS", "num_students": 2}]
    assert {v.kind for v in violations} == {"predicate_grounding_mismatch", "duplicate_counting"}


def test_repair_actions_patch_sql_with_ast():
    slices = synthesize_slices(_test_specs())
    violations, _ = run_local_checkers(CANDIDATE_SQL, slices)
    units = detect_suspicious_units(extract_oracles(QUESTION), extract_sql_components(CANDIDATE_SQL))
    actions = diagnose(violations, units)
    repaired = repair_sql(CANDIDATE_SQL, actions)

    assert {a.kind for a in actions} == {
        "ReplacePredicateColumn",
        "AddDistinctToCount",
        "ReplaceHavingCountWithDistinctCount",
    }
    assert repaired == EXPECTED_REPAIRED_SQL


def _test_specs():
    oracles = extract_oracles(QUESTION)
    components = extract_sql_components(CANDIDATE_SQL)
    units = detect_suspicious_units(oracles, components)
    return compile_test_specs(units, components)
