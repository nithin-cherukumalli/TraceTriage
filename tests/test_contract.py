"""Enforces research/probe-contract.md. These are the tests that keep results meaningful.

Three failure modes they exist to catch:
  - a policy reaching hidden ground truth (the experiment becomes vacuous)
  - a mechanism label leaking into a visible or probe-revealed field (ditto)
  - the visibility tiers drifting away from schemas/trace_schema.json
"""
import dataclasses
import json
import re
from pathlib import Path

import pytest

from diagnosis.decision import run_episode
from diagnosis.policy import AdaptivePolicy, ChecklistPolicy, VisibleOnlyPolicy
from probes.base import PROBE_COST, all_probes, get_probe
from trace.models import GroundTruth, Observation, make_observation

SCHEMA = json.loads((Path(__file__).resolve().parents[1]
                     / "schemas" / "trace_schema.json").read_text())

# A mechanism label or a family id appearing anywhere a policy can see it.
# Every mechanism id and every family id. Built from the taxonomy so a new family cannot
# be added without the leakage check covering it.
from diagnosis.hypothesis import FAMILIES as _FAMILIES  # noqa: E402

LABEL_PAT = re.compile(
    r"\bH[1-5]_|\bH[1-5]\b|" + "|".join(re.escape(f) for f in _FAMILIES), re.I)


def walk(obj, seen=None):
    seen = seen if seen is not None else set()
    if id(obj) in seen:
        return
    seen.add(id(obj))
    yield obj
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        for f in dataclasses.fields(obj):
            yield from walk(getattr(obj, f.name), seen)
    elif isinstance(obj, dict):
        for k, v in obj.items():
            yield from walk(k, seen)
            yield from walk(v, seen)
    elif isinstance(obj, (list, tuple, set)):
        for v in obj:
            yield from walk(v, seen)


# ---------------------------------------------------------------- L3: ground-truth isolation
def test_l3_observation_cannot_reach_ground_truth(dev_corpus):
    for case in dev_corpus.cases[:20]:
        obs = make_observation(case, 6)
        for pid in all_probes():
            for i in range(len(case.steps)):
                obs.evidence.append(get_probe(pid).execute(case, i))
        assert not any(isinstance(o, GroundTruth) for o in walk(obs)), case.trace_id


def test_l3_policies_never_see_a_trace_or_ground_truth(dev_corpus):
    captured = []

    class Spy(AdaptivePolicy):
        name = "spy"

        def act(self, obs):
            captured.append(obs)
            return super().act(obs)

    for case in dev_corpus.cases[:15]:
        run_episode(case, Spy(), budget=6, reference_lookup=dev_corpus.lookup)
    assert captured
    for obs in captured:
        assert isinstance(obs, Observation)
        assert not any(isinstance(o, GroundTruth) for o in walk(obs))


# ---------------------------------------------------------------- L1 / L2: label leakage
def test_l2_visible_tier_contains_no_label(dev_corpus, test_corpus):
    for corpus in (dev_corpus, test_corpus):
        for case in corpus.cases:
            visible = json.dumps([dataclasses.asdict(h) for h in case.headers()])
            visible += case.task + (case.final_error or "") + case.final_result
            assert not LABEL_PAT.search(visible), f"{case.trace_id}: {visible[:200]}"


def test_l1_evidence_payloads_contain_no_label(dev_corpus):
    for case in dev_corpus.cases[:30]:
        for pid in all_probes():
            for i in range(len(case.steps)):
                ev = get_probe(pid).execute(case, i)
                assert not LABEL_PAT.search(json.dumps(ev.payload, default=str)), pid


# ---------------------------------------------------------------- visibility tiers
def test_visible_tier_matches_schema():
    """StepHeader must expose exactly the step fields marked VISIBLE in the schema."""
    step_props = SCHEMA["$defs"]["step"]["properties"]
    visible = {k for k, v in step_props.items() if v.get("x-visibility") == "VISIBLE"}
    assert visible == {"index", "kind", "summary"}

    tool_props = SCHEMA["$defs"]["tool_call"]["properties"]
    visible_tool = {k for k, v in tool_props.items() if v.get("x-visibility") == "VISIBLE"}
    assert visible_tool == {"name", "arguments"}, "amendment A1"


