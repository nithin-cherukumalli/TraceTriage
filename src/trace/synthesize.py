"""Synthetic failure-case generator for the eleven failure families.

WRITTEN AFTER research/probe-contract.md WAS FROZEN. That ordering is the anti-circularity
device: probe semantics could not be tuned to whatever this file happens to emit.

Strategy
--------
1. **Generative, not annotative.** Each case runs a scripted support agent through a
   plausible task, perturbs exactly one component, and lets the consequences propagate.
   `root_cause_step` is where the perturbed component first emitted a wrong artefact;
   `crash_step` is where the run died. No label is written anywhere in the trace.

2. **Surface errors are deliberately ambiguous.** Drawn from a shared pool where every
   error is produced by at least two mechanisms. An earlier version wrote
   mechanism-specific strings into `final_error` and a zero-probe baseline reached 0.858
   attribution accuracy. Diagnostic detail lives in `raw_output`, behind a probe.

3. **Every case is probe-sufficient (requirement G6).** For in-taxonomy families a full
   probe sweep must recover the true mechanism. For the held-out family the invariant
   inverts: every probe returns `ok` and none yields an anomalous signature, so escalation
   follows from insufficiency rather than from a detectable marker.

4. **Two families are deliberately invisible to any single probe.**
   `misunderstood_output` and `wrong_reasoning_decision` only appear when plan text is
   held against tool output or retrieved context. They are the strongest argument in the
   project for sequential probing over one-shot reading.

5. **Distractors.** Innocent steps between root cause and crash, so "probe the failing
   step" is not a winning strategy. This is what makes step targeting -- not probe type --
   the thing an adaptive policy has to get right.
"""
from __future__ import annotations

import random
from dataclasses import dataclass

from diagnosis.hypothesis import FAMILIES, IN_TAXONOMY_FAMILIES, Family
from .models import GroundTruth, Mechanism, RetrievedContext, Step, ToolCall, Trace

# --------------------------------------------------------------------------- domain

SCHEMAS: dict[str, dict] = {
    "lookup_order": {"type": "object", "required": ["order_id"],
                     "properties": {"order_id": {"type": "string"}}},
    "check_eligibility": {"type": "object", "required": ["order_id", "days_since_purchase"],
                          "properties": {"order_id": {"type": "string"},
                                         "days_since_purchase": {"type": "integer"}}},
    "issue_refund": {"type": "object", "required": ["order_id", "amount"],
                     "properties": {"order_id": {"type": "string"},
                                    "amount": {"type": "number"}}},
    "notify_customer": {"type": "object", "required": ["order_id", "message"],
                        "properties": {"order_id": {"type": "string"},
                                       "message": {"type": "string"}}},
    "fetch_invoice": {"type": "object", "required": ["order_id"],
                      "properties": {"order_id": {"type": "string"}}},
}

#: Plans name the tools they intend to use. A plan that names a tool the run never
#: executed is a plan/execution mismatch -- observable only by combining the plan probe
#: with the VISIBLE tool names (amendment A1).
SOUND_PLAN = ("route to the refund workflow: retrieve the current policy, look up the "
              "order with lookup_order, check eligibility with check_eligibility, then "
              "issue_refund if it qualifies")

CURRENT_POLICY = "REFUND POLICY v3 (current, effective 2026-01): refunds within 30 days"
STALE_POLICY = "REFUND POLICY v1 (superseded 2025-11): refunds within 120 days"

