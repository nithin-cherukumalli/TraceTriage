# Pre-registration

Written before the test split is touched. Amendments must be dated.

## Primary hypothesis

**PH1.** At a matched probe budget of 6, adaptive discriminative probe selection (P)
attains higher **escalation-aware attribution accuracy** than the strongest fixed
procedure (B2-strong) on the held-out test split.

```
attribution_correct(episode) =
    (diagnosed_mechanism == true_mechanism)                  # in-taxonomy hit
 or (escalated and not true_family.in_taxonomy)              # correct refusal
```

Escalating on a diagnosable trace is incorrect. There is no free refusal.

## Secondary

- **S1 localization** — exact match on `root_cause_step`, computed **only over correctly
  attributed in-taxonomy episodes**. Also reported at ±1 tolerance.
- **S2 crash-step confusion** — rate at which a policy localizes to `crash_step` when it
  differs from `root_cause_step`. This is the lesson-6 diagnostic.
- **S3 efficiency** — attribution accuracy as a function of probe budget b ∈ {1..6}. This
  replaces a single blended cost scalar: a curve cannot be gamed by reweighting terms.
- **S4 probe cost** — mean charged cost to decision (contract prices).
- **S5 escalation** — precision and recall against out-of-taxonomy ground truth.
- **S6 unknown handling** — detection rate on the held-out `silent_state_corruption` family.

## Baselines

- **B0-trivial** — modal mechanism, localize to the crash step, zero probes. Sanity floor.
- **B-visible-only** — hand rules over the VISIBLE tier (tool names, arguments, final
  error), zero probes. Measures how much of the task the free information already solves.
  Added after contract amendment A1 made arguments visible.
- **B1-whole-trace** — one LLM call, no probing. Run under **two input views** (amendment
  P1): `VISIBLE`, the same tier the probing policies start from, and `FULL`, the fully
  unredacted trace. Both reported.
- **B2-checklist** — fixed probe order taken from published debugging workflow, frozen.
- **B2-strong** — the *optimal fixed probe order*, searched on the dev split. **This is the
  baseline that matters.** Built before P, so the adaptive number is never seen first.

## Statistics

Paired over case ids. 10,000-resample bootstrap on the paired difference in attribution
accuracy; report mean and 95% CI. n ≥ 400 test cases. No claim from a CI crossing zero.

## Kill criteria

- **K1** B2-strong's CI overlaps P's → the probe set is insufficiently discriminative.
  Fix the probes or the corpus. Do **not** add policy machinery.
- **K2** B0-trivial exceeds 0.40 attribution accuracy → mechanism prior is skewed.
- **K3** Localizing to `crash_step` scores > 0.90 against `root_cause_step` → corpus
  violates G1 and is invalid.
- **K4** B1-whole-trace beats P → probing does not pay at this trace length. Report it.
  Do not tune P until it wins.
- **K5** B-visible-only exceeds 0.55 attribution accuracy → the visible tier is doing the
  work and the probes are decorative. Introduced by amendment A1, which moved tool
  arguments into the visible tier. Response is to re-tier, not to add policy machinery.

## Corpus requirements (checked by `experiments/validate_corpus.py`)

- **G1** `root_cause_step != crash_step` in ≥ 40% of cases
- **G2** per-mechanism prior within [0.20, 0.30]
- **G3** ≥ 1 distractor step between root cause and crash in ≥ 50% of displaced cases
- **G4** held-out family absent from dev, present in test only
- **G5** visible-only attribution accuracy < 0.55 (see K5)
- **G6** **probe-sufficiency** -- every in-taxonomy case is solvable by some probe set of
  size <= 3, verified by subset search rather than by running the policy's belief model;
  every held-out case yields no anomalous signature under a full probe sweep
- **G7** every family represented (stratified corpora only)

**Oracle probe count.** G6's subset search returns the minimum probes needed per case. Its
mean is a lower bound no policy can beat and the correct yardstick for probe economy: on
the current corpus it is **1.22**, with cross-evidence families at exactly 2.


---

## Amendment P1 — 2026-08-12 — B1 input tier

**Change.** B1 was specified as receiving the fully unredacted trace. It is now run under
two views: `VISIBLE` (task, step headers, tool names, tool arguments, final outcome — the
tier the probing policies start from) and `FULL` (everything a probe could reveal).

**Why both.** They answer different questions and only one of them was ever stated.
`VISIBLE` is the fair-information ablation: B1 and the probing policies begin from identical
input, so the only difference is whether you can pay to see more. That isolates the
contribution exactly. `FULL` is the faithful reproduction of the practice under criticism —
practitioners paste the whole log, tool outputs included. Reporting only `VISIBLE` would
understate the strawman; reporting only `FULL` would confound information access with
policy. Choosing one silently would decide a question the experiment exists to answer.

**Consequence.** PH1's comparison is against `b1_whole_trace@VISIBLE`, since that is the
matched-information contrast. `FULL` is reported alongside as the practitioner-strawman
reference. **K4 fires if either beats the adaptive policy.**

**Additional measures registered with B1** (not previously in the secondary list):

- **S7 evidence grounding** — fraction of cited `step_id`s that exist in the trace.
- **S8 unsupported explanation rate** — reported in two parts. `unsupported_by_value` is
  exact: under `VISIBLE` the model never saw raw outputs, HTTP codes, retrieved documents,
  plan text or replay records, so an explanation containing one of those literals is
  invention by construction. `unsupported_by_category` is a labelled heuristic over
  assertive phrasing, hedges excluded. The two are never merged without saying so.
- **S9 calibration** — ECE, Brier, accuracy per confidence decile, and
  `high_confidence_error_rate` (confidence ≥ 0.8 and wrong), which is the direct measurement
  of the "plausible but incorrect" complaint.
- **S10 parse failure rate** — malformed or unusable model output, never retried away.

**Registered in advance:** B1 is not to be optimised. One prompt version, temperature 0,
zero repair attempts, no dev-set iteration. If the prompt ever changes it gets a new version
id and both versions are reported.
