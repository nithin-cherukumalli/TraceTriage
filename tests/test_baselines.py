"""Tests for Baseline 1.

Two jobs. First, the ordinary one: formatting, parsing, and the failure shapes real models
produce. Second, and more important, the standing guarantee that **B1 cannot cheat** — it
sees no ground truth, no probe output, and calls no probe. Those are asserted structurally
(import scanning, object-graph walking, output scanning) rather than promised in a comment,
because a refactor six sessions from now will not read the comment.
"""
from __future__ import annotations

import ast
import json
import random
from pathlib import Path

import pytest

from baselines.trace_formatter import (
    FORMAT_VERSION, TraceView, format_full_trace, format_observation, format_trace,
    visible_step_ids,
)
from baselines.whole_trace_llm import (
    PROMPT_VERSION, Diagnosis, WholeTraceLLMBaseline, parse_diagnosis,
)
from evaluation.llm_metrics import (
    audit_grounding, calibration, hidden_literals, to_episode,
)
from evaluation.metrics import score_episode
from llm.client import LLMResponse, MockClient, get_client
from trace.models import GroundTruth, Observation, Trace, make_observation
from trace.synthesize import GeneratorConfig, generate_case

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def api_failure_case():
    """H4 with a 503 and a raw output — gives the hidden-literal detector something real."""
    case, _ = generate_case("api_failure", 1, GeneratorConfig(), random.Random(4))
    return case


@pytest.fixture
def stale_case():
    case, _ = generate_case("wrong_retrieved_information", 2, GeneratorConfig(),
                            random.Random(11))
    return case


# =================================================================== leakage guarantees

def test_baselines_package_imports_nothing_from_probes():
    """'Must not use diagnostic probes' as a structural fact, not a promise."""
    offenders = []
    for path in (ROOT / "src" / "baselines").glob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            else:
                continue
            for name in names:
                if name.split(".")[0] == "probes":
                    offenders.append(f"{path.name}: {name}")
    assert not offenders, offenders


def test_visible_view_refuses_a_trace(stale_case):
    """Handing a Trace to the formatter is exactly how ground truth would leak."""
    with pytest.raises(TypeError, match="Observation"):
        format_trace(stale_case, TraceView.VISIBLE)


def test_visible_rendering_contains_no_probe_gated_content(api_failure_case, stale_case):
    for case in (api_failure_case, stale_case):
        rendered = format_observation(make_observation(case, budget=0))
        for step in case.steps:
            if step.plan_text:
                assert step.plan_text not in rendered
            if step.tool_call and step.tool_call.raw_output:
                assert step.tool_call.raw_output not in rendered
            if step.tool_call and step.tool_call.http_status:
                assert str(step.tool_call.http_status) not in rendered
            if step.retrieval:
                for doc in step.retrieval.documents:
                    assert doc not in rendered
            if step.replay_record:
                assert json.dumps(step.replay_record) not in rendered


def test_visible_rendering_contains_no_ground_truth(api_failure_case):
    gt = api_failure_case.ground_truth
    rendered = format_observation(make_observation(api_failure_case, budget=0))
    assert gt.mechanism.value not in rendered
    assert gt.family not in rendered
    assert "root_cause" not in rendered and "crash_step" not in rendered


def test_full_rendering_shows_probe_content_but_still_no_ground_truth(api_failure_case):
    rendered = format_full_trace(api_failure_case)
    crash = api_failure_case.step(api_failure_case.ground_truth.crash_step)
    assert crash.tool_call.raw_output in rendered          # FULL is meant to reveal this
    gt = api_failure_case.ground_truth
    assert gt.mechanism.value not in rendered
    assert gt.family not in rendered


def test_baseline_prompt_never_carries_ground_truth(stale_case, api_failure_case):
    """The user message must not name the truth; the system prompt must be case-invariant.

    The system prompt legitimately enumerates all five mechanisms — the model needs the
    label space. What it must not do is vary by case, since a per-case system prompt is
    where a leak would hide. So: check the user turn for the answer, and check the system
    turn is byte-identical across two cases with different mechanisms.
    """
    client = MockClient()
    baseline = WholeTraceLLMBaseline(client=client)
    baseline.diagnose(stale_case)
    system_a, user_a = client.calls[-1]
    baseline.diagnose(api_failure_case)
    system_b, _ = client.calls[-1]

    assert stale_case.ground_truth.mechanism is not api_failure_case.ground_truth.mechanism
    assert system_a == system_b, "the system prompt varies by case — that is where a leak hides"

    gt = stale_case.ground_truth
    for forbidden in (gt.mechanism.value, gt.family, "root_cause_step", "crash_step"):
        assert forbidden not in user_a


