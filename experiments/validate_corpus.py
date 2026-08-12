"""M2 exit criterion. Generates a corpus and checks it is worth experimenting on.

A corpus that fails G1 or G3 makes localization trivial; one that fails G2 makes the
attribution prior do the work. Either way the experiment measures nothing, so this runs
before any policy is compared.
"""
from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from diagnosis.policy import VisibleOnlyPolicy                  # noqa: E402
from evaluation.experiment_runner import Corpus, run_policy     # noqa: E402
from evaluation.metrics import aggregate                        # noqa: E402
from trace.parser import save_cases, validate_against_schema    # noqa: E402
from trace.synthesize import GeneratorConfig, generate          # noqa: E402

OUT = Path(__file__).resolve().parents[1] / "data" / "synthetic_cases"


def visible_only_accuracy(cases, references) -> float:
    """G5. How much of the task does the FREE information already solve?

    This is the empirical leakage guard, and it is the one that matters. A regex for
    mechanism names in visible fields is not enough: the first version of this generator
    passed every regex check while writing `policy_violation` and `precondition_not_met`
    into final_error, which a zero-probe baseline decoded to 0.86 attribution accuracy.
    Only running the baseline caught it.
    """
    scores = run_policy(Corpus(cases, references), VisibleOnlyPolicy(), budget=0)
    return aggregate(scores)["attribution_accuracy"]


def report(cases, label: str, references) -> dict:
    n = len(cases)
    gts = [c.ground_truth for c in cases]
    displaced = [g for g in gts if g.root_cause_step != g.crash_step]
    mech = Counter(g.mechanism.value for g in gts)
    fam = Counter(g.family for g in gts)
    with_distractor = [g for g in displaced if g.distractor_steps]
    silent = [c for c in cases if not c.final_error]

    vis = visible_only_accuracy(cases, references)
    checks = {
        "G1 root_cause != crash >= 40%": len(displaced) / n >= 0.40,
        "G5 visible-only attribution < 0.55 (K5)": vis < 0.55,
        "G2 mechanism prior in [0.20,0.30]": all(
            0.20 <= mech[m] / n <= 0.30 for m in
            ("H1_planning", "H2_tool", "H3_context", "H4_external")) if label == "dev"
            else True,
        "G3 distractor between root and crash >= 50% of displaced":
            (len(with_distractor) / len(displaced) if displaced else 0) >= 0.50,
        "G4 held-out absent from dev": ("silent_state_corruption" not in fam)
            if label == "dev" else ("silent_state_corruption" in fam),
        "schema valid": not validate_against_schema(cases),
    }
    return {"label": label, "n": n,
            "displaced_rate": round(len(displaced) / n, 3),
            "mechanism_prior": {k: round(v / n, 3) for k, v in sorted(mech.items())},
            "family_counts": dict(sorted(fam.items())),
            "silent_failures": len(silent),
            "distractor_coverage": round(
                len(with_distractor) / len(displaced), 3) if displaced else 0.0,
            "visible_only_attribution": round(vis, 3),
            "checks": checks}


def main() -> int:
    dev_cases, dev_refs = generate(
        GeneratorConfig(seed=0, n_cases=200, include_held_out=False))
    test_cases, test_refs = generate(
        GeneratorConfig(seed=1000, n_cases=400, include_held_out=True))

    save_cases(dev_cases, OUT / "dev.jsonl")
    save_cases(test_cases, OUT / "test.jsonl")

    ok = True
    for cases, label, refs in ((dev_cases, "dev", dev_refs),
                               (test_cases, "test", test_refs)):
        r = report(cases, label, refs)
        print(f"\n=== {label}  n={r['n']} ===")
        print(f"  displaced (root != crash): {r['displaced_rate']}")
        print(f"  distractor coverage:       {r['distractor_coverage']}")
        print(f"  silent failures (no error):{r['silent_failures']}")
        print(f"  visible-only attribution:  {r['visible_only_attribution']}")
        print(f"  mechanism prior:           {r['mechanism_prior']}")
        print(f"  families:                  {r['family_counts']}")
        for name, passed in r["checks"].items():
            print(f"  [{'PASS' if passed else 'FAIL'}] {name}")
            ok &= passed
    print("\nCorpus", "ACCEPTED" if ok else "REJECTED")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
