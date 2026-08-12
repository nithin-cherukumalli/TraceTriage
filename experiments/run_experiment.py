"""Run the full comparison and write results/. See research/preregistration.md."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from evaluation.experiment_runner import main as run_main   # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="results/latest")
    ap.add_argument("--n-dev", type=int, default=200)
    ap.add_argument("--n-test", type=int, default=400)
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args()
    results = run_main(a.out, a.n_dev, a.n_test, a.seed)
    print(json.dumps({k: v for k, v in results.items() if k != "policies"}, indent=2))
    for name, block in results["policies"].items():
        o = block["overall"]
        print(f"{name:18s} attribution={o['attribution_accuracy']:.3f}  "
              f"loc_exact={o['localization_exact']:.3f}  "
              f"esc={o['escalation_rate']:.3f}  probes={o['mean_probes']:.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