def test_baseline_result_reports_zero_probes(stale_case):
    ep = to_episode(WholeTraceLLMBaseline().diagnose(stale_case))
    assert ep.n_probes == 0 and ep.probe_cost == 0.0


def test_observation_handed_to_the_formatter_cannot_reach_ground_truth(stale_case):
    obs = make_observation(stale_case, budget=0)
    assert isinstance(obs, Observation)
    seen, stack = set(), [obs]
    while stack:
        node = stack.pop()
        if id(node) in seen:
            continue
        seen.add(id(node))
        assert not isinstance(node, GroundTruth)
        if hasattr(node, "__dataclass_fields__"):
            stack += [getattr(node, f) for f in node.__dataclass_fields__]
        elif isinstance(node, (list, tuple, set)):
            stack += list(node)
        elif isinstance(node, dict):
            stack += list(node.keys()) + list(node.values())


# =================================================================== formatting

def test_visible_rendering_lists_every_step_with_tools_and_arguments(stale_case):
    obs = make_observation(stale_case, budget=0)
    rendered = format_observation(obs)
    for header in obs.headers:
        assert f"| {header.index} |" in rendered
        assert header.summary in rendered
        if header.tool_name:
            assert header.tool_name in rendered
            assert json.dumps(header.tool_arguments, sort_keys=True) in rendered


def test_rendering_is_deterministic(stale_case):
    obs = make_observation(stale_case, budget=0)
    assert format_observation(obs) == format_observation(obs)


def test_rendering_declares_what_is_withheld(stale_case):
    """Concealing the redaction would push the model toward overconfidence, which would
    flatter our own hypothesis. Telling it is the conservative choice."""
    rendered = format_observation(make_observation(stale_case, budget=0))
    assert "What is NOT shown to you" in rendered
    for withheld in ("raw tool outputs", "retrieval queries", "replay record"):
        assert withheld in rendered


def test_silent_failure_is_rendered_as_such(stale_case):
    import dataclasses
    silent = dataclasses.replace(stale_case, final_error=None,
                                 final_result="Your refund has been processed.")
    rendered = format_observation(make_observation(silent, budget=0))
    assert "the run raised no error" in rendered
    assert "Your refund has been processed." in rendered


def test_visible_step_ids_match_the_trace(stale_case):
    obs = make_observation(stale_case, budget=0)
    assert visible_step_ids(obs) == {s.index for s in stale_case.steps}


# =================================================================== parsing

def test_parses_a_clean_object():
    d = parse_diagnosis(json.dumps({
        "predicted_mechanism": "H3_context", "predicted_failure_step": 1,
        "confidence": 0.8, "evidence_used": [{"step_id": "1", "observation": "retrieval"}],
        "alternative_explanations": ["H1_planning"], "uncertainty": "no document text"}))
    assert d.ok and d.predicted_mechanism.value == "H3_context"
    assert d.predicted_failure_step == 1 and d.confidence == 0.8
    assert d.evidence_used[0]["step_id"] == "1"


def test_parses_a_fenced_block_wrapped_in_prose():
    client = MockClient(mode="fenced")
    text = client.complete("s", "| 0 |\n| 1 |").text
    assert "```" in text
    assert parse_diagnosis(text).ok


def test_empty_response_is_a_parse_failure():
    d = parse_diagnosis("")
    assert not d.ok and "empty" in d.parse_error


def test_malformed_json_is_a_parse_failure_not_an_exception():
    d = parse_diagnosis('{"predicted_mechanism": "H2_tool", "confidence":')
    assert not d.ok and d.parse_error
    assert d.raw_text                     # kept for auditing


def test_prose_with_no_json_is_a_parse_failure():
    d = parse_diagnosis("The agent clearly failed because the tool broke.")
    assert not d.ok


def test_json_array_instead_of_object_is_rejected():
    assert not parse_diagnosis('[{"predicted_mechanism": "H2_tool"}]').ok


def test_missing_fields_are_reported_not_defaulted_silently():
    d = parse_diagnosis(json.dumps({"predicted_mechanism": "H2_tool"}))
    assert d.predicted_mechanism is not None
    assert not d.ok and "confidence missing" in d.parse_error