# Surface errors are shared across mechanisms on purpose. Every entry is produced by at
# least two families and every family can produce at least two entries, so the visible
# error is suggestive but never decisive. `None` is a silent failure. Silent failures
# occur in in-taxonomy families too, so "no error" is not a free H5 detector.
SURFACE_ERRORS: dict[str, tuple[str | None, ...]] = {
    "wrong_tool_selected":         ("refund_failed", "task_incomplete"),
    "wrong_reasoning_decision":    ("refund_failed", "task_incomplete", None),
    "incorrect_routing":           ("task_incomplete", "refund_failed", None),
    "malformed_arguments":         ("refund_failed", "tool_error"),
    "schema_mismatch":             ("tool_error", "refund_failed"),
    "misunderstood_output":        ("refund_failed", None, "task_incomplete"),
    "missing_context":             ("task_incomplete", "refund_failed", None),
    "wrong_retrieved_information": ("refund_failed", "task_incomplete", None),
    "api_failure":                 ("tool_error", "refund_failed"),
    "service_unavailable":         ("tool_error", "refund_failed"),
    "silent_state_corruption":     (None, "task_incomplete", "refund_failed"),
}

SILENT_RESULTS = ("Your refund has been processed.",
                  "This order is not eligible for a refund.",
                  "I have updated your order.")
FAILED_RESULTS = ("Unable to complete the refund.",
                  "I could not finish this request.")

REFUND_TASK = "handle the customer refund request for order {oid}"
SHIPPING_TASK = "handle the customer shipping delay complaint for order {oid}"


@dataclass
class GeneratorConfig:
    seed: int = 0
    n_cases: int = 400
    include_held_out: bool = False
    held_out_fraction: float = 0.10
    #: "by_mechanism" gives a uniform prior over H1-H4 (experimental corpora).
    #: "by_family" guarantees every family appears -- necessary for small inspection
    #: corpora, where random sampling would leave families empty.
    allocation: str = "by_mechanism"
    distractor_range: tuple[int, int] = (1, 3)
    nondeterminism_rate: float = 0.4


class _Builder:
    def __init__(self, rng: random.Random, order_id: str):
        self.rng = rng
        self.order_id = order_id
        self.steps: list[Step] = []

    @property
    def next_index(self) -> int:
        return len(self.steps)

    def plan(self, text: str) -> int:
        i = self.next_index
        self.steps.append(Step(i, "plan", "draft a plan for the request", plan_text=text))
        return i

    def reflect(self, text: str, summary: str = "reconsider the plan") -> int:
        i = self.next_index
        self.steps.append(Step(i, "reflect", summary, plan_text=text))
        return i

    def retrieve(self, query: str, documents: list[str], scores: list[float],
                 summary: str) -> int:
        i = self.next_index
        self.steps.append(Step(i, "retrieval", summary,
                               retrieval=RetrievedContext(query, documents, scores)))
        return i

    def call(self, name: str, arguments: dict, raw_output: str, status: str = "ok",
             http_status: int | None = 200, latency_ms: int | None = None,
             replay_output: str | None = None, force_replay: bool | None = None) -> int:
        i = self.next_index
        if latency_ms is None:
            latency_ms = self.rng.randint(60, 400)
        keep = self.rng.random() < 0.6 if force_replay is None else force_replay
        record = ({"output": replay_output if replay_output is not None else raw_output,
                   "captured_at": "2026-08-11T09:14:22Z"} if keep else None)
        self.steps.append(Step(i, "tool_call", f"call {name}",
                               tool_call=ToolCall(name=name, arguments=arguments,
                                                  schema=SCHEMAS[name],
                                                  raw_output=raw_output, status=status,
                                                  latency_ms=latency_ms,
                                                  http_status=http_status),
                               replay_record=record))
        return i

    def final(self, summary: str = "return a response to the customer") -> int:
        i = self.next_index
        self.steps.append(Step(i, "final", summary))
        return i

    def distractors(self, n: int) -> list[int]:
        """Innocent, plausible-looking steps. Each survives inspection cleanly."""
        out: list[int] = []
        for _ in range(n):
            pick = self.rng.random()
            if pick < 0.4:
                out.append(self.retrieve(
                    "shipping timelines", ["SHIPPING SLA v2 (current): 5 business days"],
                    [0.71], "retrieve shipping information"))
            elif pick < 0.75:
                out.append(self.call("fetch_invoice", {"order_id": self.order_id},
                                     '{"invoice_id":"INV-88","total":45.0}'))
            else:
                out.append(self.reflect(
                    "the order details look consistent; check the remaining conditions",
                    "review gathered information"))
        return out

    def lookup(self, days: int = 18) -> int:
        return self.call("lookup_order", {"order_id": self.order_id},
                         '{"order_id":"%s","total":45.0,"days_since_purchase":%d}'
                         % (self.order_id, days))


