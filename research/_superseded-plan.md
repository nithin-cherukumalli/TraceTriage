# Implementation Plan — Active Diagnosis for Failed AI-Agent Execution Traces

Status: v0 scaffold complete and green (17 tests). This document is the plan of record.

---

## 1. What the experiment actually is

Strip away the framing and this is a **sequential decision problem under partial
observability with a hidden discrete label**:

- Hidden state: `(mechanism, root_cause_step, family)`
- Observation: redacted trace (step headers + final error) + accumulated evidence
- Actions: 6 probes, `diagnose(mechanism, step)`, `escalate`
- Reward: negative expected diagnostic cost

That framing matters because it tells you what the *smallest valid* experiment is:
a corpus with hidden labels, a closed probe set with fixed prices, three policies, one
scalar objective, and a paired significance test. Everything else is decoration for v0.

---

## 2. The four assumptions I want to attack before you write the generator

### A1. "Adaptive beats fixed" is almost tautologically true against a *weak* fixed baseline

A checklist that always probes in the order `output → args → context → plan → compare →
replay` will lose to anything responsive. That result is worth nothing. The baseline that
matters is **B2-strong: the optimal fixed probe order**, found by search on the dev split.
If your adaptive policy cannot beat the best possible non-adaptive ordering, you have no
paper — you have a probe-set problem.

This is registered as kill criterion **K1**. Build B2-strong (M3) *before* the adaptive
policy (M4), so you never get to see the adaptive number first and rationalise around it.

### A2. Designing the fault injector and the probes together makes the result circular

If I write "H2 = malformed args" into the generator and also write "probe `validate_tool_args`
reveals malformed args", the adaptive policy is just reading my mind. Three mitigations,
all already baked into the repo:

1. `specs/PROBE_CONTRACT.md` is **frozen before** `generation/` is implemented. The file is
   write-once with a dated-amendment section.
2. The generator produces the label as a **byproduct of a generative process** — a scripted
   agent runs, a component is perturbed, the trace records what happened — never as an
   annotation written alongside the trace.
3. The discrimination matrix in `policies/discrimination.py` carries an explicit caveat in
   its docstring: it is authored knowledge, and the v0 claim is narrowed accordingly to
   *"a cheap authored discrimination prior beats the best fixed order"*, not *"adaptivity
   emerges"*. Say this in the paper before a reviewer says it for you.

### A3. Localization is trivial unless the corpus makes it hard

Your own lesson 6 says the visible failure step ≠ the first meaningful wrong step. If the
corpus doesn't enforce that, "localize to the last step" scores 90% and the metric is dead.
Hence requirement **G1**: `root_cause_step != crash_step` in ≥40% of traces, and kill
criterion **K3** which invalidates the corpus if the crash-step heuristic wins.

The fixture trace in `tests/conftest.py` is built exactly this way: a stale retrieved
document at step 1 causes a tool rejection at step 3. It is deliberately a trap for
whole-trace reading.

### A4. H5 cannot be a class you predict — it has to be *held out*

If the generator produces H5 traces and the policy has an H5 likelihood, you have measured
5-way classification, not unknown-failure handling. In `configs/taxonomy.yaml` the two
held-out families (`silent_state_corruption`, `prompt_template_regression`) appear **only
in the test split**, are absent from dev, and are structurally different (they are not
localizable at step granularity at all). Escalation is then the only correct behaviour, and
`escalation_precision` measures something real.

Corollary: escalating on an in-taxonomy trace must **cost** (3.0 units). Otherwise a policy
wins by escalating always.

---

## 3. One number, pre-registered

Accuracy alone rewards probing forever; probe count alone rewards guessing. So the primary
metric is a single scalar with a frozen cost matrix:

```
EDC = probe_cost + decision_cost
```

`configs/costs.yaml` holds both halves and is frozen before any policy tuning.
Everything in your original metric list survives as a secondary — reported alongside,
never instead. Localization and attribution are scored in separate fields (lesson 8), and
`crash_step_confusion` is reported explicitly so the paper can show the two tasks come apart.

---

## 4. Milestones

| # | Deliverable | Exit criterion | Est. |
|---|---|---|---|
| **M0** | `specs/*` frozen | 3 spec files committed, unmodified thereafter | done |
| **M1** | Schema, redaction, probes, episode loop, leakage tests | `make test` green; random policy runs end-to-end | done |
| **M2** | Synthetic simulator + 12 fault families | 400 traces; G1 ≥40%; per-class prior in [0.15, 0.35]; K2/K3 checks pass | 3–4 d |
| **M3** | B0-trivial, B2-checklist, **B2-strong** | best fixed order found on dev; EDC reported | 2 d |
| **M4** | Belief + discrimination matrix + adaptive policy | P beats B2-strong on dev, or K1 fires | 3 d |
| **M5** | Metrics, paired bootstrap, report | E1 runs on test once; CI-backed table | 2 d |
| **M6** | B1 whole-trace LLM | token cost folded into EDC; 3 seeds for variance | 2 d |
| **M7** | Held-out families → H5 evaluation | escalation precision/recall on test | 1 d |
| **M8** | TRAIL adapter (real traces) | ≥100 real traces; documented lossy mapping table | 4 d |

**Explicit non-goals for v0:** POMDP formulation, RL, learned information gain, multi-agent
attribution, automatic repair, live re-execution. Those are the M9+ ablation ladder, and
each is only worth building if the M5 result is positive and the M4 heuristic is the
bottleneck.

---

## 5. The ablation ladder (do NOT start here)

Once M5 gives a signed, CI-backed result, the natural progression is:

1. authored discrimination matrix (M4) →
2. expected-posterior-disagreement selection →
3. expected information gain with learned likelihoods →
4. explicit POMDP / learned policy

Each rung only justifies itself if the rung below it is the limiting factor. Report the
ladder as future work in the v0 paper.

---

## 6. Threats to validity to state in the paper

- **Synthetic corpus.** Fault families are hand-designed; real failures are messier and
  co-occur more. M8 (TRAIL) is the mitigation, and its results should be reported even if
  weaker.
- **Authored priors.** Both the likelihood table and the discrimination matrix encode human
  debugging knowledge. The honest claim is about *whether cheap authored structure pays*,
  not about emergent reasoning.
- **Cost model is stipulated.** Probe prices are ordinal guesses, not measured latencies.
  Run a sensitivity sweep (±50% on each probe price) and report whether the ranking flips.
  If it flips, the result is a cost-model artefact.
- **No preserved observations in real datasets.** `replay_tool_call` returns `unavailable`
  on every TRAIL trace. Report that as a finding about the state of tracing infrastructure —
  it is arguably the most publishable observation in the whole project.

---

## 7. Immediate next actions

1. Read `specs/PROBE_CONTRACT.md` and `specs/PREREGISTRATION.md` and **push back now**.
   After M2 starts, changing them costs you the frozen-spec defence.
2. Confirm the decision-cost matrix numbers (0 / 4 / 10 / 3 / 0). They encode a value
   judgement: a wrong diagnosis is ~2.5× worse than a needless escalation. That ratio is
   the single most contestable number in the project.
3. Then M2: the simulator. That is the next real engineering.
