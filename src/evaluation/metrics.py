"""Scoring. Attribution is primary; localization is secondary and conditioned on it.

Two design choices carry most of the weight here:

1. **Escalation-aware attribution.** Escalations are not dropped from the denominator.
   An escalation is correct only when the truth is out of taxonomy. Otherwise a policy
   could protect its score by refusing every hard case.
2. **Localization is scored only where attribution was correct.** A lucky step guess
   attached to the wrong mechanism is not a diagnosis, and should not earn credit.
"""
from __future__ import annotations

from dataclasses import dataclass
from statistics import mean

from diagnosis.decision import Episode
from trace.models import GroundTruth, Mechanism


@dataclass(frozen=True)
class Score:
    trace_id: str
    policy: str
    family: str
    mechanism: Mechanism
    # primary
    attribution_correct: bool
    # secondary
    localization_exact: bool | None       # None when attribution was wrong
    localization_within1: bool | None
    localized_to_crash: bool | None
    # behaviour
    escalated: bool
    should_have_escalated: bool
    n_probes: int
    probe_cost: float


def score_episode(ep: Episode, gt: GroundTruth) -> Score:
    escalated = ep.terminal in ("escalate", "budget_exhausted")
    should_escalate = not gt.in_taxonomy

    if escalated:
        return Score(
            trace_id=ep.trace_id, policy=ep.policy, family=gt.family,
            mechanism=gt.mechanism,
            attribution_correct=should_escalate,
            localization_exact=None, localization_within1=None, localized_to_crash=None,
            escalated=True, should_have_escalated=should_escalate,
            n_probes=ep.n_probes, probe_cost=ep.probe_cost,
        )

    correct = (ep.mechanism == gt.mechanism) and gt.in_taxonomy
    loc = ep.localized_step
    return Score(
        trace_id=ep.trace_id, policy=ep.policy, family=gt.family, mechanism=gt.mechanism,
        attribution_correct=correct,
        localization_exact=(loc == gt.root_cause_step) if correct else None,
        localization_within1=(loc is not None and abs(loc - gt.root_cause_step) <= 1)
                             if correct else None,
        localized_to_crash=(loc == gt.crash_step and gt.crash_step != gt.root_cause_step)
                           if correct else None,
        escalated=False, should_have_escalated=should_escalate,
        n_probes=ep.n_probes, probe_cost=ep.probe_cost,
    )


def _mean(values) -> float:
    vals = [v for v in values if v is not None]
    return mean(vals) if vals else 0.0


def aggregate(scores: list[Score]) -> dict:
    if not scores:
        return {}
    esc = [s for s in scores if s.escalated]
    should = [s for s in scores if s.should_have_escalated]
    attributed = [s for s in scores if s.attribution_correct and not s.escalated]
    return {
        "n": len(scores),
        # PRIMARY
        "attribution_accuracy": _mean(s.attribution_correct for s in scores),
        # SECONDARY
        "localization_exact": _mean(s.localization_exact for s in attributed),
        "localization_within1": _mean(s.localization_within1 for s in attributed),
        "crash_step_confusion": _mean(s.localized_to_crash for s in attributed),
        "escalation_rate": len(esc) / len(scores),
        "escalation_precision": _mean(s.should_have_escalated for s in esc),
        "escalation_recall": _mean(s.escalated for s in should),
        "mean_probes": _mean(s.n_probes for s in scores),
        "mean_probe_cost": _mean(s.probe_cost for s in scores),
    }


def by_family(scores: list[Score]) -> dict[str, dict]:
    families = sorted({s.family for s in scores})
    return {f: aggregate([s for s in scores if s.family == f]) for f in families}


def paired_values(scores: list[Score], metric: str = "attribution_correct") -> dict[str, float]:
    return {s.trace_id: float(getattr(s, metric)) for s in scores
            if getattr(s, metric) is not None}


def paired_bootstrap(a: dict[str, float], b: dict[str, float], resamples: int = 10000,
                     seed: int = 0, alpha: float = 0.05) -> dict:
    """Paired bootstrap on a - b over shared trace ids. No claim from a CI crossing zero."""
    import random as _random
    keys = sorted(set(a) & set(b))
    if not keys:
        raise ValueError("no paired trace ids")
    diffs = [a[k] - b[k] for k in keys]
    rng = _random.Random(seed)
    n = len(diffs)
    boots = sorted(mean(diffs[rng.randrange(n)] for _ in range(n)) for _ in range(resamples))
    lo = boots[int(alpha / 2 * resamples)]
    hi = boots[int((1 - alpha / 2) * resamples) - 1]
    return {"mean_diff": mean(diffs), "ci_low": lo, "ci_high": hi,
            "n_pairs": n, "significant": not (lo <= 0.0 <= hi)}