# --------------------------------------------------------------------------- templates
# Each template mutates the builder and returns (root_cause_step, crash_step, distractors).
# Surface error and final result are drawn separately from the shared ambiguous pool.

def _refund_preamble(b: _Builder, plan_text: str = SOUND_PLAN,
                     policy: str = CURRENT_POLICY, days: int = 18):
    plan_i = b.plan(plan_text)
    ret_i = b.retrieve("refund policy", [policy], [0.88], "retrieve the refund policy")
    b.lookup(days)
    return plan_i, ret_i


# ------------------------------------------------------------------ H1 planning

def _t_wrong_tool_selected(b: _Builder, cfg: GeneratorConfig):
    """H1. The plan names check_eligibility; the run calls notify_customer instead.

    The tool that was called behaves perfectly -- clean schema, clean 200 response -- so
    every single-probe view of the failing step looks innocent. The fault is visible only
    by holding the plan text against the VISIBLE tool names.
    """
    _refund_preamble(b)
    root = b.call("notify_customer",
                  {"order_id": b.order_id, "message": "checking your refund eligibility"},
                  '{"delivered":true}')
    distractors = b.distractors(b.rng.randint(*cfg.distractor_range))
    crash = b.call("issue_refund", {"order_id": b.order_id, "amount": 45.0},
                   '{"error":"precondition_not_met","detail":"eligibility not verified"}',
                   status="error", http_status=409)
    b.final()
    return root, crash, distractors


def _t_wrong_reasoning_decision(b: _Builder, cfg: GeneratorConfig):
    """H1. The current policy is retrieved correctly and the wrong conclusion is drawn.

    Context probe alone says `context_clean`. Plan probe alone says `plan_sound`. Only the
    two together show a 95-day-old order being called eligible under a 30-day policy.
    """
    _refund_preamble(b, days=95)
    root = b.reflect("the order is 95 days old and the policy applies, so it is eligible; "
                     "verify nothing further", "assess eligibility")
    distractors = b.distractors(b.rng.randint(*cfg.distractor_range))
    b.call("check_eligibility", {"order_id": b.order_id, "days_since_purchase": 95},
           '{"eligible":false,"reason":"outside window"}')
    crash = b.call("issue_refund", {"order_id": b.order_id, "amount": 45.0},
                   '{"error":"policy_violation","detail":"outside 30 day window"}',
                   status="error", http_status=409)
    b.final()
    return root, crash, distractors


def _t_incorrect_routing(b: _Builder, cfg: GeneratorConfig):
    """H1. A shipping complaint is routed into the refund workflow.

    Every downstream step is executed competently; the workflow was simply the wrong one.
    Visible only by holding the plan text against the task.
    """
    root = b.plan("route to the refund workflow: retrieve the current policy, look up the "
                  "order with lookup_order, check eligibility with check_eligibility, "
                  "then issue_refund if it qualifies")
    b.retrieve("refund policy", [CURRENT_POLICY], [0.86], "retrieve the refund policy")
    b.lookup()
    distractors = b.distractors(b.rng.randint(*cfg.distractor_range))
    b.call("check_eligibility", {"order_id": b.order_id, "days_since_purchase": 18},
           '{"eligible":true}')
    crash = b.call("issue_refund", {"order_id": b.order_id, "amount": 45.0},
                   '{"error":"no_refund_requested","detail":"open case is a delivery delay"}',
                   status="error", http_status=409)
    b.final()
    return root, crash, distractors


