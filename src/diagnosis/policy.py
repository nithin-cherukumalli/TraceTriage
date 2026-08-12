"""Policies. All implement: reset(obs) -> None, act(obs) -> Action, and carry a `name`.

Build order matters and is deliberate: B0 -> B2 -> B2-strong -> P. The optimal fixed
order is found before the adaptive policy exists, so the adaptive number is never seen
first and rationalised backwards (research/preregistration.md, K1).
"""
from __future__ import annotations

import random
from typing import Protocol

from probes.base import PROBE_COST
from trace.models import Mechanism, Observation

from .belief import ANOMALOUS, Belief, anomalous_steps
from .decision import Action


class Policy(Protocol):
    name: str
    def reset(self, obs: Observation) -> None: ...
    def act(self, obs: Observation) -> Action: ...


def _last_step(obs: Observation) -> int:
    return obs.headers[-1].index if obs.headers else 0


def _executed_tools(obs: Observation) -> tuple[str, ...]:
    """Tool names from the VISIBLE tier. Free under amendment A1."""
    return tuple(h.tool_name for h in obs.headers if h.tool_name)


def _rebuild(obs: Observation) -> Belief:
    return Belief.rebuild(obs.evidence, obs.task, _executed_tools(obs))


def _crash_step(obs: Observation) -> int:
    """Best visible guess at where the failure surfaced: last non-final step."""
    for h in reversed(obs.headers):
        if h.kind != "final":
            return h.index
    return _last_step(obs)


# --------------------------------------------------------------------------- B0
class TrivialPolicy:
    """Sanity floor. Modal mechanism, localize to the crash step, zero probes.

    Kill criterion K2 fires if this exceeds 0.40 attribution accuracy.
    """
    name = "b0_trivial"

    def __init__(self, modal: Mechanism = Mechanism.H2_TOOL):
        self.modal = modal

    def reset(self, obs: Observation) -> None:
        pass

    def act(self, obs: Observation) -> Action:
        return Action.diagnose(self.modal, _crash_step(obs), "modal prior, no evidence")


# --------------------------------------------------------------------------- random
class RandomPolicy:
    """Uniform probing then uniform guess. Scaffolding and a noise reference."""
    name = "random"

    def __init__(self, seed: int = 0, n_probes: int = 3):
        self.rng = random.Random(seed)
        self.n_probes = n_probes
        self._used = 0

    def reset(self, obs: Observation) -> None:
        self._used = 0

    def act(self, obs: Observation) -> Action:
        if self._used < min(self.n_probes, obs.budget_remaining):
            self._used += 1
            return Action.probe(self.rng.choice(list(PROBE_COST)),
                                self.rng.choice([h.index for h in obs.headers]))
        return Action.diagnose(self.rng.choice(Mechanism.predictable()),
                               self.rng.choice([h.index for h in obs.headers]), "random")


# --------------------------------------------------------------------------- B2
DEFAULT_CHECKLIST = (
    "inspect_tool_output",
    "validate_tool_args",
    "inspect_context",
    "inspect_plan",
    "compare_known_good",
    "replay_tool_call",
)


class ChecklistPolicy:
    """Baseline 2 -- a fixed debugging procedure.

    Probe *type* order is fixed. Step targeting is the naive rule every debugging guide
    gives: start at the failing step and walk backwards. B2-strong varies the type order;
    neither can condition on what it has already seen, which is the whole contrast.
    """
    name = "b2_checklist"

    def __init__(self, order: tuple[str, ...] = DEFAULT_CHECKLIST, name: str | None = None):
        self.order = order
        if name:
            self.name = name
        self._plan: list[tuple[str, int | None]] = []
        self._i = 0

    def reset(self, obs: Observation) -> None:
        self._i = 0
        self._plan = self._build_plan(obs)

    KINDS = {"inspect_tool_output": ("tool_call",), "validate_tool_args": ("tool_call",),
             "inspect_context": ("retrieval",), "inspect_plan": ("plan", "reflect"),
             "replay_tool_call": ("tool_call",)}

    def _build_plan(self, obs: Observation) -> list[tuple[str, int | None]]:
        """Expand the fixed type order into (probe, step) pairs.

        Each probe type expands to ALL applicable steps, walking backwards from the crash
        -- the standard "start at the failure and work back" rule. This makes B2 a strong
        baseline rather than a strawman: with a 6-probe budget it can spend every probe
        walking one type backwards, or spread across types, depending on the order under
        search. B2-strong searches that ordering on dev.
        """
        plan: list[tuple[str, int | None]] = []
        for pid in self.order:
            if pid == "compare_known_good":
                if obs.has_reference_trace:
                    plan.append((pid, None))
                continue
            for step in sorted(obs.steps_of_kind(*self.KINDS[pid]), reverse=True):
                plan.append((pid, step))
        return plan

    def act(self, obs: Observation) -> Action:
        if self._i < len(self._plan) and obs.budget_remaining > 0:
            pid, step = self._plan[self._i]
            self._i += 1
            return Action.probe(pid, step)
        return Action.diagnose(_rebuild(obs).top(), self._localize(obs), "fixed checklist")

    def _localize(self, obs: Observation) -> int:
        """Same evidence-driven rule the adaptive policy uses.

        Given to B2 deliberately: localization must not be the thing that makes the
        adaptive policy look good. Any gap on the secondary task should come from which
        evidence was gathered, not from a smarter read-out.
        """
        for e in obs.evidence:
            if e.probe_id == "compare_known_good" and e.ok:
                fd = e.payload.get("first_divergent_step")
                if fd is not None:
                    return fd
        steps = anomalous_steps(obs.evidence)
        return steps[0] if steps else _crash_step(obs)


