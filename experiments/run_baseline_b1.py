"""Run Baseline 1 over a corpus and report attribution, grounding and calibration.

    python experiments/run_baseline_b1.py --client mock
    python experiments/run_baseline_b1.py --client anthropic --view full --n 100

Defaults to the mock client so this runs offline with no API key.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from baselines.trace_formatter import TraceView                    # noqa: E402
from baselines.whole_trace_llm import WholeTraceLLMBaseline        # noqa: E402
from evaluation.experiment_runner import build_corpus              # noqa: E402
from evaluation.llm_metrics import b1_report, to_episode           # noqa: E402
from evaluation.metrics import aggregate, by_family, score_episode  # noqa: E402
from llm.client import get_client                                  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--client", default="mock", choices=["mock", "anthropic", "openai"])
    ap.add_argument("--model", default=None)
    ap.add_argument("--view", default="visible", choices=["visible", "full"])
    ap.add_argument("--n", type=int, default=40)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--out", default=None)
    a = ap.parse_args()

    kwargs = {"model": a.model} if a.model else {}
    client = get_client(a.client, **kwargs)
    corpus = build_corpus(seed=a.seed, n_cases=a.n, include_held_out=True)

    baseline = WholeTraceLLMBaseline(client=client, view=TraceView(a.view))
    results = baseline.run(corpus.cases)

    traces = {c.trace_id: c for c in corpus.cases}
    scores = [score_episode(to_episode(r), traces[r.trace_id].ground_truth) for r in results]

    overall = aggregate(scores)
    report = b1_report(results, traces, scores)

    print(f"\nB1 whole-trace LLM — client={a.client} view={a.view} n={len(results)}\n")
    print(f"  attribution accuracy        {overall['attribution_accuracy']:.3f}   PRIMARY")
    print(f"  localization exact          {overall['localization_exact']:.3f}")
    print(f"  crash-step confusion        {overall['crash_step_confusion']:.3f}")
    print(f"  escalation rate (H5 given)  {overall['escalation_rate']:.3f}")
    print(f"  parse failure rate          {report['parse_failure_rate']:.3f}")
    g = report["grounding"]
    print(f"\n  cited no evidence           {g['cited_no_evidence_rate']:.3f}")
    print(f"  valid citation rate         {g['valid_citation_rate']:.3f}")
    print(f"  invalid step citation       {g['invalid_step_citation_rate']:.3f}")
    print(f"  unsupported (exact)         {g['unsupported_by_value_rate']:.3f}")
    print(f"  unsupported (heuristic)     {g['unsupported_by_category_rate_HEURISTIC']:.3f}")
    print(f"  suggested a fix             {g['suggested_a_fix_rate']:.3f}")
    c = report["calibration"]
    print(f"\n  mean confidence             {c['mean_confidence']:.3f}")
    print(f"  accuracy                    {c['accuracy']:.3f}")
    print(f"  overconfidence              {c['overconfidence']:+.3f}")
    print(f"  ECE                         {c['ece']:.3f}")
    print(f"  Brier                       {c['brier']:.3f}")
    print(f"  high-confidence error rate  {c['high_confidence_error_rate']:.3f}\n")

    out = Path(a.out) if a.out else ROOT / "results" / f"b1_{a.client}_{a.view}"
    out.mkdir(parents=True, exist_ok=True)
    (out / "report.json").write_text(json.dumps(
        {"config": vars(a), "overall": overall, "by_family": by_family(scores),
         "b1": report}, indent=2, default=str))
    with (out / "diagnoses.jsonl").open("w") as fh:
        for r in results:
            fh.write(json.dumps(asdict(r), indent=None, default=str) + "\n")
    print(f"  written -> {out.relative_to(ROOT)}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
