"""Step-aligned diff against a known-good run of the same task.

Trace-level probe: takes no step index. Returns the first divergent step, which is the
single strongest localization signal available, but is only weakly discriminative for
attribution -- it tells you *where* things went wrong, not *why*. That asymmetry is the
reason the project scores localization and attribution separately.

The reference trace is supplied by the environment through a lookup, never read out of
ground truth.
"""
from __future__ import annotations

from typing import Callable

from trace.models import Evidence, Trace
from .base import ProbeSpec, failed, register

SPEC = ProbeSpec(
    id="compare_known_good",
    description="Step-aligned diff against a known-good run of the same task.",
    target="trace", applies_to_kinds=(),
    reveals=("first_divergent_step", "aligned_diff"),
)


class StateCompareProbe:
    spec = SPEC

    def __init__(self, lookup: Callable[[str], Trace | None] | None = None):
        self._lookup = lookup

    def bind(self, lookup: Callable[[str], Trace | None]) -> None:
        """Called by the episode runner. Keeps ground truth out of the probe."""
        self._lookup = lookup

    def execute(self, trace: Trace, step_index: int | None) -> Evidence:
        if trace.reference_trace_id is None or self._lookup is None:
            return failed(SPEC, None, "no reference trace available for this task")
        reference = self._lookup(trace.reference_trace_id)
        if reference is None:
            return failed(SPEC, None, "reference trace id does not resolve")

        diff: list[dict] = []
        first_divergent: int | None = None
        for a, b in zip(trace.steps, reference.steps):
            same = a.kind == b.kind and a.summary == b.summary
            if not same:
                if first_divergent is None:
                    first_divergent = a.index
                diff.append({"index": a.index, "failed_run": a.summary,
                             "known_good": b.summary})
        if len(trace.steps) != len(reference.steps) and first_divergent is None:
            first_divergent = min(len(trace.steps), len(reference.steps))

        return Evidence(SPEC.id, None, True, {
            "first_divergent_step": first_divergent,
            "aligned_diff": diff,
            "length_delta": len(trace.steps) - len(reference.steps),
        })


register(StateCompareProbe())
