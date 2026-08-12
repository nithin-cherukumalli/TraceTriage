# agent-diagnosis

**Active Diagnosis for Failed AI-Agent Execution Traces**

When an AI agent fails and several failure mechanisms are possible, can an adaptive
diagnostic agent choose better evidence-gathering actions than fixed debugging procedures?

The diagnostic agent starts **blind**. It sees the shape of a failed run — steps, tool
names, arguments, the final result — and must pay from a bounded budget to see anything
else. Then it names the failure mechanism, or escalates.

```
failed trace (redacted)
  → competing hypotheses
  → select probe        ← the decision under study
  → observe evidence
  → update belief
  → diagnose / probe again / escalate
```

---

## Repository structure

Every file below exists because something in `research/` requires it. Nothing is
scaffolding for its own sake.

### `harness/` — how work is tracked across sessions

Follows [awesome-harness-engineering](https://github.com/ai-boost/awesome-harness-engineering).

| file | purpose |
|---|---|
| `features.json` | **The locked feature ledger.** 22 features with dependencies, acceptance criteria and a runnable verify command each. Locked fields are covered by a SHA-256 in `features.lock`; changing one without a `lock_version` bump and a changelog entry fails CI. |
| `feature_schema.json` | Refuses under-specified features: fewer than two acceptance criteria, a thin `why`, or a missing `verify` command all fail validation. |
| `PLAN.md` | Milestones with verification gates, scope boundaries, open questions, risks. |
| `IMPLEMENT.md` | Append-only implementation log: decisions, deviations, resolved and unresolved questions. |
| `HARNESS_CHECKLIST.md` | Filled review checklist, including what would make each harness component unnecessary. |
| `PROGRESS.md` | Generated index of every session. |
| `sessions/` | One log per working session. Each ends with "Carried forward", written assuming the next session remembers nothing. |

`AGENTS.md` at the repo root (symlinked as `CLAUDE.md`) states structure, permissions and
verification gates. `scripts/harness.py` is the CLI:

```bash
python scripts/harness.py next          # the single next actionable feature
python scripts/harness.py start F-010   # marks in progress, opens a session log
python scripts/harness.py done F-010    # refuses unless the verify command passes
python scripts/harness.py status        # the whole ledger
```

Exactly one feature may be in progress; the CLI refuses a second.

### `research/` — the scientific record, written before the code it governs

| file | purpose |
|---|---|
| `problem.md` | Formal statement of the decision problem, the H1–H5 taxonomy, the eleven failure families, and the task hierarchy (attribution primary, localization secondary). The reference for what is being measured. |
| `probe-contract.md` | **FROZEN.** The closed probe set, their costs, their semantics, the three visibility tiers, and the leakage rules. Dated before `src/trace/synthesize.py` existed. Write-once; changes require a dated amendment. Currently at **amendment A1**. |
| `preregistration.md` | Primary hypothesis, secondary metrics, baselines, statistical protocol, corpus requirements G1–G7, and kill criteria K1–K5. Written before the test split is scored. |
| `literature.md` | TRAIL, Who&When, AgenTracer. What each gives us and where each stops — the gap this project sits in. |
| `discussion-record.md` | Append-only decision log. Why the taxonomy was revised, why attribution became primary, why amendment A1 was accepted despite weakening the H2 contrast. |

### `schemas/` — the visibility boundary, machine-readable

| file | purpose |
|---|---|
| `trace_schema.json` | JSON Schema for a trace, where **every field carries an `x-visibility` tag**: `VISIBLE`, `PROBE` (with the probe that unlocks it), or `HIDDEN`. This file is the single authority on what the diagnostic agent may see for free. `tests/test_contract.py` asserts the Python model agrees with it. |

### `data/synthetic_cases/` — generated corpora

Holds the corpora. `inspection_40.json` and its `.agent_view.json` twin are **checked in**
— they are small, and the pair is the auditable evidence that ground truth is hidden.
Large experimental corpora are gitignored: the generator is deterministic given a seed, so
the seed is the artefact worth versioning, not 400 serialised traces.

### `src/trace/` — the data model and the corpus generator

| file | purpose |
|---|---|
| `models.py` | The dataclasses. `Trace`/`Step`/`ToolCall`/`RetrievedContext` are the full record; `StepHeader`/`Observation` are the redacted projection a policy receives; `GroundTruth` is evaluator-only. `make_observation()` is the **single sanctioned door** between the two. |
| `parser.py` | JSONL load/save plus a dependency-free structural validator. `load_cases` is the only way a trace enters an experiment, so split filtering lives here. |
| `synthesize.py` | **The case generator.** Eleven family templates that build a plausible support-agent run, perturb exactly one component, and let the consequences propagate. The label is a byproduct of construction, never an annotation. Written *after* the probe contract was frozen. |
| `verify.py` | Corpus verification. Probe-sufficiency (G6) by **subset search** — does a probe set of size ≤ 3 identify the truth? — plus `oracle_probes`, the minimum probes per case. |

### `src/probes/` — one file per probe, plus the registry

| file | purpose |
|---|---|
| `base.py` | `ProbeSpec`, the `Probe` protocol, the **frozen cost table**, and the registry. Costs live in code, not config, so a price change shows up in review next to the contract that froze it. |
| `schema_probe.py` | Reveals the tool's **declared schema** and a validation verdict. Isolates `malformed_arguments` and `schema_mismatch`. |
| `tool_output_probe.py` | Reveals raw output, status, HTTP code, latency. Separates transport failure (H4) from semantic refusal. |
| `context_probe.py` | Reveals retrieval query, documents, scores. Isolates `missing_context` and `wrong_retrieved_information` (H3). |
| `plan_probe.py` | Reveals plan and reflection text. Carries both cross-evidence families: nothing here is decisive alone. |
| `replay_probe.py` | Compares against the **preserved external observation**. Returns `none` / `output_differs` / `unavailable`. Replay is not rerun; `unavailable` is a first-class answer. |
| `state_compare_probe.py` | Step-aligned diff against a known-good run. Strong localization signal, weak attribution signal — the asymmetry that justifies scoring the two tasks separately. |

### `src/diagnosis/` — the diagnostic agent

| file | purpose |
|---|---|
| `hypothesis.py` | The taxonomy: mechanisms, the eleven families, the held-out family. Single source of truth for what may be generated versus what may be predicted — those sets differ, which is what makes H5 an escalation problem rather than a fifth label. |
| `belief.py` | Categorical belief over H1–H4 plus an explicit `unexplained` mass that drives escalation. Hand-declared likelihoods in one auditable table. Reduces evidence to a fixed signature vocabulary in two passes: `single_signatures()` for what one probe says alone, `cross_signatures()` for what only appears when two results are held against each other. |
| `policy.py` | Every policy: `b0_trivial`, `b_visible_only`, `random`, `b2_checklist`, `b2_strong` (via `search_best_fixed_order`), and `p_adaptive`. Kept in one file because each is ~40 lines and the point is to read them side by side. |
| `decision.py` | `Action`, `Episode`, and `run_episode` — the loop that owns the trace, hands out observations, charges for probes, and forces escalation at budget exhaustion. |

### `src/evaluation/`

| file | purpose |
|---|---|
| `metrics.py` | Escalation-aware attribution accuracy (primary), localization conditioned on correct attribution (secondary), crash-step confusion, escalation precision/recall, per-family breakdown, paired bootstrap. |
| `experiment_runner.py` | Builds corpora, runs policies, searches the optimal fixed order **on dev before the adaptive policy is instantiated**, computes budget curves, writes results. |

### `experiments/`, `results/`, `paper/`

| path | purpose |
|---|---|
| `experiments/build_cases.py` | Builds and verifies a corpus, emitting **two** files: the evaluator record with ground truth, and `*.agent_view.json` — exactly what the diagnostic agent receives. Diffing them is the demonstration that ground truth is hidden. |
| `experiments/validate_corpus.py` | Generates dev/test splits and checks G1–G5 for experimental corpora. |
| `experiments/run_experiment.py` | Runs the full policy comparison. |
| `results/` | Per-run `results.json` plus per-policy episode transcripts, for hand-auditing individual decisions. |
| `paper/` | Write-up. Empty until there is a result worth writing up. |

### `tests/`

`test_harness.py` enforces the feature lock, session-log integrity, dependency ordering and
the one-at-a-time policy. `test_contract.py` is not optional: it is the mechanism that keeps the frozen
contract from silently rotting. It enforces ground-truth isolation, label leakage rules,
tier agreement with the JSON schema, probe semantics, budget accounting, probe-sufficiency,
and that the two cross-evidence families never become single-probe solvable. 45 tests total.

---

## How label leakage is prevented

Leakage here means the diagnostic agent obtaining the answer without earning it. Four
independent guards, because the first three are all defeatable and one of them already was.

**First, a distinction that matters.** Leaking *evidence* into the visible tier is a design
choice — argument values are visible because real tracing UIs show them. Leaking the
*label* is a bug. `amount="45.00"` is evidence. `"policy_violation"` is a label wearing an
error message as a disguise.

### 1. Structural — ground truth is unreachable, not merely unread

`GroundTruth` hangs off `Trace`, which is owned by `run_episode`. A policy receives an
`Observation`, built only by `make_observation()`. There is no back-pointer, no trace id
lookup, no corpus handle. `test_contract.py` walks the entire object graph a policy can
touch and asserts no `GroundTruth` instance is reachable, including after every probe has
fired. Argument dicts are **copied** into headers, so a policy cannot even mutate the
corpus it is being scored against.

### 2. Declarative — visibility is data, and the data is tested

Every field in `trace_schema.json` carries `x-visibility`. `test_visible_tier_matches_schema`
asserts the Python `StepHeader` exposes exactly the fields marked `VISIBLE`, and
`test_probe_gated_fields_are_absent_from_headers` asserts the probe-gated ones are absent.
Redrawing the boundary means editing the schema, which means the diff is visible in review.

### 3. Lexical — no mechanism or family name in anything a policy can read

Rules L1 and L2 in the probe contract. A regex for mechanism ids and family ids runs over
every visible field and every probe payload across the whole corpus.

### 4. Empirical — the one that actually works

`VisibleOnlyPolicy`: hand rules over the free information, zero probes. Corpus requirement
**G5** rejects any corpus where it exceeds 0.55 attribution accuracy.

**This guard has already earned its keep.** The first version of the generator passed
guards 1–3 cleanly while writing `policy_violation`, `precondition_not_met`,
`validation_error` and `upstream_unavailable` into `final_error` — a visible field. Those
strings are not mechanism *names*, so no regex caught them, but they are one-to-one with
mechanisms. `VisibleOnlyPolicy` decoded them to **0.858** attribution accuracy with zero
probes, against a 0.25 chance floor. Every probe in the study was decorative and no
lexical check would ever have said so.

The fix was to draw surface errors from a shared, deliberately ambiguous pool
(`refund_failed`, `task_incomplete`, `tool_error`, or nothing at all), where each error is
produced by at least two mechanisms and each mechanism can produce at least two errors.
Diagnostic detail still exists — it lives in `raw_output`, behind a probe, which is exactly
what inspecting a tool output is supposed to buy you. Silent failures (no error at all)
were also added to in-taxonomy families, so "no error" is not a free detector for the
held-out H5 family. Visible-only accuracy dropped to **0.278**.

The lesson generalises: *a leakage guard that cannot fail is not a guard.* Measure what the
free information already solves, and treat that number as a corpus property.

---

## Status

| milestone | state |
|---|---|
| M0 specs frozen | done |
| M1 model, probes, episode loop, contract tests | done — 18 tests green |
| **M2 corpus generator** | **done — 11 families, G1–G7 pass, 44/44 probe-sufficient** |
| M3 B2-strong search | harness in place, needs its own evaluation pass |
| M4 adaptive policy calibration | first uncalibrated run below; **K1 currently fires** |
| M5–M8 | not started |

### First end-to-end run (diagnostic only — not the registered experiment)

400 test cases, 6-probe budget:

| policy | attribution | localization | probes | escalation |
|---|---|---|---|---|
| `b0_trivial` | 0.237 | 0.484 | 0.00 | 0.000 |
| `b_visible_only` | 0.278 | 0.588 | 0.00 | 0.195 |
| `random` | 0.225 | 0.144 | 3.00 | 0.000 |
| `b2_checklist` | 0.235 | 0.415 | 6.00 | 0.000 |
| **`b2_strong`** | **0.743** | 0.687 | 6.00 | 0.000 |
| `p_adaptive` | 0.613 | **0.833** | **2.76** | 0.000 |

**Kill criterion K1 fires: the adaptive policy loses the primary task to the best fixed
order.** It wins the secondary task decisively and uses less than half the probes, but the
pre-registered claim is about attribution and that claim currently fails.

Per the pre-registration, the response is *not* to tune `p_adaptive` until it wins. The
defect is already visible in its budget curve, which is **anti-monotone** — 0.68 at four
probes, 0.61 at six. More evidence makes it worse. That is the fingerprint of the
naive-Bayes independence assumption in `belief.py` double-counting correlated evidence, and
it is an M4 problem to be fixed on the dev split with the reason written down first.

**Pre-registration note:** this run used seeds 0/1000, which are hereby burned for
diagnostics. The registered E1 must use a fresh, previously unscored test seed. It also
predates the eleven-family taxonomy and will need re-running.

---

## The 40-case inspection corpus

`data/synthetic_cases/inspection_40.json` — stratified so all eleven families appear, and
small enough to read end to end.

| check | result |
|---|---|
| G1 root cause ≠ crash | 0.55 |
| G5 visible-only attribution | 0.425 (chance floor 0.25) |
| G6 probe-sufficient | 40/40 |
| G7 every family present | 11/11 |
| mean oracle probes | 1.22 |
| cases needing ≥ 2 probes | 8 |
| silent failures (no error raised) | 10 |

**This corpus cannot test the pre-registered hypothesis.** With five classes and eleven
families, a 10-point accuracy gap at n=40 carries a CI near ±15 points, and there are ~3.6
cases per family. It is for hand-auditing that ground truth is hidden and evidence is
reachable. Run `build_cases.py --n 400 --allocation by_mechanism` for an experimental
corpus.

### What one case looks like

Evaluator record, `case-00000`:

```json
"ground_truth": { "mechanism": "H1_planning", "family": "wrong_reasoning_decision",
                  "root_cause_step": 3, "crash_step": 6, "distractor_steps": [4] },
"_audit":       { "oracle_probes": 2,
                  "oracle_probe_set": [["inspect_context", 1], ["inspect_plan", 3]] }
```

The agent sees the same case as step headers, tool names, arguments, and
`final_error: null` — the run raised nothing and returned "Your refund has been
processed.", which is false. The fault is at step 3, three steps before the crash, behind
a distractor at step 4, and it takes exactly two probes to see: the retrieved policy says
30 days, the reflection calls a 95-day-old order eligible. Neither probe alone shows
anything wrong.

## Quick start

```bash
make install
make all              # harness check + tests + corpus gates G1-G7
make next             # what to work on
```
