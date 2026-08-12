"""Baseline 1 — whole-trace LLM diagnosis.

The approach criticised in practitioner discussions: hand the failed trace to an LLM and
ask what went wrong. **This is not the proposed method.** It is the comparison point, and it
is deliberately not optimised.

What that means concretely, and why each choice cuts against flattering the baseline:

* **One call, no probes.** This module imports nothing from `src/probes/`; a test enforces
  it. There is no `get_step()`, no replay, no state diff, no second look.
* **No retry on malformed output.** Retrying until the JSON parses would quietly convert a
  failure mode into a success. Parse failures are counted and scored as incorrect
  attribution. `max_repair_attempts` exists and defaults to 0.
* **One prompt version, temperature 0, no dev-set iteration.** If the prompt changes it
  gets a new version id and both are reported.
* **Diagnosis only.** The output schema has no remediation field and the system prompt
  forbids suggesting fixes.

The interesting output is not accuracy. It is `unsupported_explanation_rate`: under the
VISIBLE view the model provably never saw raw outputs, HTTP codes, retrieved documents,
plan text or replay records, so any explanation asserting one of those values is invented
by construction — no judgement call required.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from llm.client import LLMClient, LLMResponse, MockClient
from trace.models import Mechanism, Observation, Trace, make_observation

from .trace_formatter import FORMAT_VERSION, TraceView, format_trace, visible_step_ids

PROMPT_VERSION = "v1"

MECHANISMS = [m.value for m in Mechanism]

SYSTEM_PROMPT = """You are an experienced engineer diagnosing a failed AI-agent run.

You will be shown a record of the run. Identify the single mechanism that caused the \
failure and the step at which the failure was FIRST CAUSED — which is often earlier than \
the step where it became visible.

Failure mechanisms:
- H1_planning: the agent's plan or decision was wrong, given correct inputs. Includes \
selecting a tool that cannot serve the subgoal, drawing a wrong conclusion from correct \
evidence, and routing the request into the wrong workflow.
- H2_tool: the agent misused a tool that was working correctly. Includes malformed \
arguments, argument names that do not match the tool contract, and misreading a correct \
tool response.
- H3_context: the evidence supplied to the agent was wrong, missing or stale.
- H4_external: the tool or environment itself failed — server error, timeout, \
unavailability — on valid input.
- H5_unknown: none of the above explains it.

Rules:
- Diagnose only. Do not propose fixes, remediation, or code changes.
- Cite only what you were actually shown. If you did not see a tool's output, do not \
assert what it returned.
- Report calibrated confidence. Low confidence on thin evidence is correct behaviour, \
not a failure.

Respond with a single JSON object and nothing else:

