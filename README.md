# CE-SQL Demo

**CE-SQL** (Counter-Example Guided SQL Repair) — Paper Submission Demo

This repository contains a self-contained, runnable demonstration of the CE-SQL pipeline.
It repairs incorrect SQL queries by extracting **partial semantic oracles** from natural language questions,
compiling them into **counterexample test specifications**, synthesizing **deterministic test slices**,
and performing **AST-local repairs** when violations are detected.

## Pipeline Overview

```
Question + Candidate SQL + Schema
    │
    ▼
① Oracle Extraction          (rule-based / provided)
    │
    ▼
② SQL Component Extraction   (sqlglot AST traversal)
    │
    ▼
③ Oracle→SQL Scope Adaptation (alias resolution)
    │
    ▼
④ Suspicious Unit Detection  (oracle vs. component comparison)
    │
    ▼
⑤ Test Specification Compilation
    │
    ▼
⑥ Counterexample Slice Synthesis (in-memory SQLite)
    │
    ▼
⑦ Verification               (run SQL on slices)
    │
    ▼
⑧ Diagnosis                  (violation → RepairAction)
    │
    ▼
⑨ Repair                     (AST-local patching via sqlglot)
    │
    ▼
⑩ Re-verification
```

## Running Example

**Question:** "For each department, how many students majoring in CS have taken a database course?"

**Buggy Candidate SQL:**
```sql
SELECT d.dept_name, COUNT(*) AS num_students
FROM students s
JOIN departments d ON s.dept_id = d.dept_id
JOIN enrollments e ON s.sid = e.sid
JOIN courses c ON e.cid = c.cid
WHERE d.dept_name = 'CS'           -- ← wrong column (should be s.major)
  AND c.title LIKE '%Database%'
GROUP BY d.dept_name
HAVING COUNT(*) >= 2;              -- ← COUNT(*) overcounts via join
```

**Repaired SQL:**
```sql
SELECT d.dept_name, COUNT(DISTINCT s.sid) AS num_students
FROM students s
JOIN departments d ON s.dept_id = d.dept_id
JOIN enrollments e ON s.sid = e.sid
JOIN courses c ON e.cid = c.cid
WHERE s.major = 'CS'               -- ✓ corrected to students.major
  AND c.title LIKE '%Database%'
GROUP BY d.dept_name
HAVING COUNT(DISTINCT s.sid) >= 2; -- ✓ COUNT(DISTINCT) avoids overcounting
```

Two bugs are detected and repaired:
1. **Predicate grounding mismatch**: `d.dept_name = 'CS'` → `s.major = 'CS'`
2. **Duplicate counting**: `COUNT(*)` → `COUNT(DISTINCT s.sid)`

## Quick Start

```bash
# Install
pip install sqlglot pytest

# Run the demo
python scripts/run_running_example.py

# Run tests
pytest -v
```

## Project Structure

```
cesql_demo/
├── cesql/
│   ├── core/
│   │   ├── types.py          # Core data structures (oracles, slices, violations, ...)
│   │   └── pipeline.py       # End-to-end pipeline orchestration
│   ├── oracle/
│   │   ├── rule_extractor.py # Rule-based oracle extraction from NL questions
│   │   ├── oracle_adapter.py # Oracle-to-SQL alias adaptation
│   │   ├── schema_grounding.py   # Schema text normalization
│   │   ├── value_grounding.py    # Value matching in SQLite databases
│   │   └── candidate_column_ranker.py  # Column candidate ranking
│   ├── sql/
│   │   ├── components.py     # SQL component extraction (sqlglot AST)
│   │   ├── parser.py         # SQL validation
│   │   ├── patcher.py        # AST-local SQL patching
│   │   └── execution.py      # SQLite in-memory execution for slices
│   ├── suspicious/
│   │   └── detector.py       # Detect oracle↔SQL mismatches
│   ├── compiler/
│   │   └── test_spec.py      # Compile suspicious units → test specs
│   ├── synthesis/
│   │   ├── synthesizer.py    # Dispatch to type-specific synthesizers
│   │   ├── predicate_contrast.py  # Predicate contrast counterexample generation
│   │   ├── count_distinct.py     # Count-distinct counterexample generation
│   │   └── schema_rows.py        # Schema-aware row generation
│   ├── testing/
│   │   ├── verifier.py       # Verification wrapper
│   │   └── local_checkers.py # Semantic checkers for each slice type
│   ├── diagnosis/
│   │   └── diagnoser.py      # Map violations → repair actions
│   └── repair/
│       └── repair_engine.py  # Apply repair actions via AST patching
├── examples/
│   └── running_example/      # Canonical demo question + buggy SQL
├── scripts/
│   └── run_running_example.py
├── tests/
│   └── test_running_example.py  # 9 end-to-end assertions
└── pyproject.toml
```

## Dependencies

- **sqlglot** (≥25.0): SQL parsing and AST manipulation
- **pytest** (≥8.0, optional): Running the test suite

No LLM calls, no external API keys, no dataset downloads required.

## Design Principles

1. **Oracles as hypotheses, not instructions**: Every oracle is verified through counterexample testing before triggering a repair.
2. **Safety-first**: Never over-repair. If counterexample testing cannot confirm a bug, the system leaves the SQL unchanged.
3. **AST-local repairs only**: Deterministic, targeted patches — no free-form LLM rewriting.

## License

For academic review only.
