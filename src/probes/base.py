"""Probe protocol, cost table and registry. Implements research/probe-contract.md (FROZEN).

Costs live here rather than in a config file so that a diff to a probe price is visible in
code review next to the contract that froze it.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from trace.models import Evidence, Trace

# FROZEN — see research/probe-contract.md. Sensitivity sweep required before publication.
PROBE_COST: dict[str, float] = {
    "inspect_plan": 1.0,
    "validate_tool_args": 1.0,
    "inspect_tool_output": 1.5,
    "inspect_context": 2.0,
    "compare_known_good": 3.0,
    "replay_tool_call": 4.0,
}


@dataclass(frozen=True)
class ProbeSpec:
    id: str
    description: str
    target: str                        # "step" | "trace"
    applies_to_kinds: tuple[str, ...]
    reveals: tuple[str, ...]

    @property
    def cost(self) -> float:
        return PROBE_COST[self.id]


class Probe(Protocol):
    spec: ProbeSpec

    def execute(self, trace: Trace, step_index: int | None) -> Evidence:
        """Read-only unredaction. Never mutates. Never returns a diagnosis."""
        ...


def failed(spec: ProbeSpec, step_index: int | None, note: str) -> Evidence:
    """Inapplicable probe. Contract rule 2: still charged in full by the episode loop."""
    return Evidence(probe_id=spec.id, step_index=step_index, ok=False, payload={}, note=note)


_REGISTRY: dict[str, Probe] = {}


def register(probe: Probe) -> Probe:
    _REGISTRY[probe.spec.id] = probe
    return probe


def get_probe(probe_id: str) -> Probe:
    return _REGISTRY[probe_id]


def all_probes() -> dict[str, Probe]:
    return dict(_REGISTRY)


def probe_ids() -> tuple[str, ...]:
    return tuple(_REGISTRY)