def search_best_fixed_order(dev_traces, run_fn, score_fn, max_orders: int = 200,
                            seed: int = 0):
    """B2-strong: search probe-type orderings on the DEV split only.

    Greedy prefix construction, then random restarts. Returns (order, score). Called from
    evaluation/experiment_runner.py before the adaptive policy is instantiated.
    """
    rng = random.Random(seed)
    ids = list(PROBE_COST)
    best_order, best_score = tuple(ids), -1.0

    order: list[str] = []
    remaining = list(ids)
    while remaining:                                    # greedy prefix
        scored = []
        for pid in remaining:
            cand = tuple(order + [pid] + [x for x in remaining if x != pid])
            scored.append((score_fn(run_fn(dev_traces, ChecklistPolicy(cand))), pid))
        scored.sort(reverse=True)
        order.append(scored[0][1])
        remaining.remove(scored[0][1])
    greedy = tuple(order)
    best_order, best_score = greedy, score_fn(run_fn(dev_traces, ChecklistPolicy(greedy)))

    for _ in range(max_orders):                          # random restarts
        cand = tuple(rng.sample(ids, len(ids)))
        s = score_fn(run_fn(dev_traces, ChecklistPolicy(cand)))
        if s > best_score:
            best_order, best_score = cand, s
    return best_order, best_score