def test_probe_gated_fields_are_absent_from_headers(dev_corpus):
    header_fields = {f.name for f in dataclasses.fields(dev_corpus.cases[0].headers()[0])}
    forbidden = {"plan_text", "replay_record", "schema", "raw_output", "status",
                 "http_status", "latency_ms", "query", "documents", "scores"}
    assert not (header_fields & forbidden)


def test_headers_copy_arguments_so_a_policy_cannot_mutate_the_corpus(dev_corpus):
    case = next(c for c in dev_corpus.cases if any(s.tool_call for s in c.steps))
    header = next(h for h in case.headers() if h.tool_arguments is not None)
    header.tool_arguments["injected"] = True
    step = next(s for s in case.steps if s.index == header.index)
    assert "injected" not in step.tool_call.arguments


# ---------------------------------------------------------------- probe semantics
def test_probe_set_is_closed_and_priced():
    assert set(all_probes()) == set(PROBE_COST) == {
        "inspect_plan", "validate_tool_args", "inspect_tool_output",
        "inspect_context", "compare_known_good", "replay_tool_call"}


def test_probes_never_mutate_the_trace(dev_corpus):
    case = dev_corpus.cases[0]
    before = json.dumps(dataclasses.asdict(case), default=str)
    for pid in all_probes():
        for i in range(len(case.steps)):
            get_probe(pid).execute(case, i)
    assert json.dumps(dataclasses.asdict(case), default=str) == before


def test_inapplicable_probe_reports_not_ok(stale_case):
    tool_step = next(s.index for s in stale_case.steps if s.kind == "tool_call")
    assert get_probe("inspect_context").execute(stale_case, tool_step).ok is False


def test_replay_is_not_rerun_and_can_say_unavailable(dev_corpus):
    seen = set()
    for case in dev_corpus.cases:
        for s in case.steps:
            if s.kind != "tool_call":
                continue
            ev = get_probe("replay_tool_call").execute(case, s.index)
            seen.add(ev.payload["divergence"])
    assert "unavailable" in seen, "replay must be able to report that it is impossible"
    assert "none" in seen


def test_schema_probe_no_longer_reveals_arguments(stale_case):
    """Amendment A1: arguments are visible, so paying for them twice would be a bug."""
    step = next(s.index for s in stale_case.steps if s.kind == "tool_call")
    ev = get_probe("validate_tool_args").execute(stale_case, step)
    assert set(ev.payload) == {"schema", "schema_valid", "violations"}


# ---------------------------------------------------------------- budget accounting
def test_inapplicable_probes_are_still_charged(dev_corpus):
    class AlwaysWrongProbe:
        name = "wrong"

        def reset(self, obs):
            pass

        def act(self, obs):
            from diagnosis.decision import Action
            return Action.probe("inspect_context", obs.steps_of_kind("tool_call")[-1])

    ep = run_episode(dev_corpus.cases[0], AlwaysWrongProbe(), budget=3,
                     reference_lookup=dev_corpus.lookup)
    assert ep.n_probes == 3
    assert ep.probe_cost == pytest.approx(3 * PROBE_COST["inspect_context"])
    assert ep.terminal == "budget_exhausted"


def test_budget_exhaustion_is_escalation_not_a_free_guess(dev_corpus):
    from diagnosis.decision import Action

    class Greedy:
        name = "greedy"

        def reset(self, obs):
            pass

        def act(self, obs):
            return Action.probe("inspect_plan", 0)

    ep = run_episode(dev_corpus.cases[0], Greedy(), budget=2)
    assert ep.terminal == "budget_exhausted" and ep.mechanism is None


def test_policies_respect_the_budget(dev_corpus):
    for policy in (AdaptivePolicy(), ChecklistPolicy(), VisibleOnlyPolicy()):
        for case in dev_corpus.cases[:20]:
            ep = run_episode(case, policy, budget=6, reference_lookup=dev_corpus.lookup)
            assert ep.n_probes <= 6


