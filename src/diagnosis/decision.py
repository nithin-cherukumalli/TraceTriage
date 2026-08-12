"""The diagnostic decision process: actions, budget accounting and the episode loop.

The environment owns the Trace and therefore the GroundTruth. A policy receives only an
Observation. This asymmetry is the experiment; `tests/test_contract.py` enforces it.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable

from probes.base import PROBE_COST, get_probe
from probes.state_compare_probe import StateCompareProbe
from trace.models import Mechanism, Observation, Trace, make_observation

DEFAULT_BUDGET = 6


class ActionType(str, Enum):
    PROBE = "probe"
    DIAGNOSE = "diagnose"
    ESCALATE = "escalate"


@dataclass(frozen=True)
class Action:
    type: ActionType
    probe_id: str | None = None
    step_index: int | None = None
    # DIAGNOSE carries attribution and localization together; they are scored separately.
    mechanism: Mechanism | None = None
    localized_step: int | None = None
    reason: str = ""

    @staticmethod
    def probe(probe_id: str, step_index: int | None = None) -> "Action":
        return Action(ActionType.PROBE, probe_id=probe_id, step_index=step_index)

    @staticmethod
    def diagnose(mechanism: Mechanism, localized_step: int, reason: str = "") -> "Action":
        return Action(ActionType.DIAGNOSE, mechanism=mechanism,
                      localized_step=localized_step, reason=reason)

    @staticmethod
    def escalate(reason: str) -> "Action":
        return Action(ActionType.ESCALATE, reason=reason)


@dataclass
class Episode:
    """One diagnostic run. Everything needed to score it and to audit it by hand."""
    trace_id: str
    policy: str
    terminal: str                       # diagnose | escalate | budget_exhausted
    mechanism: Mechanism | None
    localized_step: int | None
    reason: str
    n_probes: int
    probe_cost: float
    transcript: list[dict[str, Any]] = field(default_factory=list)


def run_episode(trace: Trace, policy, budget: int = DEFAULT_BUDGET,
                reference_lookup: Callable[[str], Trace | None] | None = None) -> Episode:
    obs = make_observation(trace, budget)
    policy.reset(obs)

    # The trace-level probe needs a reference resolver. Injected here so the probe never
    # touches ground truth or the corpus directly.
    probe = get_probe("compare_known_good")
    if isinstance(probe, StateCompareProbe):
        probe.bind(reference_lookup or (lambda _: None))

    transcript: list[dict[str, Any]] = []
    n_probes = 0
    spent = 0.0

    while True:
        action = policy.act(obs)

        if action.type is ActionType.PROBE:
            if n_probes >= budget:
                # Running out of budget is a forced escalation, never a free guess.
                transcript.append({"action": "budget_exhausted"})
                return Episode(trace.trace_id, policy.name, "budget_exhausted", None,
                               None, "probe budget exhausted", n_probes, spent, transcript)
            evidence = get_probe(action.probe_id).execute(trace, action.step_index)
            charge = PROBE_COST[action.probe_id]        # contract rule 2: always full price
            n_probes += 1
            spent += charge
            obs.evidence.append(evidence)
            obs.budget_remaining = budget - n_probes
            obs.cost_spent = spent
            transcript.append({"action": "probe", "probe_id": action.probe_id,
                               "step": action.step_index, "ok": evidence.ok,
                               "cost": charge, "note": evidence.note})
            continue

        if action.type is ActionType.DIAGNOSE:
            transcript.append({"action": "diagnose",
                               "mechanism": action.mechanism.value,
                               "localized_step": action.localized_step,
                               "reason": action.reason})
            return Episode(trace.trace_id, policy.name, "diagnose", action.mechanism,
                           action.localized_step, action.reason, n_probes, spent,
                           transcript)

        transcript.append({"action": "escalate", "reason": action.reason})
        return Episode(trace.trace_id, policy.name, "escalate", None, None,
                       action.reason, n_probes, spent, transcript)
