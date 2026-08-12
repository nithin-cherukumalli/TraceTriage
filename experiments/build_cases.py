"""Build a synthetic failure-case corpus and verify it before anyone experiments on it.

Emits two files, and the pair is the point:

  <name>.json             full records, ground truth included -- the EVALUATOR's copy
  <name>.agent_view.json  exactly what the diagnostic agent receives at episode start

The second is produced by `make_observation()`, the same function the episode loop uses.
Diffing the two is the demonstration that ground truth is hidden: the agent view contains
no mechanism, no failure step, no family, and no probe-gated field.

Default is the 40-case INSPECTION corpus: small enough to read by hand, stratified so every
family appears. It cannot test the pre-registered hypothesis -- with five classes and
eleven families a 10-point accuracy gap carries a CI near +/-15 points, and n=40 leaves
~3.6 cases per family. Pass --n 400 --allocation by_mechanism for an experimental corpus.
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from diagnosis.hypothesis import FAMILIES                       # noqa: E402
from diagnosis.policy import VisibleOnlyPolicy                  # noqa: E402
from evaluation.experiment_runner import Corpus, run_policy     # noqa: E402
from evaluation.metrics import aggregate                        # noqa: E402
from trace.models import make_observation                       # noqa: E402
from trace.parser import to_dict, validate_against_schema       # noqa: E402
from trace.synthesize import GeneratorConfig, generate          # noqa: E402
from trace.verify import audit_corpus                           # noqa: E402

OUT = Path(__file__).resolve().parents[1] / "data" / "synthetic_cases"


def agent_view(trace) -> dict:
    """Exactly what the policy sees. Built through the one sanctioned door."""
    obs = make_observation(trace, budget=6)
    return {
        "trace_id": trace.trace_id,
        "task": obs.task,
        "final_result": obs.final_result,
        "final_error": obs.final_error,
        "has_reference_trace": obs.has_reference_trace,
        "budget_remaining": obs.budget_remaining,
        "steps": [dataclasses.asdict(h) for h in obs.headers],
    }


def checks(cases, references, audits) -> dict:
    n = len(cases)
    gts = [c.ground_truth for c in cases]
    mech = Counter(g.mechanism.value for g in gts)
    fam = Counter(g.family for g in gts)
    displaced = [g for g in gts if g.root_cause_step != g.crash_step]
    with_distractor = [g for g in displaced if g.distractor_steps]
    visible_only = aggregate(
        run_policy(Corpus(cases, references), VisibleOnlyPolicy(), budget=0)
    )["attribution_accuracy"]

    return {
        "G1 root_cause != crash in >= 40%": len(displaced) / n >= 0.40,
        "G2 every mechanism present": len(mech) >= 4,
        "G3 distractor between root and crash in >= 50% of displaced":
            (len(with_distractor) / len(displaced) if displaced else 0) >= 0.50,
        "G4 held-out family labelled out-of-taxonomy": all(
            not FAMILIES[g.family].in_taxonomy or g.in_taxonomy for g in gts),
        "G5 visible-only attribution < 0.55": visible_only < 0.55,
        "G6 every case probe-sufficient": all(a.probe_sufficient for a in audits),
        "G7 every family represented": len(fam) == len(FAMILIES),
        "schema valid": not validate_against_schema(cases),
    }, {"mechanism_prior": {k: round(v / n, 3) for k, v in sorted(mech.items())},
        "family_counts": dict(sorted(fam.items())),
        "displaced_rate": round(len(displaced) / n, 3),
        "silent_failures": sum(1 for c in cases if not c.final_error),
        "visible_only_attribution": round(visible_only, 3)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=40)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--allocation", default="by_family",
                    choices=["by_family", "by_mechanism"])
    ap.add_argument("--name", default="inspection_40")
    ap.add_argument("--no-held-out", action="store_true")
    a = ap.parse_args()

    cfg = GeneratorConfig(seed=a.seed, n_cases=a.n, include_held_out=not a.no_held_out,
                          allocation=a.allocation)
    cases, references = generate(cfg)
    audits, audit_summary = audit_corpus(cases, references.get)
    passed, stats = checks(cases, references, audits)

    OUT.mkdir(parents=True, exist_ok=True)
    audit_by_id = {x.trace_id: x for x in audits}

    payload = {
        "corpus": a.name,
        "purpose": ("inspection: hand-auditable, stratified, NOT powered for the "
                    "pre-registered hypothesis" if a.n < 200 else "experimental"),
        "generator": dataclasses.asdict(cfg),
        "taxonomy": {fid: {"mechanism": f.mechanism.value,
                           "description": f.description,
                           "in_taxonomy": f.in_taxonomy,
                           "needs_cross_evidence": f.needs_cross_evidence}
                     for fid, f in FAMILIES.items()},
        "statistics": stats,
        "verification": {"checks": passed, "audit": audit_summary},
        "cases": [
            {**to_dict(c),
             "_audit": {"oracle_probes": audit_by_id[c.trace_id].oracle_probes,
                        "oracle_probe_set": [list(p) for p in
                                             audit_by_id[c.trace_id].oracle_probe_set],
                        "signatures": list(audit_by_id[c.trace_id].signatures),
                        "reason": audit_by_id[c.trace_id].reason}}
            for c in cases
        ],
        "reference_traces": [to_dict(r) for r in references.values()],
    }
    (OUT / f"{a.name}.json").write_text(json.dumps(payload, indent=2, default=str))
    (OUT / f"{a.name}.agent_view.json").write_text(json.dumps(
        {"corpus": a.name,
         "note": ("This is the complete input to the diagnostic agent. No mechanism, "
                  "no failure step, no family, no probe-gated field. Everything else "
                  "costs a probe."),
         "cases": [agent_view(c) for c in cases]}, indent=2, default=str))

    print(f"\n=== {a.name}  n={len(cases)} ===")
    for k, v in stats.items():
        print(f"  {k}: {v}")
    print(f"  mean oracle probes: {audit_summary['mean_oracle_probes']}")
    print(f"  cases needing >=2 probes: {audit_summary['needing_two_or_more_probes']}")
    print()
    for name, ok in passed.items():
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}")
    if audit_summary["failures"]:
        print("\n  probe-sufficiency failures:")
        for tid, fam, reason in audit_summary["failures"]:
            print(f"    {tid} ({fam}): {reason}")
    ok = all(passed.values())
    print(f"\nCorpus {'ACCEPTED' if ok else 'REJECTED'} -> {OUT / (a.name + '.json')}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
