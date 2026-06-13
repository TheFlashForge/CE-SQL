"""Dispatch test specifications to deterministic slice synthesizers."""

from __future__ import annotations

from cesql.core.types import CounterexampleSlice, TestSpec
from cesql.synthesis.count_distinct import CountDistinctSynthesizer
from cesql.synthesis.predicate_contrast import PredicateContrastSynthesizer


def synthesize_slices(test_specs: list[TestSpec]) -> list[CounterexampleSlice]:
    """Synthesize all counterexample slices requested by test specs."""

    slices: list[CounterexampleSlice] = []
    for spec in test_specs:
        if spec.test_type == "predicate_contrast":
            slices.append(PredicateContrastSynthesizer().synthesize(spec))
        elif spec.test_type == "count_distinct_contrast":
            slices.append(CountDistinctSynthesizer().synthesize(spec))
    return slices