{
  "predicted_mechanism": "one of H1_planning, H2_tool, H3_context, H4_external, H5_unknown",
  "predicted_failure_step": <integer step number, or null>,
  "confidence": <number between 0.0 and 1.0>,
  "evidence_used": [{"step_id": "<step number>", "observation": "<what you saw there>"}],
  "alternative_explanations": ["<other mechanisms you considered>"],
  "uncertainty": "<what you could not determine and why>"
}"""

USER_PREFIX = "Diagnose this failed run.\n\n"


# --------------------------------------------------------------------------- output

@dataclass(frozen=True)
class Diagnosis:
    """Parsed model output. `parse_error` set means the model failed to answer usably."""
    predicted_mechanism: Mechanism | None = None
    predicted_failure_step: int | None = None
    confidence: float = 0.0
    evidence_used: tuple[dict[str, str], ...] = ()
    alternative_explanations: tuple[str, ...] = ()
    uncertainty: str = ""
    parse_error: str | None = None
    raw_text: str = ""

    @property
    def ok(self) -> bool:
        return self.parse_error is None and self.predicted_mechanism is not None


_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.S)


def _extract_json(text: str) -> tuple[dict | None, str | None]:
    """Pull a JSON object out of model text.

    Tolerant of the two things every model does — fencing the block and wrapping it in
    prose — and intolerant of everything else. This is extraction, not repair: we do not
    patch trailing commas or invent missing braces, because a model that cannot emit its
    own declared output format is telling us something worth measuring.
    """
    if not text or not text.strip():
        return None, "empty response"
    candidates: list[str] = []
    fenced = _FENCE.search(text)
    if fenced:
        candidates.append(fenced.group(1))
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        candidates.append(text[start:end + 1])
    candidates.append(text)

    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(parsed, dict):
            return parsed, None
        return None, f"expected a JSON object, got {type(parsed).__name__}"
    return None, "no parsable JSON object in response"


def _coerce_step(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str):
        m = re.search(r"-?\d+", value)
        if m:
            return int(m.group())
    return None


def _coerce_confidence(value: Any) -> tuple[float, str | None]:
    """A non-numeric confidence is a schema violation, not something to guess at.

    Verbal hedges ("high") are mapped, because refusing them would inflate the parse-failure
    rate on a technicality rather than on a real inability to answer; the mapping is
    recorded so it can be audited.
    """
    if isinstance(value, bool):
        return 0.0, "confidence was a boolean"
    if isinstance(value, (int, float)):
        return max(0.0, min(1.0, float(value))), None
    if isinstance(value, str):
        verbal = {"very high": 0.95, "high": 0.8, "medium": 0.5, "moderate": 0.5,
                  "low": 0.25, "very low": 0.1}
        key = value.strip().lower()
        if key in verbal:
            return verbal[key], None
        try:
            return max(0.0, min(1.0, float(key.rstrip("%")) / (100 if "%" in key else 1))), None
        except ValueError:
            return 0.0, f"unparsable confidence {value!r}"
    return 0.0, f"confidence had type {type(value).__name__}"


def _coerce_evidence(value: Any) -> tuple[tuple[dict[str, str], ...], str | None]:
    if value is None:
        return (), None
    if isinstance(value, dict):          # a single entry, not a list
        value = [value]
    if not isinstance(value, list):
        return (), f"evidence_used had type {type(value).__name__}"
    out = []
    for item in value:
        if isinstance(item, dict):
            out.append({"step_id": str(item.get("step_id", "")),
                        "observation": str(item.get("observation", ""))})
        elif isinstance(item, str):
            out.append({"step_id": "", "observation": item})
    return tuple(out), None


def parse_diagnosis(text: str) -> Diagnosis:
    """Parse model output. Never raises — a bad response is data, not an exception."""
    payload, err = _extract_json(text)
    if payload is None:
        return Diagnosis(parse_error=err, raw_text=text)

    problems: list[str] = []

    raw_mech = payload.get("predicted_mechanism")
    mechanism: Mechanism | None = None
    if raw_mech is None:
        problems.append("predicted_mechanism missing")
    else:
        key = str(raw_mech).strip()
        for m in Mechanism:
            if key == m.value or key.lower() == m.value.lower() or key.upper() == m.name:
                mechanism = m
                break
        else:
            # Accept a bare "H2" but nothing looser: silently mapping free text onto a
            # class would manufacture accuracy the model did not earn.
            bare = re.fullmatch(r"[Hh]([1-5])", key)
            if bare:
                mechanism = list(Mechanism)[int(bare.group(1)) - 1]
            else:
                problems.append(f"unrecognised mechanism {raw_mech!r}")

    if "confidence" not in payload:
        problems.append("confidence missing")
        confidence = 0.0
    else:
        confidence, cerr = _coerce_confidence(payload["confidence"])
        if cerr:
            problems.append(cerr)

    evidence, everr = _coerce_evidence(payload.get("evidence_used"))
    if everr:
        problems.append(everr)

    alternatives = payload.get("alternative_explanations")
    if isinstance(alternatives, str):
        alternatives = [alternatives]
    elif not isinstance(alternatives, list):
        alternatives = []

    uncertainty = payload.get("uncertainty")
    uncertainty = "" if uncertainty is None else str(uncertainty)

    return Diagnosis(
        predicted_mechanism=mechanism,
        predicted_failure_step=_coerce_step(payload.get("predicted_failure_step")),
        confidence=confidence,
        evidence_used=evidence,
        alternative_explanations=tuple(str(a) for a in alternatives),
        uncertainty=uncertainty,
        parse_error="; ".join(problems) if problems else None,
        raw_text=text,
    )


# --------------------------------------------------------------------------- baseline

@dataclass
class B1Result:
    trace_id: str
    diagnosis: Diagnosis
    view: str
    prompt_version: str
    format_version: str
    model: str
    input_tokens: int
    output_tokens: int
    provider_error: str | None
    #: Step ids the model could legitimately have cited. Carried so grounding can be scored
    #: later without re-deriving the observation.
    visible_steps: tuple[int, ...]


class WholeTraceLLMBaseline:
    """B1. One call, no probes, no repair, no tuning."""

    name = "b1_whole_trace"

    def __init__(self, client: LLMClient | None = None,
                 view: TraceView = TraceView.VISIBLE,
                 max_repair_attempts: int = 0,
                 temperature: float = 0.0):
        self.client = client or MockClient()
        self.view = view
        # Kept configurable so the effect of repair can be *measured* if anyone wants it,
        # but 0 is the honest default: repairing output flatters the baseline.
        self.max_repair_attempts = max_repair_attempts
        self.temperature = temperature

    def diagnose(self, trace: Trace) -> B1Result:
        obs = make_observation(trace, budget=0)
        source = obs if self.view is TraceView.VISIBLE else trace
        rendered = format_trace(source, self.view)

        response: LLMResponse = self.client.complete(
            SYSTEM_PROMPT, USER_PREFIX + rendered, temperature=self.temperature)

        diagnosis = parse_diagnosis(response.text)
        attempts = 0
        while (not diagnosis.ok) and attempts < self.max_repair_attempts:
            attempts += 1
            retry = self.client.complete(
                SYSTEM_PROMPT,
                USER_PREFIX + rendered +
                f"\n\nYour previous reply could not be parsed ({diagnosis.parse_error}). "
                "Reply with the JSON object only.",
                temperature=self.temperature)
            diagnosis = parse_diagnosis(retry.text)
            response = LLMResponse(retry.text,
                                   response.input_tokens + retry.input_tokens,
                                   response.output_tokens + retry.output_tokens,
                                   response.model, retry.error)

        return B1Result(
            trace_id=trace.trace_id, diagnosis=diagnosis, view=self.view.value,
            prompt_version=PROMPT_VERSION, format_version=FORMAT_VERSION,
            model=getattr(self.client, "model", "?"),
            input_tokens=response.input_tokens, output_tokens=response.output_tokens,
            provider_error=response.error,
            visible_steps=tuple(sorted(visible_step_ids(obs))),
        )

    def run(self, traces: list[Trace]) -> list[B1Result]:
        return [self.diagnose(t) for t in traces]
