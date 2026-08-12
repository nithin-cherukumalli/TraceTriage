"""Corpus verification: probe-sufficiency (G6) and the evidence audit.

The requirement is that every case *contain evidence reachable through probes*. That is
checkable, so it is checked.

How NOT to check it
-------------------
The first version of this verifier swept every probe over every step, fed the lot into
`Belief`, and asked whether the posterior landed on the truth. It failed 8/44 cases,
including every `api_failure`. The cases were fine. The verifier was measuring the
*policy's* belief model, which is known to double-count correlated evidence: one
`transport_failure` at P=0.92 for H4 was being drowned by four incidental `output_clean`
observations at P=0.05 each, collected from innocent steps the oracle had no reason to
visit.

That is a policy defect (M4), and letting it condemn the corpus would have had us rewrite
good cases to accommodate a bad belief update.

How it is checked
-----------------
Sufficiency is a property of the *evidence*, not of any particular reasoner. So the test is
subset existence: does there exist a set of at most `max_probes` (probe, step) pairs whose
evidence identifies the true mechanism? Searching smallest-first also yields something
independently useful -- `oracle_probes`, the minimum number of probes needed to solve the
case. That is a lower bound no policy can beat, and the right yardstick to report an
adaptive policy against.

The invariant inverts for the held-out family: every probe must return `ok` and *no* probe
may yield an anomalous signature, so the agent runs out of explanations rather than finding
a marker. An H5 case with a detectable signal would let a policy learn "unknown", which is
exactly what H5 must not be.
"""
from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations

from diagnosis.belief import Belief, all_signatures
from probes.base import all_probes, get_probe
from .models import Evidence, Mechanism, Trace

#: A subset counts as identifying only if it is this confident. Prevents a bare 0.26
#: plurality being called "sufficient evidence".
DECISIVE = 0.60


@dataclass(frozen=True)
class CaseAudit:
    trace_id: str
    family: str
    mechanism: Mechanism
    in_taxonomy: bool
    signatures: tuple[str, ...]
    #: Minimum probes any reasoner would need. None if the case is unsolvable.
    oracle_probes: int | None
    #: The cheapest identifying probe set, as (probe_id, step_index) pairs.
    oracle_probe_set: tuple[tuple[str, int | None], ...]
    probe_sufficient: bool
    reason: str


def _bind_reference(reference_lookup) -> None:
    probe = get_probe("compare_known_good")
    if hasattr(probe, "bind"):
        probe.bind(reference_lookup or (lambda _: None))


def sweep(trace: Trace, reference_lookup=None) -> list[Evidence]:
    """Every probe against every step. Unlimited budget; used for the H5 cleanliness test."""
    _bind_reference(reference_lookup)
    evidence: list[Evidence] = []
    for pid in all_probes():
        if pid == "compare_known_good":
            evidence.append(get_probe(pid).execute(trace, None))
            continue
        for step in trace.steps:
            evidence.append(get_probe(pid).execute(trace, step.index))
    return evidence


def _applicable_evidence(trace: Trace, reference_lookup=None) -> list[Evidence]:
    """Only probe/step pairs that actually return something. The oracle is not stupid."""
    return [e for e in sweep(trace, reference_lookup) if e.ok]


def find_minimal_probe_set(trace: Trace, reference_lookup=None, max_probes: int = 3):
    """Smallest set of probes whose evidence identifies the true mechanism.

    Searched smallest-first, so the first hit is minimal. Capped at `max_probes`: a case
    needing four coordinated probes to be solvable at all is not a diagnosis problem, it is
    a puzzle, and belongs out of the corpus.
    """
    gt = trace.ground_truth
    tools = tuple(s.tool_call.name for s in trace.steps if s.tool_call)
    candidates = _applicable_evidence(trace, reference_lookup)

    for size in range(1, max_probes + 1):
        for subset in combinations(candidates, size):
            belief = Belief.rebuild(list(subset), trace.task, tools)
            if belief.top() is gt.mechanism and belief.top_prob() >= DECISIVE:
                return size, tuple((e.probe_id, e.step_index) for e in subset)
    return None, ()


def audit_case(trace: Trace, reference_lookup=None, max_probes: int = 3) -> CaseAudit:
    gt = trace.ground_truth
    tools = tuple(s.tool_call.name for s in trace.steps if s.tool_call)
    full = sweep(trace, reference_lookup)
    sigs = tuple(sorted(set(all_signatures(full, trace.task, tools))))

    if not gt.in_taxonomy:
        clean = not Belief.rebuild(full, trace.task, tools).saw_anomaly()
        return CaseAudit(
            trace_id=trace.trace_id, family=gt.family, mechanism=gt.mechanism,
            in_taxonomy=False, signatures=sigs, oracle_probes=None, oracle_probe_set=(),
            probe_sufficient=clean,
            reason=("ok: probes all return, none is anomalous, so escalation is the only "
                    "correct action") if clean
                   else f"LEAK: anomalous signature present in {list(sigs)}",
        )

    size, probe_set = find_minimal_probe_set(trace, reference_lookup, max_probes)
    return CaseAudit(
        trace_id=trace.trace_id, family=gt.family, mechanism=gt.mechanism,
        in_taxonomy=True, signatures=sigs, oracle_probes=size, oracle_probe_set=probe_set,
        probe_sufficient=size is not None,
        reason="ok" if size is not None
               else f"UNSOLVABLE: no probe set of size <= {max_probes} identifies "
                    f"{gt.mechanism.value}",
    )


def audit_corpus(cases: list[Trace], reference_lookup=None, max_probes: int = 3):
    audits = [audit_case(c, reference_lookup, max_probes) for c in cases]
    failures = [a for a in audits if not a.probe_sufficient]
    solved = [a for a in audits if a.oracle_probes]

    by_family: dict[str, dict] = {}
    for a in audits:
        e = by_family.setdefault(a.family, {"n": 0, "sufficient": 0, "oracle_probes": []})
        e["n"] += 1
        e["sufficient"] += int(a.probe_sufficient)
        if a.oracle_probes:
            e["oracle_probes"].append(a.oracle_probes)
    for e in by_family.values():
        probes = e.pop("oracle_probes")
        e["mean_oracle_probes"] = round(sum(probes) / len(probes), 2) if probes else None

    summary = {
        "n": len(audits),
        "probe_sufficient": len(audits) - len(failures),
        "mean_oracle_probes": (round(sum(a.oracle_probes for a in solved) / len(solved), 2)
                               if solved else None),
        "needing_two_or_more_probes": sum(a.oracle_probes >= 2 for a in solved),
        "failures": [(a.trace_id, a.family, a.reason) for a in failures[:10]],
        "by_family": by_family,
    }
    return audits, summary