# ---------------------------------------------------------------- corpus invariants
def test_corpus_meets_g1_displacement(dev_corpus):
    gts = [c.ground_truth for c in dev_corpus.cases]
    displaced = sum(g.root_cause_step != g.crash_step for g in gts)
    assert displaced / len(gts) >= 0.40


def test_held_out_family_is_absent_from_dev_and_present_in_test(dev_corpus, test_corpus):
    assert all(c.ground_truth.family != "silent_state_corruption" for c in dev_corpus.cases)
    assert any(c.ground_truth.family == "silent_state_corruption" for c in test_corpus.cases)
    for c in test_corpus.cases:
        if c.ground_truth.family == "silent_state_corruption":
            assert c.ground_truth.in_taxonomy is False


def test_silent_failures_exist(test_corpus):
    """Some failures raise nothing. 'Read the error' must not be a complete strategy."""
    assert any(c.final_error is None for c in test_corpus.cases)


# ---------------------------------------------------------------- probe sufficiency (G6)
def test_g6_every_case_is_probe_sufficient(inspection_corpus):
    """The requirement 'every case contains evidence reachable through probes', enforced.

    Checked by subset existence, not by running the policy's belief model over everything:
    sufficiency is a property of the evidence, and conflating it with the reasoner would
    let a known belief-model defect condemn perfectly good cases.
    """
    from trace.verify import audit_corpus
    audits, summary = audit_corpus(inspection_corpus.cases, inspection_corpus.lookup)
    failures = [(a.trace_id, a.family, a.reason) for a in audits if not a.probe_sufficient]
    assert not failures, failures


def test_cross_evidence_families_need_two_probes(inspection_corpus):
    """misunderstood_output and wrong_reasoning_decision must be invisible to one probe.

    If either becomes single-probe solvable the corpus has lost the cases that justify
    sequential evidence gathering at all.
    """
    from trace.verify import audit_case
    from diagnosis.hypothesis import CROSS_EVIDENCE_FAMILIES
    checked = set()
    for case in inspection_corpus.cases:
        fam = case.ground_truth.family
        if fam not in CROSS_EVIDENCE_FAMILIES:
            continue
        audit = audit_case(case, inspection_corpus.lookup)
        assert audit.oracle_probes is not None and audit.oracle_probes >= 2, \
            f"{fam} became single-probe solvable"
        checked.add(fam)
    assert checked == set(CROSS_EVIDENCE_FAMILIES)


def test_held_out_family_yields_no_anomalous_evidence(inspection_corpus):
    """H5 must be unreachable by detection, only by exclusion."""
    from trace.verify import audit_case
    seen = 0
    for case in inspection_corpus.cases:
        if case.ground_truth.in_taxonomy:
            continue
        seen += 1
        assert audit_case(case, inspection_corpus.lookup).probe_sufficient
    assert seen > 0


def test_every_family_appears_in_the_stratified_corpus(inspection_corpus):
    from diagnosis.hypothesis import FAMILIES
    present = {c.ground_truth.family for c in inspection_corpus.cases}
    assert present == set(FAMILIES)


def test_agent_view_export_contains_no_hidden_field():
    """The published agent_view JSON must not carry ground truth or probe-gated data."""
    import json as _json
    import subprocess
    import sys as _sys
    from pathlib import Path as _Path
    root = _Path(__file__).resolve().parents[1]
    path = root / "data" / "synthetic_cases" / "inspection_40.agent_view.json"
    if not path.exists():
        subprocess.run([_sys.executable, str(root / "experiments" / "build_cases.py")],
                       cwd=root, check=True, capture_output=True)
    blob = _json.loads(path.read_text())
    text = _json.dumps(blob["cases"])   # scope to payload; the file's own note is prose
    for forbidden in ("ground_truth", "root_cause_step", "crash_step", "mechanism",
                      "family", "plan_text", "raw_output", "documents", "replay_record",
                      "http_status", "schema"):
        assert forbidden not in text, f"agent view leaks {forbidden}"
