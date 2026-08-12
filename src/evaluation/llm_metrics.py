"""Metrics specific to unconstrained LLM diagnosis.

Attribution and localization are scored by `evaluation.metrics`, unchanged, so B1 sits on
the same axes as every probing policy. This module adds the three things that only matter
for a baseline whose failure mode is *plausibility*:

**Evidence grounding.** Did the explanation cite steps that exist?

**Unsupported explanation rate.** Did it assert things it could not have seen? Under the
VISIBLE view this has an exact answer for once: the model was never shown raw outputs, HTTP
codes, retrieved documents, plan text or replay records, so an explanation containing one of
those literal values is invented by construction. Reported in two parts, because they have
very different evidential weight:

  * `unsupported_by_value` — a hidden literal appears verbatim in the explanation. Airtight.
    Either fabrication that happened to land, or a lucky guess; unsupported *given the
    input* either way.
  * `unsupported_by_category` — the explanation asserts something about an unseen field
    ("the tool returned a 503"). A heuristic, hedged phrasing excluded. Labelled as such
    everywhere it is reported, and never merged into the airtight number without saying so.

**Calibration.** ECE and Brier over the confidence the model reported. The headline number
is `high_confidence_error_rate`: confident and wrong is precisely the practitioner
complaint.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from statistics import mean

from baselines.whole_trace_llm import B1Result
from diagnosis.decision import Episode
from trace.models import GroundTruth, Mechanism, Trace

# Assertive phrasing about a probe-gated field. Hedges are excluded on purpose: "the tool
# probably failed" is a hypothesis, which is what the model is supposed to be producing.
_HEDGES = re.compile(r"\b(may|might|could|possibly|perhaps|likely|probably|appears|seems|"
                     r"suggests|presumably|if |unclear|cannot tell|unknown|not shown|"
                     r"no visibility|without)\b", re.I)

_CATEGORY_CLAIMS = (
    (re.compile(r"\b(returned|responded with|response was|output was|replied with)\b", re.I),
     "asserts a tool output"),
    (re.compile(r"\b(http|status code|[45]\d\d\b|timed out|timeout)\b", re.I),
     "asserts transport status"),
    (re.compile(r"\b(the document|retrieved document|the retrieved|search results?|"
                r"relevance score)\b", re.I),
     "asserts retrieved context"),
    (re.compile(r"\b(the plan (said|stated|specified)|its reasoning|the agent reasoned|"
                r"reflection (said|stated))\b", re.I),
     "asserts plan or reflection text"),
    (re.compile(r"\b(replay|re-?ran|rerun)\b", re.I),
     "asserts a replay result"),
    (re.compile(r"\b(schema (requires|declares|specifies)|declared schema)\b", re.I),
     "asserts a declared schema"),
)

_REMEDIATION = re.compile(r"\b(should (be )?(fix|change|add|use|retry)|recommend|"
                          r"the fix is|to resolve this|suggest (adding|changing|using))\b",
                          re.I)


# --------------------------------------------------------------------------- bridging

def to_episode(result: B1Result) -> Episode:
    """Express a B1 run as an Episode so `evaluation.metrics` scores it unchanged.

    Predicting `H5_unknown` is an escalation — the model declined to place the failure in
    the taxonomy, which is the same act a probing policy performs when it escalates. A parse
    failure is *not* an escalation: it is a wrong answer, and is scored as one.
    """
    d = result.diagnosis
    if d.ok and d.predicted_mechanism is Mechanism.H5_UNKNOWN:
        terminal, mechanism, step = "escalate", None, None
    else:
        terminal = "diagnose"
        mechanism = d.predicted_mechanism if d.ok else None
        step = d.predicted_failure_step if d.ok else None

    return Episode(
        trace_id=result.trace_id, policy="b1_whole_trace", terminal=terminal,
        mechanism=mechanism, localized_step=step,
        reason=d.parse_error or d.uncertainty, n_probes=0, probe_cost=0.0,
        transcript=[{"action": "llm_call", "view": result.view,
                     "prompt_version": result.prompt_version,
                     "tokens": result.input_tokens + result.output_tokens,
                     "parse_error": d.parse_error,
                     "provider_error": result.provider_error}],
    )


# --------------------------------------------------------------------------- grounding

@dataclass(frozen=True)
class GroundingAudit:
    trace_id: str
    n_citations: int
    valid_citations: int
    invalid_step_ids: tuple[str, ...]
    unsupported_by_value: tuple[str, ...]
    unsupported_by_category: tuple[str, ...]
    suggested_a_fix: bool

    @property
    def cited_anything(self) -> bool:
        return self.n_citations > 0

    @property
    def any_unsupported(self) -> bool:
        return bool(self.unsupported_by_value or self.unsupported_by_category)


def hidden_literals(trace: Trace) -> list[str]:
    """Values present in the trace that the VISIBLE view never shows.

    Short and numeric tokens are excluded: matching "45" or "true" would fire on anything.
    """
    out: list[str] = []
    for s in trace.steps:
        if s.plan_text:
            out.append(s.plan_text)
        if s.tool_call:
            tc = s.tool_call
            if tc.raw_output:
                out.append(tc.raw_output)
            if tc.http_status is not None:
                out.append(str(tc.http_status))
            if tc.status != "ok":
                out.append(tc.status)
        if s.retrieval:
            out.extend(s.retrieval.documents)
            if s.retrieval.query:
                out.append(s.retrieval.query)
        if s.replay_record and isinstance(s.replay_record.get("output"), str):
            out.append(s.replay_record["output"])
    return [v for v in out if len(str(v)) >= 3]


def _explanation_text(result: B1Result) -> str:
    d = result.diagnosis
    parts = [e.get("observation", "") for e in d.evidence_used]
    parts.append(d.uncertainty)
    parts.extend(d.alternative_explanations)
    return "\n".join(p for p in parts if p)


def audit_grounding(result: B1Result, trace: Trace) -> GroundingAudit:
    """Score one B1 result for evidence grounding and invention.

    Only meaningful for the VISIBLE view; under FULL the model was shown everything, so
    `unsupported_*` are vacuously empty and the function says so by returning empty tuples.
    """
    d = result.diagnosis
    visible = set(result.visible_steps)
    text = _explanation_text(result)

    invalid: list[str] = []
    valid = 0
    for item in d.evidence_used:
        raw = item.get("step_id", "")
        m = re.search(r"-?\d+", str(raw))
        if m and int(m.group()) in visible:
            valid += 1
        else:
            invalid.append(str(raw))

    by_value: list[str] = []
    by_category: list[str] = []
    if result.view == "visible" and text:
        lowered = text.lower()
        for literal in hidden_literals(trace):
            token = str(literal).lower()
            # Long literals: substring match. Short ones (status codes): word boundary,
            # or "503" would fire inside an order id.
            hit = (token in lowered if len(token) > 8
                   else re.search(rf"\b{re.escape(token)}\b", lowered) is not None)
            if hit and token not in by_value:
                by_value.append(token)

        for sentence in re.split(r"(?<=[.;])\s+|\n", text):
            if not sentence.strip() or _HEDGES.search(sentence):
                continue
            for pattern, label in _CATEGORY_CLAIMS:
                if pattern.search(sentence) and label not in by_category:
                    by_category.append(label)

    return GroundingAudit(
        trace_id=result.trace_id, n_citations=len(d.evidence_used), valid_citations=valid,
        invalid_step_ids=tuple(invalid), unsupported_by_value=tuple(by_value),
        unsupported_by_category=tuple(by_category),
        suggested_a_fix=bool(_REMEDIATION.search(text)),
    )


def aggregate_grounding(audits: list[GroundingAudit]) -> dict:
    if not audits:
        return {}
    cited = [a for a in audits if a.cited_anything]
    total_citations = sum(a.n_citations for a in audits)
    valid = sum(a.valid_citations for a in audits)
    return {
        "n": len(audits),
        "cited_no_evidence_rate": 1 - len(cited) / len(audits),
        "mean_citations": mean(a.n_citations for a in audits),
        "valid_citation_rate": (valid / total_citations) if total_citations else 0.0,
        "invalid_step_citation_rate": mean(bool(a.invalid_step_ids) for a in audits),
        "unsupported_by_value_rate": mean(bool(a.unsupported_by_value) for a in audits),
        "unsupported_by_category_rate_HEURISTIC":
            mean(bool(a.unsupported_by_category) for a in audits),
        "unsupported_explanation_rate": mean(a.any_unsupported for a in audits),
        "suggested_a_fix_rate": mean(a.suggested_a_fix for a in audits),
    }


# --------------------------------------------------------------------------- calibration

@dataclass(frozen=True)
class CalibrationReport:
    n: int
    ece: float
    brier: float
    mean_confidence: float
    accuracy: float
    overconfidence: float
    high_confidence_error_rate: float
    bins: tuple[dict, ...]


def calibration(confidences: list[float], correct: list[bool], n_bins: int = 10,
                high: float = 0.8) -> CalibrationReport:
    """Expected calibration error, Brier score, and per-bin accuracy.

    `overconfidence` is mean confidence minus accuracy: positive means the model believes
    itself more than the evidence warrants. `high_confidence_error_rate` is the headline —
    confidently wrong is the specific complaint this baseline exists to test.
    """
    if not confidences:
        return CalibrationReport(0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, ())
    n = len(confidences)
    acc = mean(correct)
    conf = mean(confidences)
    brier = mean((c - float(y)) ** 2 for c, y in zip(confidences, correct))

    bins: list[dict] = []
    ece = 0.0
    for i in range(n_bins):
        lo, hi = i / n_bins, (i + 1) / n_bins
        idx = [j for j, c in enumerate(confidences)
               if (lo <= c < hi) or (i == n_bins - 1 and c == 1.0)]
        if not idx:
            bins.append({"bin": f"[{lo:.1f},{hi:.1f})", "n": 0,
                         "mean_confidence": None, "accuracy": None})
            continue
        b_conf = mean(confidences[j] for j in idx)
        b_acc = mean(correct[j] for j in idx)
        ece += (len(idx) / n) * abs(b_acc - b_conf)
        bins.append({"bin": f"[{lo:.1f},{hi:.1f})", "n": len(idx),
                     "mean_confidence": round(b_conf, 3), "accuracy": round(b_acc, 3)})

    confident = [j for j, c in enumerate(confidences) if c >= high]
    hce = mean(not correct[j] for j in confident) if confident else 0.0

    return CalibrationReport(n=n, ece=ece, brier=brier, mean_confidence=conf,
                             accuracy=acc, overconfidence=conf - acc,
                             high_confidence_error_rate=hce, bins=tuple(bins))


# --------------------------------------------------------------------------- report

def b1_report(results: list[B1Result], traces_by_id: dict[str, Trace],
              scores) -> dict:
    """Everything B1-specific, keyed for the results file.

    `scores` comes from `evaluation.metrics.score_episode`, so attribution and localization
    are computed by exactly the same code path as every other policy.
    """
    audits = [audit_grounding(r, traces_by_id[r.trace_id]) for r in results]
    by_id = {s.trace_id: s for s in scores}
    confidences, correct = [], []
    for r in results:
        s = by_id.get(r.trace_id)
        if s is None:
            continue
        confidences.append(r.diagnosis.confidence)
        correct.append(bool(s.attribution_correct))

    cal = calibration(confidences, correct)
    parse_failures = [r for r in results if not r.diagnosis.ok]
    provider_errors = [r for r in results if r.provider_error]

    return {
        "n": len(results),
        "view": results[0].view if results else None,
        "prompt_version": results[0].prompt_version if results else None,
        "format_version": results[0].format_version if results else None,
        "model": results[0].model if results else None,
        "parse_failure_rate": len(parse_failures) / len(results) if results else 0.0,
        "provider_error_rate": len(provider_errors) / len(results) if results else 0.0,
        "mean_tokens": mean(r.input_tokens + r.output_tokens for r in results) if results else 0,
        "grounding": aggregate_grounding(audits),
        "calibration": {
            "ece": round(cal.ece, 4), "brier": round(cal.brier, 4),
            "mean_confidence": round(cal.mean_confidence, 4),
            "accuracy": round(cal.accuracy, 4),
            "overconfidence": round(cal.overconfidence, 4),
            "high_confidence_error_rate": round(cal.high_confidence_error_rate, 4),
            "bins": list(cal.bins),
        },
    }
