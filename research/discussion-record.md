# Discussion Record

Append-only log of decisions and the reasoning behind them. Dated entries.

## 2026-08-12 — Practitioner lessons taken as design constraints

1. Whole-trace LLM diagnosis prematurely locks onto a plausible explanation → B1 baseline.
2. Good debugging is hypothesis → evidence → update → the episode loop in `decision.py`.
3. The best next evidence is not necessarily evidence for the favourite hypothesis →
   probe selection scores *separation*, not confirmation.
4. The useful probe is the one that best separates remaining hypotheses → top-2
   discrimination in `policy.py`.
5. Existing tracing and replay workflows are strong baselines → B2-strong is the optimal
   fixed order, not a strawman checklist.
6. Visible failure step ≠ first meaningful wrong step → `crash_step` and `root_cause_step`
   are separate fields; corpus requirement G1 forces them apart in ≥ 40% of cases.
7. Replay ≠ rerun → `replay_probe` returns preserved observations and can answer
   `unavailable`.
8. Localization and attribution evaluated separately → attribution primary, localization
   secondary and conditioned on correct attribution.

## 2026-08-12 — Scope decisions

- **Six families, not twelve.** Cut from an earlier 12-family draft. Twelve families with
  n=400 gives ~33 cases per family, too thin for per-family error analysis. Six families
  gives ~67 and keeps the generator auditable.
- **Attribution is primary; the blended cost scalar is demoted.** An earlier draft made
  "expected diagnostic cost" the headline. It required defending a decision-cost matrix
  (how much worse is a wrong diagnosis than a needless escalation?) that is pure
  stipulation. An accuracy-vs-budget curve makes the same efficiency point without a
  contestable weighting. Cost is retained as secondary S4.
- **Escalation-aware accuracy, not accuracy-over-diagnosed-episodes.** Excluding
  escalations from the denominator lets a policy protect its score by refusing hard cases.
- **Probe contract frozen before the generator.** `research/probe-contract.md` is dated
  earlier than `src/trace/synthesize.py`; git history is the evidence.

## 2026-08-12 — Amendment A1: visibility boundary redrawn

Tool names and arguments moved from PROBE to VISIBLE at the researcher's direction. Handled
as a dated amendment to the frozen contract rather than a silent edit, because the value of
freezing is entirely in the audit trail.

The change is right — real tracing UIs show call signatures for free — but it is not free
scientifically. It hands `arg_type_violation` partly to the visible tier, which shrinks the
headroom this project is trying to measure on H2. Two consequences accepted deliberately:

1. The experiment's contrast now rests mainly on displaced-root-cause families
   (`stale_document`, `missing_precondition`, `wrong_tool_selected`), where the open
   question is *which step* to probe. That is a sharper and more falsifiable claim than
   "adaptive beats fixed" anyway, so the amendment arguably improves the paper.
2. B1 (whole-trace LLM) gains more than the signature-based policies, since it can read
   argument values semantically. Left in place. Engineering that advantage away would be
   rigging the baseline.

Guard added: `VisibleOnlyPolicy` and kill criterion K5.

## 2026-08-12 — M2 complete; the lexical leakage guards were not enough

First corpus passed every structural and lexical leakage check and was still broken.
`VisibleOnlyPolicy` scored **0.858** attribution accuracy with zero probes against a 0.25
chance floor, because the generator wrote `policy_violation`, `precondition_not_met`,
`validation_error` and `upstream_unavailable` into `final_error`. Those are not mechanism
names, so no regex fired, but they are one-to-one with mechanisms. Every probe in the study
was decorative and nothing in guards 1–3 could have told us.

Fix: surface errors drawn from a shared ambiguous pool; diagnostic detail moved into
`raw_output`, behind a probe; silent failures added to in-taxonomy families so "no error"
stops being a free H5 detector. Visible-only fell to 0.278.

Promoted to corpus requirement **G5**, checked by `experiments/validate_corpus.py`.
Generalised lesson recorded in the README: a leakage guard that cannot fail is not a guard.

## 2026-08-12 — First end-to-end run: K1 fires

`p_adaptive` 0.613 attribution vs `b2_strong` 0.743, paired and significant against us. It
wins localization (0.833 vs 0.687) on 2.76 probes instead of 6.

Not tuning it. K1's stated remedy was "fix the probes or the corpus", but that diagnosis is
wrong here: `b2_strong` reaches 0.743 on the same probe set, so the probes discriminate
fine. The defect is in `belief.py`. Evidence: the adaptive budget curve is **anti-monotone**
(0.68 at 4 probes, 0.61 at 6) — more evidence makes it worse, which is the signature of
naive-Bayes double-counting correlated observations. `schema_valid` and `output_clean`, for
instance, are strongly dependent but multiplied as if independent.

Amend K1 at M4 to distinguish the two causes: if a fixed policy clears the adaptive policy
on the same probe set, the probe set is exonerated and the belief model is the suspect.

Also noted: `p_adaptive` escalates on 0% of cases and therefore misses all 43 held-out H5
cases. `tau_escalate` never triggers because `unexplained` only accumulates on unmodelled
signatures, and clean evidence is all modelled. Flat-posterior escalation needs to be a
first-class rule, not a budget-exhaustion fallback.

**Pre-registration hygiene:** seeds 0/1000 are burned for diagnostics. E1 must use a fresh
test seed.

## 2026-08-12 — Taxonomy revision: eleven families, wrong_tool_selected -> H1

