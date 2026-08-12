"""Belief state over H1-H4 plus an explicit unexplained mass that drives escalation.

Deliberately a flat categorical with hand-declared likelihoods. No learning, no
information gain, no POMDP -- those are the ablation ladder, not v0. Keeping it this
simple is the point: a reviewer can read exactly what knowledge was injected.

Evidence is reduced to a fixed vocabulary of SIGNATURES before it touches the belief, in
two passes:

  * `single_signatures(ev)` -- what one probe result says on its own.
  * `cross_signatures(evidence, task)` -- what two probe results say only when held
    against each other. `misunderstood_output` and `wrong_reasoning_decision` are
    invisible to any single probe; they exist precisely to make sequential evidence
    gathering matter.

Belief is rebuilt from the full evidence list each turn rather than updated incrementally.
Cross-evidence signatures make incremental updating order-dependent, and a policy that
scores differently depending on the order it happened to probe in would be measuring the
wrong thing.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from trace.models import Evidence, Mechanism

M = Mechanism

# P(signature | mechanism). Hand-authored and declared in one place so it can be audited.
# Rows are observations, not a joint model; the naive independence assumption between rows
# is a known defect (see research/discussion-record.md, M4).
LIKELIHOOD: dict[str, dict[Mechanism, float]] = {
    # -- schema_probe
    "schema_invalid":     {M.H1_PLANNING: 0.05, M.H2_TOOL: 0.85, M.H3_CONTEXT: 0.05, M.H4_EXTERNAL: 0.05},
    "schema_valid":       {M.H1_PLANNING: 0.95, M.H2_TOOL: 0.30, M.H3_CONTEXT: 0.95, M.H4_EXTERNAL: 0.95},
    # -- tool_output_probe
    "transport_failure":  {M.H1_PLANNING: 0.02, M.H2_TOOL: 0.05, M.H3_CONTEXT: 0.02, M.H4_EXTERNAL: 0.92},
    "semantic_refusal":   {M.H1_PLANNING: 0.50, M.H2_TOOL: 0.45, M.H3_CONTEXT: 0.55, M.H4_EXTERNAL: 0.05},
    "output_clean":       {M.H1_PLANNING: 0.48, M.H2_TOOL: 0.50, M.H3_CONTEXT: 0.43, M.H4_EXTERNAL: 0.05},
    # -- context_probe
    "context_missing":    {M.H1_PLANNING: 0.05, M.H2_TOOL: 0.05, M.H3_CONTEXT: 0.88, M.H4_EXTERNAL: 0.05},
    "context_stale":      {M.H1_PLANNING: 0.05, M.H2_TOOL: 0.05, M.H3_CONTEXT: 0.88, M.H4_EXTERNAL: 0.05},
    "context_clean":      {M.H1_PLANNING: 0.95, M.H2_TOOL: 0.95, M.H3_CONTEXT: 0.20, M.H4_EXTERNAL: 0.95},
    # -- plan_probe
    "plan_incomplete":    {M.H1_PLANNING: 0.82, M.H2_TOOL: 0.08, M.H3_CONTEXT: 0.08, M.H4_EXTERNAL: 0.05},
    "plan_sound":         {M.H1_PLANNING: 0.25, M.H2_TOOL: 0.92, M.H3_CONTEXT: 0.92, M.H4_EXTERNAL: 0.95},
    # -- replay_probe
    "replay_diverges":    {M.H1_PLANNING: 0.05, M.H2_TOOL: 0.05, M.H3_CONTEXT: 0.05, M.H4_EXTERNAL: 0.75},
    "replay_matches":     {M.H1_PLANNING: 0.95, M.H2_TOOL: 0.95, M.H3_CONTEXT: 0.95, M.H4_EXTERNAL: 0.25},
    "replay_unavailable": {M.H1_PLANNING: 1.00, M.H2_TOOL: 1.00, M.H3_CONTEXT: 1.00, M.H4_EXTERNAL: 1.00},
    # -- cross-evidence (require two probes to observe at all)
    "routing_mismatch":   {M.H1_PLANNING: 0.88, M.H2_TOOL: 0.05, M.H3_CONTEXT: 0.05, M.H4_EXTERNAL: 0.02},
    "plan_execution_mismatch":
                          {M.H1_PLANNING: 0.88, M.H2_TOOL: 0.06, M.H3_CONTEXT: 0.04, M.H4_EXTERNAL: 0.02},
    "reasoning_contradicts_context":
                          {M.H1_PLANNING: 0.88, M.H2_TOOL: 0.05, M.H3_CONTEXT: 0.10, M.H4_EXTERNAL: 0.02},
    "plan_contradicts_output":
                          {M.H1_PLANNING: 0.15, M.H2_TOOL: 0.85, M.H3_CONTEXT: 0.05, M.H4_EXTERNAL: 0.02},
}

#: Signatures that carry no information and must not move the belief.
UNINFORMATIVE = {"replay_unavailable"}

#: Signatures that mark a step as suspicious. Used for localization read-out.
ANOMALOUS = {
    "schema_invalid", "context_stale", "context_missing", "plan_incomplete",
    "transport_failure", "replay_diverges", "routing_mismatch",
    "reasoning_contradicts_context", "plan_contradicts_output",
    "plan_execution_mismatch",
}

#: Tools a plan may name. Used only to detect plan/execution mismatch.
KNOWN_TOOLS = ("lookup_order", "check_eligibility", "issue_refund", "notify_customer",
               "fetch_invoice")

# Surface cues used to reduce plan text to a signature. Authored knowledge, and a
# circularity vector -- see research/discussion-record.md. Kept keyword-shallow on
# purpose: a cleverer reader here would quietly do the diagnosis the policy is meant to be
# doing, and the experiment would stop measuring probe selection.
VERIFY_MARKERS = ("verify", "check", "confirm", "validate")
STOP_MARKERS = ("best guess", "answer directly", "skip", "assume", "without waiting")

_WORKFLOW_RE = re.compile(r"route to the (\w+) workflow")
_LIMIT_RE = re.compile(r"within (\d+) days")
_AGE_RE = re.compile(r"(\d+) days old")
_ELIGIBLE_RE = re.compile(r"\bis eligible\b|\bqualifies\b")


# --------------------------------------------------------------------------- signatures

def single_signatures(ev: Evidence) -> list[str]:
    """What one probe result says on its own."""
    if not ev.ok:
        return []
    p, pid = ev.payload, ev.probe_id

    if pid == "validate_tool_args":
        return ["schema_invalid" if not p.get("schema_valid") else "schema_valid"]

    if pid == "inspect_tool_output":
        if p.get("status") == "timeout" or (p.get("http_status") or 0) >= 500:
            return ["transport_failure"]
        if p.get("status") == "error":
            return ["semantic_refusal"]
        return ["output_clean"]

    if pid == "inspect_context":
        docs = p.get("documents") or []
        if not docs:
            return ["context_missing"]
        joined = " ".join(docs).lower()
        if "superseded" in joined or "deprecated" in joined:
            return ["context_stale"]
        if max(p.get("scores") or [1.0]) < 0.35:
            return ["context_stale"]
        return ["context_clean"]

    if pid == "inspect_plan":
        text = (p.get("plan_text") or "").lower()
        stops = any(m in text for m in STOP_MARKERS)
        verifies = any(m in text for m in VERIFY_MARKERS)
        return ["plan_incomplete" if stops or not verifies else "plan_sound"]

    if pid == "replay_tool_call":
        return {"none": ["replay_matches"], "output_differs": ["replay_diverges"],
                "unavailable": ["replay_unavailable"]}.get(p.get("divergence"), [])

    return []


def cross_signatures(evidence: list[Evidence], task: str = "",
                     executed_tools: tuple[str, ...] = ()) -> list[str]:
    """What only becomes visible when two observations are held against each other.

    Nothing here can fire from a single probe. That is the point: these are the families a
    one-shot reader of any single field cannot see. `executed_tools` comes from the VISIBLE
    tier (amendment A1), so plan/execution mismatch costs one probe rather than two.
    """
    out: list[str] = []
    plans = [e for e in evidence if e.probe_id == "inspect_plan" and e.ok]
    outputs = [e for e in evidence if e.probe_id == "inspect_tool_output" and e.ok]
    contexts = [e for e in evidence if e.probe_id == "inspect_context" and e.ok]

    # wrong_tool_selected: the plan names a tool the run never executed. Needs the plan
    # probe plus the visible tool names -- no single probe shows it.
    for pe in plans:
        text = (pe.payload.get("plan_text") or "").lower()
        named = {t for t in KNOWN_TOOLS if t in text}
        if named and not named.issubset(set(executed_tools)):
            out.append("plan_execution_mismatch")
            break

    # incorrect_routing: the plan names a workflow the task did not ask for.
    for pe in plans:
        m = _WORKFLOW_RE.search((pe.payload.get("plan_text") or "").lower())
        if m and task and m.group(1) not in task.lower() and "routing_mismatch" not in out:
            out.append("routing_mismatch")
            break

    # wrong_reasoning_decision: retrieved policy states a limit, the plan asserts the
    # order qualifies, and the order is older than that limit.
    for ce in contexts:
        docs = " ".join(ce.payload.get("documents") or []).lower()
        limit = _LIMIT_RE.search(docs)
        if not limit:
            continue
        for pe in plans:
            text = (pe.payload.get("plan_text") or "").lower()
            age = _AGE_RE.search(text)
            if age and _ELIGIBLE_RE.search(text) and int(age.group(1)) > int(limit.group(1)):
                out.append("reasoning_contradicts_context")
                break
        if "reasoning_contradicts_context" in out:
            break

    # misunderstood_output: a tool answered cleanly and negatively; the plan reports the
    # opposite. Requires the output probe AND the plan probe.
    for oe in outputs:
        raw = (oe.payload.get("raw_output") or "").lower()
        if oe.payload.get("status") != "ok" or '"eligible":false' not in raw.replace(" ", ""):
            continue
        for pe in plans:
            text = (pe.payload.get("plan_text") or "").lower()
            if pe.step_index is not None and oe.step_index is not None \
                    and pe.step_index > oe.step_index and _ELIGIBLE_RE.search(text):
                out.append("plan_contradicts_output")
                break
        if "plan_contradicts_output" in out:
            break

    return out


def all_signatures(evidence: list[Evidence], task: str = "",
                   executed_tools: tuple[str, ...] = ()) -> list[str]:
    sigs: list[str] = []
    for ev in evidence:
        sigs.extend(single_signatures(ev))
    sigs.extend(cross_signatures(evidence, task, executed_tools))
    return sigs


def anomalous_steps(evidence: list[Evidence]) -> list[int]:
    """Steps a single probe flagged as suspicious. Used for localization read-out."""
    return sorted({e.step_index for e in evidence
                   if e.ok and e.step_index is not None
                   and set(single_signatures(e)) & ANOMALOUS})


# --------------------------------------------------------------------------- belief

@dataclass
class Belief:
    probs: dict[Mechanism, float] = field(
        default_factory=lambda: {m: 0.25 for m in Mechanism.predictable()})
    unexplained: float = 0.0
    seen: list[str] = field(default_factory=list)

    @classmethod
    def rebuild(cls, evidence: list[Evidence], task: str = "",
                executed_tools: tuple[str, ...] = ()) -> "Belief":
        """Recompute from the whole evidence list. Order-independent by construction."""
        b = cls()
        for sig in all_signatures(evidence, task, executed_tools):
            b.update(sig)
        # A full budget spent without the posterior committing is itself informative: it
        # says the taxonomy may not contain this failure. This -- not a magic detector --
        # is what makes H5 reachable.
        return b

    def update(self, signature: str) -> None:
        if signature in UNINFORMATIVE:
            self.seen.append(signature)
            return
        row = LIKELIHOOD.get(signature)
        if row is None:
            self.unexplained = min(1.0, self.unexplained + 0.25)
            return
        self.seen.append(signature)
        posterior = {m: self.probs[m] * row[m] for m in self.probs}
        total = sum(posterior.values())
        if total <= 0:
            self.unexplained = min(1.0, self.unexplained + 0.5)
            return
        self.probs = {m: p / total for m, p in posterior.items()}

    def top(self) -> Mechanism:
        return max(self.probs, key=self.probs.get)

    def top_prob(self) -> float:
        return max(self.probs.values())

    def top2(self) -> tuple[Mechanism, Mechanism]:
        ranked = sorted(self.probs, key=self.probs.get, reverse=True)
        return ranked[0], ranked[1]

    def margin(self) -> float:
        a, b = self.top2()
        return self.probs[a] - self.probs[b]

    def saw_anomaly(self) -> bool:
        return bool(set(self.seen) & ANOMALOUS)


# Backwards-compatible alias used by older call sites.
signatures = single_signatures