# ------------------------------------------------------------------ H2 tool

def _t_malformed_arguments(b: _Builder, cfg: GeneratorConfig):
    """H2. A numeric field is passed as a string, violating the declared type."""
    _refund_preamble(b)
    b.call("check_eligibility", {"order_id": b.order_id, "days_since_purchase": 18},
           '{"eligible":true}')
    distractors = b.distractors(b.rng.randint(0, 1))
    crash = b.call("issue_refund", {"order_id": b.order_id, "amount": "45.00"},
                   '{"error":"validation_error","detail":"amount must be a number"}',
                   status="error", http_status=422)
    b.final()
    return crash, crash, distractors


def _t_schema_mismatch(b: _Builder, cfg: GeneratorConfig):
    """H2. Argument names do not match the contract: required field absent, extra supplied."""
    _refund_preamble(b)
    b.call("check_eligibility", {"order_id": b.order_id, "days_since_purchase": 18},
           '{"eligible":true}')
    distractors = b.distractors(b.rng.randint(0, 1))
    crash = b.call("issue_refund", {"order": b.order_id, "amount": 45.0},
                   '{"error":"unknown_field","detail":"order_id is required"}',
                   status="error", http_status=400)
    b.final()
    return crash, crash, distractors


def _t_misunderstood_output(b: _Builder, cfg: GeneratorConfig):
    """H2. A healthy 200 response says `eligible:false`; the agent reports the opposite.

    Schema probe: valid. Output probe: clean 200. Plan probe: sound-looking. The
    contradiction exists only across the output and the reflection that followed it.
    """
    _refund_preamble(b, days=95)
    b.call("check_eligibility", {"order_id": b.order_id, "days_since_purchase": 95},
           '{"eligible":false,"reason":"outside window"}')
    root = b.reflect("the eligibility service confirms the order qualifies; check nothing "
                     "further and proceed to the refund", "interpret the eligibility result")
    distractors = b.distractors(b.rng.randint(*cfg.distractor_range))
    crash = b.call("issue_refund", {"order_id": b.order_id, "amount": 45.0},
                   '{"error":"policy_violation","detail":"order is not eligible"}',
                   status="error", http_status=409)
    b.final()
    return root, crash, distractors


# ------------------------------------------------------------------ H3 context

def _t_missing_context(b: _Builder, cfg: GeneratorConfig):
    """H3. Retrieval returns nothing usable and the agent proceeds regardless."""
    b.plan(SOUND_PLAN)
    root = b.retrieve("refund policy", [], [], "retrieve the refund policy")
    b.lookup()
    distractors = b.distractors(b.rng.randint(*cfg.distractor_range))
    b.call("check_eligibility", {"order_id": b.order_id, "days_since_purchase": 18},
           '{"eligible":true}')
    crash = b.call("issue_refund", {"order_id": b.order_id, "amount": 45.0},
                   '{"error":"policy_unresolved","detail":"no policy in force was cited"}',
                   status="error", http_status=409)
    b.final()
    return root, crash, distractors


def _t_wrong_retrieved_information(b: _Builder, cfg: GeneratorConfig):
    """H3. A superseded policy is retrieved; the agent then reasons correctly over it.

    The stale retrieval sits early, and a later clean retrieval is often inserted as a
    distractor, so "probe the most recent retrieval" returns `context_clean` and misleads.
    """
    b.plan(SOUND_PLAN)
    root = b.retrieve("refund policy", [STALE_POLICY], [0.83], "retrieve the refund policy")
    b.lookup(days=95)
    b.reflect("the policy in hand allows 120 days and the order is 95 days old, so it is "
              "eligible; check the amount", "assess eligibility")
    distractors = b.distractors(b.rng.randint(*cfg.distractor_range))
    b.call("check_eligibility", {"order_id": b.order_id, "days_since_purchase": 95},
           '{"eligible":true}')
    crash = b.call("issue_refund", {"order_id": b.order_id, "amount": 45.0},
                   '{"error":"policy_violation","detail":"outside 30 day window"}',
                   status="error", http_status=409)
    b.final()
    return root, crash, distractors


