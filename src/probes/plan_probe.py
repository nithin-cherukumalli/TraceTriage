"""Reveal the agent's plan / reasoning text.

Discriminative role: separates H1 (plan itself is wrong) from H2 `wrong_tool_selected`,
where the plan is correct and execution deviates from it.
"""
from __future__ import annotations

from trace.models import Evidence, Trace
from .base import ProbeSpec, failed, register

SPEC = ProbeSpec(
    id="inspect_plan",
    description="Reveal plan or reflection text at a step.",
    target="step", applies_to_kinds=("plan", "reflect"), reveals=("plan_text",),
)


class PlanProbe:
    spec = SPEC

    def execute(self, trace: Trace, step_index: int | None) -> Evidence:
        s = trace.step(step_index)
        if s is None or s.kind not in SPEC.applies_to_kinds or s.plan_text is None:
            return failed(SPEC, step_index, "no plan or reflection text at this step")
        return Evidence(SPEC.id, step_index, True, {"plan_text": s.plan_text})


register(PlanProbe())
