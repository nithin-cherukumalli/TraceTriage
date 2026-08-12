# Session 0006 — Baseline 1: whole-trace LLM diagnosis

*Date: 2026-08-12*
*Feature: F-017*

## Goal

Implement B1, the approach practitioners criticise — hand the failed trace to an LLM and ask
what went wrong — as a comparison point that is deliberately **not** optimised, and measure
the four things that matter about it: attribution, localization, evidence grounding, and
calibration.

## Starting state

45 tests green, ledger v1, 9 features done. F-017 sat behind F-015 in the dependency graph.

## Log

### 2026-08-12 — Ledger amended rather than bypassed

**What happened:** The researcher reprioritised B1 ahead of F-010..F-016, which the harness
had just been built to prevent. It also extended B1's acceptance with three measures not in
the original feature.

**Decision:** Amended through the mechanism instead of around it. `lock_version` 1 → 2, with
a changelog entry covering both changes. On inspection F-017's dependency on F-015 was
**over-specified by me** — B1 needs the data model (F-002) and the metrics layer (F-005),
both done; F-015 *consumes* B1's output rather than producing anything B1 needs. That was a
genuine error in the original ledger, corrected on the record rather than quietly.

The harness is meant to make changes visible and deliberate, not to overrule the researcher.
A lock that cannot be amended is a lock that gets deleted.

### 2026-08-12 — The formatter's input type is the leakage proof

**Decision:** `format_trace(..., VISIBLE)` accepts an `Observation` and raises `TypeError`
on a `Trace`. `make_observation()` is already proven unable to reach a `GroundTruth`
(session 0002), so B1 inherits that proof rather than restating it. A separate test AST-scans
`src/baselines/` for any import from `src/probes/`, so "must not use diagnostic probes" is a
structural fact rather than a convention someone forgets in six sessions.

### 2026-08-12 — The spec contradicted the pre-registration

**What happened:** `research/preregistration.md` defines B1 as receiving the fully unredacted
trace. The researcher specified the visible tier only.

**Decision:** Implemented both as a `TraceView` enum, defaulted to VISIBLE, recorded as
pre-registration amendment P1. They measure different things and only one had been written
down. VISIBLE is the matched-information ablation — B1 and the probing policies start from
identical input, so the only difference is whether you can pay to see more. FULL is the
faithful reproduction of the practice under criticism, where people paste the whole log.
PH1 compares against VISIBLE; FULL is reported alongside; **K4 fires if either wins.**

**Deviation from plan:** P1 is the second amendment to a frozen document this project has
needed. Both were researcher-directed and both are dated.

### 2026-08-12 — Hallucination gets an exact detector

**Decision:** Under VISIBLE the model provably never saw raw outputs, HTTP codes, retrieved
documents, plan text or replay records. So an explanation containing one of those literal
values is invention **by construction** — no LLM-as-judge, no judgement call. Reported as
`unsupported_by_value` (airtight) separately from `unsupported_by_category` (heuristic over
assertive phrasing, hedges excluded, labelled as heuristic everywhere it appears). Merging
them into one number would launder a heuristic as a measurement.

### 2026-08-12 — Choices that deliberately do not flatter the baseline

- **Zero repair attempts.** Retrying until the JSON parses converts a failure mode into a
  success. Parse failure is a reported metric and scores as incorrect attribution.
  `max_repair_attempts` exists and defaults to 0 so the effect of repair can be *measured*
  rather than assumed.
- **No fuzzy mechanism matching.** An unrecognised mechanism string is a parse failure, not
  a nearest-neighbour guess. Guessing would manufacture accuracy the model did not earn.
- **The prompt says what is withheld.** This looks like helping B1 but cuts the other way:
  concealing the redaction would push it toward overconfidence, which flatters our own
  hypothesis.
- **One prompt version, temperature 0, no dev iteration.** Recorded in every result row.

### 2026-08-12 — Mock client reproduces the behaviour under study

**What happened:** The offline mock is a keyword heuristic over the visible tier that blames
the last visible step. Run over 40 cases it produces attribution 0.350, confidence 0.699,
overconfidence +0.349, and **crash-step confusion 0.643**.

**Decision:** Keep it. That is the practitioner complaint reproduced by a deliberately
shallow reader — confident, plausible, and wrong about *where* two-thirds of the time — which
demonstrates the metric pipeline measures the right thing before a single API call is spent.
It is not evidence about real LLMs and must never be reported as such.

**Next:** F-010 — regenerate the corpora under the eleven-family taxonomy. Then a real
provider run of B1 on three seeds.

## Verification run

```
$ pytest tests/test_baselines.py -q && python experiments/run_baseline_b1.py --client mock
```

Result: 49 baseline tests pass, 94 total. B1 runs end to end under both views.

| view | attribution | localization | crash-step confusion | overconfidence | ECE |
|---|---|---|---|---|---|
| VISIBLE | 0.350 | 0.357 | 0.643 | +0.349 | 0.349 |
| FULL | 0.425 | 0.471 | 0.529 | +0.274 | 0.274 |

Mock client only. Not a result about LLMs.

## Outcome

- [x] Feature acceptance met
- [x] Verify command exits 0
- [x] Ledger updated (v2)
- [x] `research/discussion-record.md` and `research/preregistration.md` (amendment P1) updated

## Carried forward

B1 is built but **unrun against a real model**. Every number above is the mock and must be
labelled as such in any write-up.

Three things the next session must not undo: zero repair attempts, no fuzzy mechanism
matching, and the `Observation`-typed formatter signature. Each is load-bearing and each
looks like an inconvenience from the inside.

The real-provider run needs three seeds with variance reported, and belongs after F-010 —
scoring B1 on corpora that predate the taxonomy revision would waste the API spend.