# ------------------------------------------------------------------ H4 external

def _t_api_failure(b: _Builder, cfg: GeneratorConfig):
    """H4. The backing service returns a server error on entirely valid input."""
    _refund_preamble(b)
    b.call("check_eligibility", {"order_id": b.order_id, "days_since_purchase": 18},
           '{"eligible":true}')
    distractors = b.distractors(b.rng.randint(0, 2))
    nondeterministic = b.rng.random() < cfg.nondeterminism_rate
    crash = b.call("issue_refund", {"order_id": b.order_id, "amount": 45.0},
                   '{"error":"internal_error","request_id":"rq-3312"}',
                   status="error", http_status=503,
                   latency_ms=b.rng.randint(800, 2500),
                   replay_output=('{"receipt_id":"RC-77","refunded":45.0}'
                                  if nondeterministic else None),
                   force_replay=True)
    b.final()
    return crash, crash, distractors


def _t_service_unavailable(b: _Builder, cfg: GeneratorConfig):
    """H4. The service does not answer at all: timeout after elevated latency."""
    _refund_preamble(b)
    b.call("check_eligibility", {"order_id": b.order_id, "days_since_purchase": 18},
           '{"eligible":true}')
    distractors = b.distractors(b.rng.randint(0, 2))
    nondeterministic = b.rng.random() < cfg.nondeterminism_rate
    crash = b.call("issue_refund", {"order_id": b.order_id, "amount": 45.0}, "",
                   status="timeout", http_status=None,
                   latency_ms=b.rng.randint(9000, 30000),
                   replay_output=('{"receipt_id":"RC-79","refunded":45.0}'
                                  if nondeterministic else None),
                   force_replay=True)
    b.final()
    return crash, crash, distractors


# ------------------------------------------------------------------ H5 held out

def _t_silent_state_corruption(b: _Builder, cfg: GeneratorConfig):
    """HELD OUT. Every step is individually clean; the failure is in unlogged state.

    No probe in the contract can localize it and no mechanism in H1-H4 explains it, so
    escalation is the only correct action. Achieved structurally -- by making every
    observable clean -- not by any marker a policy could learn to spot.
    """
    _refund_preamble(b)
    b.call("check_eligibility", {"order_id": b.order_id, "days_since_purchase": 18},
           '{"eligible":true}')
    b.distractors(b.rng.randint(1, 2))
    b.call("issue_refund", {"order_id": b.order_id, "amount": 45.0},
           '{"receipt_id":"RC-91","refunded":45.0}')
    crash = b.final("return a response that contradicts the recorded refund")
    return crash, crash, []


TEMPLATES = {
    "wrong_tool_selected": _t_wrong_tool_selected,
    "wrong_reasoning_decision": _t_wrong_reasoning_decision,
    "incorrect_routing": _t_incorrect_routing,
    "malformed_arguments": _t_malformed_arguments,
    "schema_mismatch": _t_schema_mismatch,
    "misunderstood_output": _t_misunderstood_output,
    "missing_context": _t_missing_context,
    "wrong_retrieved_information": _t_wrong_retrieved_information,
    "api_failure": _t_api_failure,
    "service_unavailable": _t_service_unavailable,
    "silent_state_corruption": _t_silent_state_corruption,
}

#: incorrect_routing is the one family whose task is not a refund request -- the routing
#: error is only an error relative to what was actually asked.
TASK_FOR_FAMILY = {"incorrect_routing": SHIPPING_TASK}

HELD_OUT = "silent_state_corruption"


# --------------------------------------------------------------------------- reference

