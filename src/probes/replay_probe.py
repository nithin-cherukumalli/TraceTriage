"""Replay a tool call against its PRESERVED external observation.

Replay is not rerun. This probe never re-executes anything; it compares the recorded
response against the preserved observation captured at trace time.

Verdicts:
  none            recorded output matches the preserved observation
  output_differs  they disagree -> the external world was nondeterministic
  unavailable     no preserved observation exists -> replay is impossible here

`unavailable` is a first-class answer, not an error. It is how the replay-vs-rerun
distinction becomes measurable: on real datasets (TRAIL) this probe returns `unavailable`
on every case, which is a finding about tracing infrastructure rather than a bug here.
"""
from __future__ import annotations

from trace.models import Evidence, Trace
from .base import ProbeSpec, failed, register

SPEC = ProbeSpec(
    id="replay_tool_call",
    description="Replay a tool call against its preserved external observation.",
    target="step", applies_to_kinds=("tool_call",),
    reveals=("replay_record", "divergence"),
)


class ReplayProbe:
    spec = SPEC

    def execute(self, trace: Trace, step_index: int | None) -> Evidence:
        s = trace.step(step_index)
        if s is None or s.tool_call is None:
            return failed(SPEC, step_index, "not a tool call")
        if s.replay_record is None:
            return Evidence(SPEC.id, step_index, True,
                            {"replay_record": None, "divergence": "unavailable"},
                            note="no preserved observation; replay is not possible")
        preserved = s.replay_record.get("output")
        divergence = "none" if preserved == s.tool_call.raw_output else "output_differs"
        return Evidence(SPEC.id, step_index, True,
                        {"replay_record": s.replay_record, "divergence": divergence})


register(ReplayProbe())
