# Session 0003 — Case generator, and a leak that every static check missed

*Date: 2026-08-12*
*Feature: F-005, F-006, F-008*

> Retro-logged during session 0005.

## Goal

Build the synthetic case generator and run the pipeline end to end for the first time.

## Starting state

18 tests green. Model, probes and episode loop complete. No corpus.

## Log

### 2026-08-12 — The corpus was broken and every static guard passed

**What happened:** First end-to-end run. `VisibleOnlyPolicy` — zero probes, hand rules over
the free information — scored **0.858** attribution accuracy against a 0.25 chance floor.

**Decision:** Root cause: the generator wrote `policy_violation`, `precondition_not_met`,
`validation_error` and `upstream_unavailable` into `final_error`, a visible field. Those are
not mechanism *names*, so the regex leakage check passed cleanly, but they are one-to-one
with mechanisms. Every probe in the study was decorative and no lexical check would ever
have said so.

Fixed by drawing surface errors from a shared ambiguous pool where each error is produced by
at least two mechanisms; diagnostic detail moved into `raw_output`, behind a probe — which
is exactly what inspecting a tool output is supposed to buy you. Silent failures added to
in-taxonomy families so "no error" stops being a free H5 detector. Visible-only fell to
**0.278**.

Promoted to corpus requirement **G5** and kill criterion **K5**.

**Deviation from plan:** None, but the lesson generalises and was written into the README:
*a leakage guard that cannot fail is not a guard.* Measure what the free information already
solves, and treat that number as a property of the corpus.

### 2026-08-12 — K1 fires on the first comparison

**What happened:** `p_adaptive` 0.613 attribution vs `b2_strong` 0.743, paired and
significant against us. Adaptive wins localization (0.833 vs 0.687) on 2.76 probes vs 6.

**Decision:** Not tuning. K1's stated remedy is "fix the probes", but that diagnosis is
wrong here: `b2_strong` reaches 0.743 on the same probe set, which exonerates the probes.
The defect is in `belief.py`, and its fingerprint is the **anti-monotone budget curve** —
0.68 at four probes, 0.61 at six. More evidence makes it worse, the signature of
naive-Bayes double-counting correlated observations.

**Next:** Fix the belief update on dev, with the reason written down first.

## Verification run

```
$ python experiments/validate_corpus.py
```

Result: ACCEPTED. G1–G5 pass on both splits; visible-only 0.278.

## Outcome

- [x] Generator built, corpus validated
- [x] Empirical leakage guard added and immediately justified
- [x] K1 recorded, not tuned around

## Carried forward

Seeds 0 and 1000 are **burned** — they have been used for diagnostics and must never be
used for the pre-registered experiment.
