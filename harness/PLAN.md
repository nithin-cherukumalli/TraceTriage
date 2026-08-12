# PLAN.md

> Task planning artifact. Updated as milestones are reached, not just at the end.
> Template: awesome-harness-engineering/templates/PLAN.md

## Task

Determine whether adaptive discriminative probe selection diagnoses failed AI-agent traces
more accurately than the best fixed debugging procedure, at equal probe budget.

## Context

Existing failure-attribution work (TRAIL, Who&When, AgenTracer) performs one-shot
attribution over a **fully visible** trace. None treats evidence gathering as a decision.
This project starts the diagnostic agent blind and makes it pay for what it looks at.

Success state: a signed, CI-backed answer to PH1 on a test split touched exactly once —
**including if the answer is no**. K4 explicitly contemplates the whole-trace LLM baseline
winning, in which case the finding is that probing does not pay at this trace length.

## Approach

Smallest scientifically valid experiment first. A synthetic corpus with hidden labels, a
closed six-probe action space with frozen prices, four baselines and one proposed policy,
one pre-registered primary metric, and a paired bootstrap. No POMDP, no RL, no learned
information gain in v0 — those are the ablation ladder above the current rung, and each is
only worth building if the rung below it proves to be the limiting factor.

Key trade-offs already taken:

- **Attribution primary, localization secondary.** An earlier draft used a blended cost
  scalar; it required defending a stipulated decision-cost matrix. An accuracy-vs-budget
  curve makes the same efficiency point without a contestable weighting.
- **Eleven families, not six.** Researcher-directed. Costs statistical power per family;
  buys coverage of the mechanisms practitioners actually name.
- **Synthetic first, real data at M8.** Faster, controllable, and honest about it. TRAIL
  is the mitigation and its results are reported even if weaker.

## Milestones

Mark `[x]` only when the verification gate passes.

- [x] **M0: specs frozen** — probe contract dated before the generator | verify: `test -f research/probe-contract.md`
- [x] **M1: model, probes, episode loop, contract tests** — ground truth provably unreachable | verify: `pytest tests/test_contract.py -q`
- [x] **M2: corpus generator + verifier** — eleven families, G1–G7 pass, every case probe-sufficient | verify: `python experiments/build_cases.py`
- [x] **H1a: harness scaffolding** — locked ledger, session logs, CLI | verify: `python scripts/harness.py check`
- [ ] **H1b: CI gate** — verification runs on every push, fails on lock drift | verify: `pytest -q && python scripts/harness.py check`
- [ ] **M3: B2-strong** — optimal fixed order searched on dev, applied unchanged to test | verify: `python experiments/run_experiment.py --report baselines`
- [ ] **M4: adaptive policy repaired** — budget curve monotone; escalation recall ≥ 0.70 on dev | verify: `python experiments/run_experiment.py --check-monotone`
- [ ] **M5: results report** — every kill criterion evaluated and shown | verify: `python experiments/analyze.py --results results/latest`
- [ ] **M6: B1 whole-trace LLM** — three seeds, variance reported, prompt committed | verify: `pytest tests/ -q`
- [ ] **M7: H5 evaluation** — escalation precision/recall on held-out families | verify: `python experiments/run_experiment.py --report unknown`
- [ ] **M8: real data** — TRAIL, then Who&When, with documented lossy mappings | verify: `pytest tests/test_adapters.py -q`
- [ ] **Final: E1 run once on a fresh seed** | verify: `python experiments/run_experiment.py --preregistered`

## Scope boundaries

In scope:

- Single-agent traces, discrete step granularity
- Read-only probing over stored traces; replay from preserved observations
- Five mechanisms, eleven families, one held-out family
- Attribution and localization; escalation as a first-class action

Out of scope (explicitly excluded from v0):

- POMDP formulation, reinforcement learning, learned information gain
- Multi-agent failure attribution (Who&When is loaded, not modelled as multi-agent)
- Automatic repair or remediation — this project diagnoses, it does not fix
- Live re-execution against a real environment
- Any claim that adaptivity "emerges"; the discrimination prior is authored knowledge

## Open questions

- [ ] Is the naive-Bayes independence assumption fixable within a flat categorical, or does
      F-011 force a factored belief? Resolve empirically on dev before choosing.
- [ ] Should escalation cost anything, given attribution is now primary? Currently a wrong
      escalation simply scores as incorrect attribution. Revisit if escalation rates spike.
- [ ] How many held-out families are enough to claim "unknown handling"? One is thin.
      Resolve in F-018.
- [ ] Does the `state_compare_probe` earn its 3.0 price? It is the only probe with no
      attribution role. Resolve in F-016's sensitivity sweep.

## Risks

- **Circularity.** The discrimination prior and the likelihood table are authored by the
  same person who wrote the generator. Mitigated by the frozen contract and by narrowing
  the claim, not eliminated. State it in the paper before a reviewer does.
- **Corpus realism.** Hand-designed faults are cleaner than real ones. M8 is the mitigation.
- **Stipulated costs.** Probe prices are ordinal guesses. F-016 tests whether the ranking
  survives a reprice; if it does not, the result is a cost-model artefact.
- **Small per-family n.** Eleven families at n=400 gives ~36 each. Per-family CIs will be
  wide; do not over-read family-level differences.
- **Pre-registration erosion.** Every diagnostic run on the test split spends credibility.
  Seeds 0/1000 are already burned.

## Notes

Running log of significant decisions. Append; do not overwrite. Full record in
`research/discussion-record.md`.

- **2026-08-12** — Attribution made primary; blended cost scalar demoted to secondary.
- **2026-08-12** — Amendment A1: tool names and arguments moved to the visible tier.
  Weakens the H2 contrast; accepted, and the contrast now rests on displaced-root-cause
  families where step targeting is the open question.
- **2026-08-12** — First generator leaked mechanism-specific strings into `final_error`;
  a zero-probe baseline scored 0.858. Fixed by drawing surface errors from a shared
  ambiguous pool. Promoted to corpus requirement G5.
- **2026-08-12** — Taxonomy revised to eleven families; `wrong_tool_selected` moved H2 → H1.
- **2026-08-12** — G6 verifier rewritten as subset existence after the first version used
  the policy's own belief model and condemned eight sound cases.
- **2026-08-12** — First end-to-end run: K1 fires. Not tuning. Cause localised to the
  belief update via the anti-monotone budget curve; tracked as F-011.

---
*Created: 2026-08-12*
