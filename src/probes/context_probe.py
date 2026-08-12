"""Reveal the retrieval query, retrieved documents and scores.

Discriminative role: isolates `stale_document` (H3). This probe is the main reason step
targeting matters: the retrieval step that caused the failure typically sits several
steps before the crash, behind distractor steps.
"""
from __future__ import annotations

from trace.models import Evidence, Trace
from .base import ProbeSpec, failed, register

SPEC = ProbeSpec(
    id="inspect_context",
    description="Reveal retrieval query, retrieved documents and relevance scores.",
    target="step", applies_to_kinds=("retrieval",),
    reveals=("query", "documents", "scores"),
)


class ContextProbe:
    spec = SPEC

    def execute(self, trace: Trace, step_index: int | None) -> Evidence:
        s = trace.step(step_index)
        if s is None or s.retrieval is None:
            return failed(SPEC, step_index, "no retrieval at this step")
        r = s.retrieval
        return Evidence(SPEC.id, step_index, True, {
            "query": r.query, "documents": r.documents, "scores": r.scores,
        })


register(ContextProbe())
