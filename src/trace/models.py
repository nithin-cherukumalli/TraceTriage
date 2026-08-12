"""Core data model. Mirrors schemas/trace_schema.json.

The one invariant that everything else rests on: the environment owns `Trace` (and
therefore `GroundTruth`); a policy only ever receives an `Observation`. Weakening this
silently invalidates every experiment, so `tests/test_contract.py` walks the object graph
and asserts a policy can never reach a `GroundTruth`.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class Mechanism(str, Enum):
    H1_PLANNING = "H1_planning"
    H2_TOOL = "H2_tool"
    H3_CONTEXT = "H3_context"
    H4_EXTERNAL = "H4_external"
    H5_UNKNOWN = "H5_unknown"

    @classmethod
    def predictable(cls) -> tuple["Mechanism", ...]:
        """H5 is never predicted. It is reached by escalation only."""
        return (cls.H1_PLANNING, cls.H2_TOOL, cls.H3_CONTEXT, cls.H4_EXTERNAL)


@dataclass(frozen=True)
class ToolCall:
    name: str
    arguments: dict[str, Any]
    schema: dict[str, Any] | None = None
    raw_output: str | None = None
    status: str = "ok"                 # ok | error | timeout
    latency_ms: int = 0
    http_status: int | None = None


@dataclass(frozen=True)
class RetrievedContext:
    query: str | None
    documents: list[str] = field(default_factory=list)
    scores: list[float] = field(default_factory=list)


@dataclass(frozen=True)
class Step:
    index: int
    kind: str                          # plan | tool_call | retrieval | reflect | final
    summary: str                       # VISIBLE. Leakage rule L2 applies.
    plan_text: str | None = None
    tool_call: ToolCall | None = None
    retrieval: RetrievedContext | None = None
    replay_record: dict[str, Any] | None = None


@dataclass(frozen=True)
class StepHeader:
    """The VISIBLE tier of a step: everything a policy gets before paying for a probe.

    Amendment A1 (2026-08-12) added `tool_name` and `tool_arguments`. Argument VALUES are
    now free; the tool's declared SCHEMA is not. Seeing `amount="45.00"` tells you what was
    sent; it does not tell you what the tool required. That gap is what a schema probe buys.
    """
    index: int
    kind: str
    summary: str
    tool_name: str | None = None
    tool_arguments: dict[str, Any] | None = None


@dataclass(frozen=True)
class GroundTruth:
    """HIDDEN."""
    mechanism: Mechanism
    family: str
    root_cause_step: int               # first meaningful wrong step (localization target)
    crash_step: int                    # where it surfaced (NOT the target)
    in_taxonomy: bool = True
    distractor_steps: tuple[int, ...] = ()
    notes: str = ""


@dataclass(frozen=True)
class Trace:
    trace_id: str
    task: str
    steps: list[Step]
    final_result: str = ""
    final_error: str | None = None
    reference_trace_id: str | None = None
    ground_truth: GroundTruth | None = None

    def step(self, index: int | None) -> Step | None:
        if index is None:
            return None
        for s in self.steps:
            if s.index == index:
                return s
        return None

    def headers(self) -> list[StepHeader]:
        """Project the trace down to its VISIBLE tier. The only door to a policy."""
        return [
            StepHeader(
                index=s.index, kind=s.kind, summary=s.summary,
                tool_name=s.tool_call.name if s.tool_call else None,
                # Copied, not referenced: a policy must not be able to mutate the corpus.
                tool_arguments=dict(s.tool_call.arguments) if s.tool_call else None,
            )
            for s in self.steps
        ]


@dataclass(frozen=True)
class Evidence:
    probe_id: str
    step_index: int | None
    ok: bool
    payload: dict[str, Any] = field(default_factory=dict)
    note: str = ""


@dataclass
class Observation:
    """The policy's entire view of the world. Holds no Trace and no GroundTruth."""
    task: str
    headers: list[StepHeader]
    final_result: str
    final_error: str | None
    has_reference_trace: bool
    evidence: list[Evidence] = field(default_factory=list)
    budget_remaining: int = 0
    cost_spent: float = 0.0

    def evidence_for(self, probe_id: str) -> list[Evidence]:
        return [e for e in self.evidence if e.probe_id == probe_id]

    def probed(self, probe_id: str, step_index: int | None) -> bool:
        return any(e.probe_id == probe_id and e.step_index == step_index
                   for e in self.evidence)

    def steps_of_kind(self, *kinds: str) -> list[int]:
        return [h.index for h in self.headers if h.kind in kinds]

    def header(self, index: int) -> StepHeader | None:
        for h in self.headers:
            if h.index == index:
                return h
        return None

    def tool_steps(self, name: str | None = None) -> list[int]:
        return [h.index for h in self.headers
                if h.tool_name is not None and (name is None or h.tool_name == name)]


def make_observation(trace: Trace, budget: int) -> Observation:
    """Build the policy's view. This function is the ONLY sanctioned path from Trace to
    Observation, so the visibility boundary has exactly one place to audit."""
    return Observation(
        task=trace.task,
        headers=trace.headers(),
        final_result=trace.final_result,
        final_error=trace.final_error,
        has_reference_trace=trace.reference_trace_id is not None,
        budget_remaining=budget,
    )