Researcher-directed. Supersedes the "six initial families" scope decision. `wrong tool
selection` reclassified from H2 to H1: the tool was invoked correctly and behaved
correctly, so the fault is in the decision. Right call, and it makes H1/H2 confusable at
`tool_call` steps, which is harder and closer to real debugging.

Cost recorded: 11 families at n=400 is ~36 cases each. Per-family error analysis is thin
and per-family CIs will be wide. At n=40 it is ~3.6, which is an inspection corpus only.

Two families added that no single probe can see -- `wrong_reasoning_decision` and
`misunderstood_output`. These required extending the belief layer with cross-evidence
signatures computed over the whole evidence list. Belief is now rebuilt from scratch each
turn rather than updated incrementally, because cross-evidence rules make incremental
updates order-dependent, and a policy whose score depends on the order it happened to probe
in would be measuring the wrong thing.

## 2026-08-12 — G6 verifier: nearly rewrote good cases to fit a bad belief model

First probe-sufficiency verifier swept every probe over every step, fed the lot into
`Belief`, and asked whether the posterior landed on the truth. It failed 8/44 cases,
including **every** `api_failure`.

The cases were fine. The verifier was measuring the policy's belief model, which
double-counts correlated evidence: one `transport_failure` at P=0.92 for H4 was drowned by
four incidental `output_clean` observations at P=0.05 each, harvested from innocent steps a
real prober would never have visited. Acting on that reading would have meant rewriting
sound cases to accommodate a known defect.

Rewritten as subset existence: does there exist a probe set of size <= 3 whose evidence
identifies the truth? Sufficiency is a property of the evidence, not of any one reasoner.
44/44 now pass, and the search returns something better than a boolean -- `oracle_probes`,
the minimum probes per case (mean 1.22), which is a lower bound no policy can beat.

General lesson, worth a line in the paper: **never let the artefact under test judge the
data it is tested on.**

## 2026-08-12 — Harness installed; feature list locked (session 0005)

Adopted the four templates from awesome-harness-engineering (AGENTS.md, PLAN.md,
IMPLEMENT.md, HARNESS_CHECKLIST.md), cloned rather than inferred. Added a hash-locked
feature ledger, per-session logs, a CLI, and a CI gate.

The lock covers only the fields that define what a feature *is* — id, area, title, why,
depends_on, acceptance, verify, milestone. Status and session references stay mutable.
Rejected locking the whole file: every status update would demand a version bump, and a
lock that fires constantly gets ignored within a day.

The schema refuses under-specified features: fewer than two acceptance criteria, a `why`
under 40 characters, or a missing `verify` command all fail validation. A feature nobody can
check is a wish.

Sessions 0001-0004 were retro-logged rather than starting the record at installation. Two of
them produced findings — the 0.858 visible-only leak and the verifier that condemned sound
cases — that would otherwise exist nowhere. Marked as reconstructed, not contemporaneous.

The checklist's "when can this component be removed" table was filled in honestly. Two rows
say **never**: the leakage guards and the visible-only baseline compensate for nothing about
model capability. They establish that the experiment measures what it claims to measure, and
would be required of a perfect agent. Everything else in the harness is scaffolding that
should be deleted as models improve. That distinction is worth a paragraph in the paper.

## 2026-08-12 — B1 built; two decisions worth defending (session 0006)

**The formatter's input type is the leakage proof.** `format_trace(..., VISIBLE)` accepts an
`Observation` and raises `TypeError` on a `Trace`. Since `make_observation()` is already
proven unable to reach a `GroundTruth`, B1 inherits that proof rather than restating it. A
second test scans `src/baselines/` for any import from `src/probes/`. "Must not use probes"
is now a structural fact, not a convention someone will forget.

**Two input views, because the spec and the pre-registration disagreed.** The
pre-registration said B1 gets the fully unredacted trace; the researcher specified the
visible tier only. Implemented both, defaulted to VISIBLE, recorded as amendment P1. VISIBLE
is the matched-information ablation and is what PH1 compares against; FULL is the faithful
strawman. Picking one quietly would have decided a question the experiment exists to answer.

**Hallucination gets an exact detector.** Under VISIBLE the model provably never saw raw
outputs, HTTP codes, documents, plan text or replay records — so an explanation containing
one of those literals is invented by construction, with no LLM-as-judge and no judgement
call. Reported separately from the heuristic phrasing-based measure, which is labelled as
heuristic everywhere it appears.

**Deliberately not optimised, and the code enforces it.** Zero repair attempts by default —
retrying until the JSON parses would convert a failure mode into a success. Parse failure is
a reported metric and scores as incorrect attribution. Unrecognised mechanism strings are
*not* mapped onto the nearest class, because that would manufacture accuracy the model did
not earn.

**One thing that looks like helping the baseline but is not.** The prompt tells the model
which fields are withheld. Concealing the redaction would push it toward overconfidence,
which would flatter our own hypothesis. Telling it is the conservative choice.

## Open questions

- Does "six initial failure families" mean six *families* (taken here) or six *mechanism
  classes*? Taken as families. Changing it is a `hypothesis.py` enum entry plus templates.
- Probe prices are stipulated. Sensitivity sweep required before publication.
- The discrimination prior in `policy.py` is authored knowledge and is a circularity
  vector. The v0 claim is narrowed to "a cheap authored discrimination prior beats the
  best fixed order", not "adaptivity emerges".