# --------------------------------------------------------------------------- P
class AdaptivePolicy:
    """Proposed policy -- adaptive discriminative probe selection.

    Loop: belief over H1-H4 -> take the top two -> choose the applicable (probe, step)
    pair that best separates that pair per unit cost -> observe -> update -> stop when
    the posterior is confident, the unexplained mass is high, or the budget runs out.

    NOT information gain. NOT a POMDP. Those are the ablation ladder above this rung.

    CAVEAT: DISCRIMINATION below is authored knowledge and is a circularity vector. It was
    written against research/probe-contract.md alone, before src/trace/synthesize.py
    existed. The v0 claim is therefore "a cheap authored discrimination prior beats the
    best fixed order", not "adaptivity emerges".
    """
    name = "p_adaptive"

    # D[probe][{Hi,Hj}] in [0,1]: expected power to separate that pair.
    DISCRIMINATION: dict[str, dict[frozenset, float]] = {
        "validate_tool_args": {
            frozenset({Mechanism.H2_TOOL, Mechanism.H1_PLANNING}): 0.85,
            frozenset({Mechanism.H2_TOOL, Mechanism.H3_CONTEXT}): 0.85,
            frozenset({Mechanism.H2_TOOL, Mechanism.H4_EXTERNAL}): 0.80,
        },
        "inspect_tool_output": {
            frozenset({Mechanism.H4_EXTERNAL, Mechanism.H1_PLANNING}): 0.90,
            frozenset({Mechanism.H4_EXTERNAL, Mechanism.H2_TOOL}): 0.85,
            frozenset({Mechanism.H4_EXTERNAL, Mechanism.H3_CONTEXT}): 0.90,
            frozenset({Mechanism.H1_PLANNING, Mechanism.H3_CONTEXT}): 0.25,
        },
        "inspect_context": {
            frozenset({Mechanism.H3_CONTEXT, Mechanism.H1_PLANNING}): 0.85,
            frozenset({Mechanism.H3_CONTEXT, Mechanism.H2_TOOL}): 0.85,
            frozenset({Mechanism.H3_CONTEXT, Mechanism.H4_EXTERNAL}): 0.80,
        },
        "inspect_plan": {
            frozenset({Mechanism.H1_PLANNING, Mechanism.H2_TOOL}): 0.80,
            frozenset({Mechanism.H1_PLANNING, Mechanism.H3_CONTEXT}): 0.70,
            frozenset({Mechanism.H1_PLANNING, Mechanism.H4_EXTERNAL}): 0.75,
        },
        "replay_tool_call": {
            frozenset({Mechanism.H4_EXTERNAL, Mechanism.H1_PLANNING}): 0.60,
            frozenset({Mechanism.H4_EXTERNAL, Mechanism.H2_TOOL}): 0.55,
            frozenset({Mechanism.H4_EXTERNAL, Mechanism.H3_CONTEXT}): 0.60,
        },
        "compare_known_good": {},   # localization signal, weak for attribution
    }

    APPLIES_TO = {
        "inspect_plan": ("plan", "reflect"),
        "validate_tool_args": ("tool_call",),
        "inspect_tool_output": ("tool_call",),
        "inspect_context": ("retrieval",),
        "replay_tool_call": ("tool_call",),
    }

    def __init__(self, tau_diagnose: float = 0.70, tau_escalate: float = 0.50):
        self.tau_diagnose = tau_diagnose
        self.tau_escalate = tau_escalate
        self._belief = Belief()
        self._ingested = 0

    def reset(self, obs: Observation) -> None:
        self._belief = Belief()

    def _select(self, obs: Observation):
        pair = frozenset(self._belief.top2())
        best, best_value = None, 0.0
        for pid, table in self.DISCRIMINATION.items():
            power = table.get(pair, 0.05)
            for step in self._targets(obs, pid):
                if obs.probed(pid, step):
                    continue
                value = power / PROBE_COST[pid]
                if value > best_value:
                    best, best_value = (pid, step), value
        return best

    def _targets(self, obs: Observation, pid: str) -> list[int | None]:
        if pid == "compare_known_good":
            return [None] if obs.has_reference_trace else []
        steps = obs.steps_of_kind(*self.APPLIES_TO[pid])
        # Step targeting is where adaptivity is expected to pay: prefer the step nearest
        # the crash first, then walk backwards through earlier candidates.
        return sorted(steps, reverse=True)

    def _localize(self, obs: Observation) -> int:
        """Localization uses evidence, not the crash step.

        Priority: an explicit first-divergence signal; else the earliest step whose
        evidence was anomalous; else fall back to the crash step.
        """
        for e in obs.evidence:
            if e.probe_id == "compare_known_good" and e.ok:
                fd = e.payload.get("first_divergent_step")
                if fd is not None:
                    return fd
        steps = anomalous_steps(obs.evidence)
        return steps[0] if steps else _crash_step(obs)

    def act(self, obs: Observation) -> Action:
        b = self._belief = _rebuild(obs)

        if b.unexplained >= self.tau_escalate:
            return Action.escalate(f"unexplained evidence mass {b.unexplained:.2f}")
        if b.top_prob() >= self.tau_diagnose and b.saw_anomaly():
            return Action.diagnose(b.top(), self._localize(obs),
                                   f"posterior {b.top_prob():.2f}")
        if obs.budget_remaining <= 0:
            # Escalation from insufficiency: a full budget spent with no anomalous
            # evidence anywhere is the signature of a failure outside the taxonomy.
            if not b.saw_anomaly() or b.top_prob() < 0.45:
                return Action.escalate("budget spent without decisive evidence")
            return Action.diagnose(b.top(), self._localize(obs), "budget spent")

        choice = self._select(obs)
        if choice is None:
            return Action.diagnose(b.top(), self._localize(obs), "no probes left to run")
        return Action.probe(*choice)


# --------------------------------------------------------------- B-visible-only (K5 guard)
class VisibleOnlyPolicy:
    """Zero probes. Hand rules over the VISIBLE tier only.

    Exists because contract amendment A1 moved tool arguments into the visible tier. If
    this policy scores well, the free information is doing the work and the probe set is
    decorative -- kill criterion K5. It is meant to be a genuinely good use of the visible
    tier, not a strawman: a weak version here would hide exactly the problem it is built
    to detect.
    """
    name = "b_visible_only"

    def reset(self, obs: Observation) -> None:
        pass

    def act(self, obs: Observation) -> Action:
        err = (obs.final_error or "").lower()
        step = _crash_step(obs)

        # Silent failure: nothing raised, so the visible tier offers no purchase at all.
        if not err:
            return Action.escalate("no surface error; visible tier is uninformative")

        if "timeout" in err or "unavailable" in err or "5" == err[:1]:
            return Action.diagnose(Mechanism.H4_EXTERNAL, step, "transport wording in error")
        if "validation" in err:
            return Action.diagnose(Mechanism.H2_TOOL, step, "validation wording in error")

        # Argument-shape heuristic, newly possible under amendment A1: a numeric-looking
        # value passed as a string is the visible fingerprint of arg_type_violation.
        for h in obs.headers:
            for value in (h.tool_arguments or {}).values():
                if isinstance(value, str) and _looks_numeric(value):
                    return Action.diagnose(Mechanism.H2_TOOL, h.index,
                                           "numeric value passed as string")
        if "policy" in err:
            return Action.diagnose(Mechanism.H3_CONTEXT, step, "policy wording in error")
        if "precondition" in err or "incomplete" in err:
            return Action.diagnose(Mechanism.H1_PLANNING, step, "precondition wording in error")
        return Action.diagnose(Mechanism.H2_TOOL, step, "fallback to modal mechanism")


def _looks_numeric(value: str) -> bool:
    try:
        float(value)
        return True
    except ValueError:
        return False