def known_good_trace(trace_id: str, order_id: str, task: str,
                     rng: random.Random) -> Trace:
    """A successful run of the same task, for compare_known_good."""
    b = _Builder(rng, order_id)
    _refund_preamble(b)
    b.call("check_eligibility", {"order_id": order_id, "days_since_purchase": 18},
           '{"eligible":true}')
    b.call("issue_refund", {"order_id": order_id, "amount": 45.0},
           '{"receipt_id":"RC-01","refunded":45.0}')
    b.call("notify_customer", {"order_id": order_id, "message": "your refund is on its way"},
           '{"delivered":true}')
    b.final()
    return Trace(trace_id=trace_id, task=task, steps=b.steps,
                 final_result="Your refund of 45.00 has been issued.",
                 final_error=None, ground_truth=None)


# --------------------------------------------------------------------------- generate

def generate_case(family_id: str, case_no: int, cfg: GeneratorConfig,
                  rng: random.Random) -> tuple[Trace, Trace]:
    family: Family = FAMILIES[family_id]
    order_id = f"A-{1000 + case_no}"
    task = TASK_FOR_FAMILY.get(family_id, REFUND_TASK).format(oid=order_id)

    b = _Builder(rng, order_id)
    root, crash, distractors = TEMPLATES[family_id](b, cfg)

    final_error = rng.choice(SURFACE_ERRORS[family_id])
    final_result = (rng.choice(SILENT_RESULTS) if final_error is None
                    else rng.choice(FAILED_RESULTS))

    ref_id = f"ref-{case_no:05d}"
    reference = known_good_trace(ref_id, order_id, task, random.Random(rng.random()))

    trace = Trace(
        trace_id=f"case-{case_no:05d}",
        task=task,
        steps=b.steps,
        final_result=final_result,
        final_error=final_error,
        reference_trace_id=ref_id,
        ground_truth=GroundTruth(
            mechanism=family.mechanism,
            family=family_id,
            root_cause_step=root,
            crash_step=crash,
            in_taxonomy=family.in_taxonomy,
            distractor_steps=tuple(distractors),
        ),
    )
    return trace, reference


def _allocate(cfg: GeneratorConfig, rng: random.Random) -> list[str]:
    """Decide which family each case belongs to.

    `by_mechanism` samples the mechanism uniformly then the family within it, keeping the
    attribution prior flat (requirement G2) at the cost of uneven family counts.
    `by_family` allocates round-robin so every family is guaranteed to appear -- necessary
    for small inspection corpora, where sampling would leave families empty.
    """
    if cfg.allocation == "by_family":
        n_held = round(cfg.n_cases * cfg.held_out_fraction) if cfg.include_held_out else 0
        plan = [HELD_OUT] * n_held
        fams = list(IN_TAXONOMY_FAMILIES)
        for i in range(cfg.n_cases - n_held):
            plan.append(fams[i % len(fams)])
        rng.shuffle(plan)
        return plan

    by_mechanism: dict[Mechanism, list[str]] = {m: [] for m in Mechanism.predictable()}
    for fid in IN_TAXONOMY_FAMILIES:
        by_mechanism[FAMILIES[fid].mechanism].append(fid)
    plan = []
    for _ in range(cfg.n_cases):
        if cfg.include_held_out and rng.random() < cfg.held_out_fraction:
            plan.append(HELD_OUT)
        else:
            plan.append(rng.choice(by_mechanism[rng.choice(list(by_mechanism))]))
    return plan


def generate(cfg: GeneratorConfig) -> tuple[list[Trace], dict[str, Trace]]:
    """Return (cases, reference_index)."""
    rng = random.Random(cfg.seed)
    cases: list[Trace] = []
    references: dict[str, Trace] = {}
    for n, family_id in enumerate(_allocate(cfg, rng)):
        case, reference = generate_case(family_id, n, cfg, rng)
        cases.append(case)
        references[reference.trace_id] = reference
    return cases, references