def test_unrecognised_mechanism_is_not_mapped_onto_a_class():
    """Guessing a class from free text would manufacture accuracy the model did not earn."""
    d = parse_diagnosis(json.dumps({
        "predicted_mechanism": "the tool was flaky", "confidence": 0.9}))
    assert d.predicted_mechanism is None and not d.ok


def test_bare_h_prefix_is_accepted():
    d = parse_diagnosis(json.dumps({"predicted_mechanism": "H4", "confidence": 0.5}))
    assert d.predicted_mechanism.value == "H4_external"


def test_wrong_types_are_coerced_or_flagged():
    d = parse_diagnosis(json.dumps({
        "predicted_mechanism": "H2_tool", "predicted_failure_step": "step 3",
        "confidence": "high", "evidence_used": {"step_id": "1", "observation": "x"},
        "alternative_explanations": "H1_planning", "uncertainty": None}))
    assert d.predicted_failure_step == 3           # "step 3" -> 3
    assert d.confidence == 0.8                     # verbal hedge mapped, and recorded
    assert len(d.evidence_used) == 1               # single dict accepted as one entry
    assert d.alternative_explanations == ("H1_planning",)
    assert d.uncertainty == ""


def test_unparsable_confidence_is_flagged():
    d = parse_diagnosis(json.dumps({"predicted_mechanism": "H2_tool",
                                    "confidence": "quite sure"}))
    assert not d.ok and "confidence" in d.parse_error


def test_confidence_is_clamped():
    d = parse_diagnosis(json.dumps({"predicted_mechanism": "H2_tool", "confidence": 4.2}))
    assert d.confidence == 1.0


def test_missing_evidence_is_handled_as_absence_not_error():
    d = parse_diagnosis(json.dumps({"predicted_mechanism": "H2_tool", "confidence": 0.5}))
    assert d.evidence_used == () and d.ok


# =================================================================== no repair, no tuning

def test_no_repair_attempt_by_default(stale_case):
    client = MockClient(mode="malformed")
    result = WholeTraceLLMBaseline(client=client).diagnose(stale_case)
    assert len(client.calls) == 1, "retrying until it parses would flatter the baseline"
    assert not result.diagnosis.ok


def test_repair_is_available_but_opt_in(stale_case):
    client = MockClient(mode="malformed")
    WholeTraceLLMBaseline(client=client, max_repair_attempts=2).diagnose(stale_case)
    assert len(client.calls) == 3


def test_provider_error_is_recorded_not_raised(stale_case):
    result = WholeTraceLLMBaseline(client=MockClient(mode="provider_error")).diagnose(stale_case)
    assert result.provider_error and not result.diagnosis.ok


def test_prompt_and_format_versions_are_recorded(stale_case):
    r = WholeTraceLLMBaseline().diagnose(stale_case)
    assert r.prompt_version == PROMPT_VERSION and r.format_version == FORMAT_VERSION


def test_system_prompt_forbids_suggesting_fixes():
    from baselines.whole_trace_llm import SYSTEM_PROMPT
    assert "Do not propose fixes" in SYSTEM_PROMPT
    assert "predicted_mechanism" in SYSTEM_PROMPT


# =================================================================== grounding metrics

def test_hidden_literals_include_probe_gated_values(api_failure_case):
    literals = hidden_literals(api_failure_case)
    crash = api_failure_case.step(api_failure_case.ground_truth.crash_step)
    assert crash.tool_call.raw_output in literals
    assert str(crash.tool_call.http_status) in literals


def test_hallucinated_step_ids_are_caught(api_failure_case):
    result = WholeTraceLLMBaseline(client=MockClient(mode="hallucinating")).diagnose(
        api_failure_case)
    audit = audit_grounding(result, api_failure_case)
    assert audit.invalid_step_ids, "steps 99 and -1 do not exist in the trace"
    assert audit.valid_citations == 0


def test_asserting_an_unseen_http_status_is_flagged_by_value(api_failure_case):
    """Airtight: under VISIBLE the model never saw 503, so citing it is invention."""
    result = WholeTraceLLMBaseline(client=MockClient(mode="hallucinating")).diagnose(
        api_failure_case)
    audit = audit_grounding(result, api_failure_case)
    assert "503" in audit.unsupported_by_value
    assert audit.any_unsupported


