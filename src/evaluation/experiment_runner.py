"""Build corpora, run policies over them, and report.

Order of operations is fixed by research/preregistration.md: dev corpus -> B2-strong
search on dev -> only then instantiate the adaptive policy -> test split touched once.
"""
from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from diagnosis.decision import DEFAULT_BUDGET, Episode, run_episode
from diagnosis.policy import (
    AdaptivePolicy, ChecklistPolicy, DEFAULT_CHECKLIST, RandomPolicy, TrivialPolicy,
    VisibleOnlyPolicy, search_best_fixed_order,
)
from trace.models import Trace
from trace.synthesize import GeneratorConfig, generate

from .metrics import Score, aggregate, by_family, paired_bootstrap, paired_values, score_episode


class Corpus:
    """Cases plus the reference-trace index that compare_known_good resolves against."""

    def __init__(self, cases: list[Trace], references: dict[str, Trace]):
        self.cases = cases
        self.references = references

    def lookup(self, trace_id: str) -> Trace | None:
        return self.references.get(trace_id)

    def __len__(self) -> int:
        return len(self.cases)


def build_corpus(seed: int, n_cases: int, include_held_out: bool) -> Corpus:
    cases, refs = generate(GeneratorConfig(seed=seed, n_cases=n_cases,
                                           include_held_out=include_held_out))
    return Corpus(cases, refs)


def run_policy(corpus: Corpus, policy, budget: int = DEFAULT_BUDGET) -> list[Score]:
    out: list[Score] = []
    for case in corpus.cases:
        ep: Episode = run_episode(case, policy, budget=budget,
                                  reference_lookup=corpus.lookup)
        out.append(score_episode(ep, case.ground_truth))
    return out


def attribution(scores: list[Score]) -> float:
    return aggregate(scores)["attribution_accuracy"]


def budget_curve(corpus: Corpus, policy, budgets=(1, 2, 3, 4, 5, 6)) -> dict[int, float]:
    """Secondary metric S3: attribution accuracy as a function of probe budget.

    Replaces a single blended cost scalar. A curve cannot be gamed by reweighting terms.
    """
    return {b: attribution(run_policy(corpus, policy, budget=b)) for b in budgets}


def main(out_dir: str = "results/latest", n_dev: int = 200, n_test: int = 400,
         seed: int = 0) -> dict:
    dev = build_corpus(seed=seed, n_cases=n_dev, include_held_out=False)
    test = build_corpus(seed=seed + 1000, n_cases=n_test, include_held_out=True)

    # --- B2-strong is searched on DEV, before the adaptive policy is instantiated.
    best_order, best_dev = search_best_fixed_order(
        dev, run_fn=lambda c, p: run_policy(c, p), score_fn=attribution, max_orders=40,
        seed=seed,
    )

    policies = [
        TrivialPolicy(),
        VisibleOnlyPolicy(),
        RandomPolicy(seed=seed),
        ChecklistPolicy(DEFAULT_CHECKLIST),
        ChecklistPolicy(best_order, name="b2_strong"),
        AdaptivePolicy(),
    ]

    results: dict = {"best_fixed_order": list(best_order), "dev_score_of_best": best_dev,
                     "policies": {}, "comparisons": {}, "budget_curves": {}}
    all_scores: dict[str, list[Score]] = {}
    for policy in policies:
        scores = run_policy(test, policy)
        all_scores[policy.name] = scores
        results["policies"][policy.name] = {
            "overall": aggregate(scores), "by_family": by_family(scores),
        }

    for name in ("b2_strong", "p_adaptive"):
        results["budget_curves"][name] = {
            str(k): v for k, v in budget_curve(
                test, next(p for p in policies if p.name == name)).items()
        }

    # PH1: adaptive vs the strongest fixed procedure.
    results["comparisons"]["p_adaptive_vs_b2_strong"] = paired_bootstrap(
        paired_values(all_scores["p_adaptive"]),
        paired_values(all_scores["b2_strong"]),
    )
    results["comparisons"]["p_adaptive_vs_b2_checklist"] = paired_bootstrap(
        paired_values(all_scores["p_adaptive"]),
        paired_values(all_scores["b2_checklist"]),
    )

    path = Path(out_dir)
    path.mkdir(parents=True, exist_ok=True)
    (path / "results.json").write_text(json.dumps(results, indent=2, default=str))
    for name, scores in all_scores.items():
        with (path / f"episodes_{name}.jsonl").open("w") as fh:
            for s in scores:
                fh.write(json.dumps(asdict(s), default=str) + "\n")
    return results