def test_hedged_language_is_not_counted_as_an_unsupported_claim(stale_case):
    result = WholeTraceLLMBaseline().diagnose(stale_case)
    hedged = Diagnosis(
        predicted_mechanism=result.diagnosis.predicted_mechanism,
        predicted_failure_step=0, confidence=0.4,
        evidence_used=({"step_id": "0", "observation":
                        "the tool may have returned an error, though I cannot see it"},),
        uncertainty="no outputs are visible")
    import dataclasses
    audit = audit_grounding(dataclasses.replace(result, diagnosis=hedged), stale_case)
    assert not audit.unsupported_by_category, "a hypothesis is not a fabricated claim"


def test_full_view_has_no_unsupported_claims_by_construction(api_failure_case):
    result = WholeTraceLLMBaseline(client=MockClient(mode="hallucinating"),
                                   view=TraceView.FULL).diagnose(api_failure_case)
    audit = audit_grounding(result, api_failure_case)
    assert audit.unsupported_by_value == () and audit.unsupported_by_category == ()


def test_remediation_language_is_detected(stale_case):
    import dataclasses
    result = WholeTraceLLMBaseline().diagnose(stale_case)
    fixy = Diagnosis(predicted_mechanism=result.diagnosis.predicted_mechanism,
                     confidence=0.5,
                     evidence_used=({"step_id": "0",
                                     "observation": "the fix is to refresh the cache"},))
    audit = audit_grounding(dataclasses.replace(result, diagnosis=fixy), stale_case)
    assert audit.suggested_a_fix


# =================================================================== calibration

def test_perfect_calibration_scores_zero_ece():
    conf = [0.05, 0.95, 0.05, 0.95]
    correct = [False, True, False, True]
    assert calibration(conf, correct).ece < 0.06


def test_confidently_wrong_is_maximally_miscalibrated():
    report = calibration([0.95] * 10, [False] * 10)
    assert report.ece > 0.9
    assert report.high_confidence_error_rate == 1.0
    assert report.overconfidence > 0.9


def test_calibration_handles_an_empty_run():
    assert calibration([], []).n == 0


def test_brier_matches_the_definition():
    assert calibration([1.0, 0.0], [True, False]).brier == 0.0
    assert calibration([1.0, 0.0], [False, True]).brier == 1.0


# =================================================================== bridging

def test_predicting_h5_is_treated_as_an_escalation(stale_case):
    import dataclasses
    result = WholeTraceLLMBaseline().diagnose(stale_case)
    from trace.models import Mechanism
    unknown = dataclasses.replace(result.diagnosis, predicted_mechanism=Mechanism.H5_UNKNOWN)
    ep = to_episode(dataclasses.replace(result, diagnosis=unknown))
    assert ep.terminal == "escalate" and ep.mechanism is None


def test_a_parse_failure_scores_as_a_wrong_answer_not_an_escalation(stale_case):
    result = WholeTraceLLMBaseline(client=MockClient(mode="malformed")).diagnose(stale_case)
    ep = to_episode(result)
    assert ep.terminal == "diagnose" and ep.mechanism is None
    score = score_episode(ep, stale_case.ground_truth)
    assert score.attribution_correct is False and score.escalated is False


def test_b1_scores_through_the_same_metrics_path_as_every_policy(stale_case):
    score = score_episode(to_episode(WholeTraceLLMBaseline().diagnose(stale_case)),
                          stale_case.ground_truth)
    assert score.policy == "b1_whole_trace"
    assert hasattr(score, "attribution_correct") and hasattr(score, "localization_exact")


# =================================================================== client abstraction

def test_registry_defaults_to_mock_and_needs_no_key():
    client = get_client()
    assert client.name == "mock"
    assert client.complete("s", "u").text


def test_unknown_client_is_rejected():
    with pytest.raises(ValueError, match="unknown client"):
        get_client("gemini")


def test_provider_clients_are_registered_without_being_imported():
    from llm.client import _REGISTRY
    assert set(_REGISTRY) == {"mock", "anthropic", "openai"}


def test_mock_is_deterministic(stale_case):
    obs = make_observation(stale_case, budget=0)
    rendered = format_observation(obs)
    a = MockClient().complete("s", rendered).text
    b = MockClient().complete("s", rendered).text
    assert a == b


def test_llm_response_reports_token_totals():
    r = LLMResponse("x", 10, 5)
    assert r.total_tokens == 15
