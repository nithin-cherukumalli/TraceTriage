# IMPLEMENT.md

> Implementation log. Decisions, deviations from the plan, and open questions that arose
> during execution. **Append-only — do not edit past entries.**
> Template: awesome-harness-engineering/templates/IMPLEMENT.md

## Task reference

See `harness/PLAN.md`. Per-feature detail lives in `harness/features.json`; per-session
narrative lives in `harness/sessions/`. This file holds the cross-cutting decisions that
belong to the implementation rather than to any one feature.

---

## Log

### 2026-08-12 — Harness scaffolding (F-009)

**What happened:** Set up the harness per awesome-harness-engineering: `AGENTS.md` at root
(with `CLAUDE.md` symlinked to it), `harness/PLAN.md`, this file, a filled
`HARNESS_CHECKLIST.md`, a locked feature ledger, per-session logs, and a `harness.py` CLI.
Retro-logged sessions 0001–0004 so the record starts at the beginning rather than at the
point the harness was installed.

**Decision:** The feature ledger is **hash-locked** over the fields that define what a
feature is — `id`, `area`, `title`, `why`, `depends_on`, `acceptance`, `verify`,
`milestone`. Status and session references stay mutable so ordinary progress does not churn
the hash. Rejected: locking the whole file (every status update would demand a version
bump, and the lock would be ignored within a day). Rejected: no lock at all (a backlog that
can be edited silently is not a plan).

**Decision:** `one_at_a_time` is enforced by the CLI, not merely stated. `start` refuses
while another feature is in progress, and refuses if a dependency is unfinished.

**Deviation from plan:** The harness was not in PLAN.md's original milestone list. Added as
H1a/H1b. Justification: the project already spans multiple sessions with no shared memory,
and two of the four sessions so far produced findings that would have been lost without a
written record.

**Next:** F-021 (CI gate), then F-010 — regenerate the corpora under the eleven-family
taxonomy, since every downstream number is currently stale.

---

<!-- Add new entries above this line. Oldest entries at the bottom. -->

## Deviations summary

| Deviation | Reason | Plan updated? |
|---|---|---|
| Six families → eleven | Researcher-directed taxonomy revision; `wrong tool selection` is a decision error, not an interaction error | yes — `research/problem.md`, `hypothesis.py` |
| Blended cost scalar → attribution-primary | Cost matrix was pure stipulation and needed defending; an accuracy-vs-budget curve makes the efficiency point without a contestable weighting | yes — `research/preregistration.md` |
| Tool arguments PROBE → VISIBLE | Amendment A1; real tracing UIs show call signatures for free | yes — contract amendment + K5 guard |
| G6 verifier: posterior → subset existence | First version used the policy's own belief model to judge the corpus and condemned eight sound cases | yes — `src/trace/verify.py` rewritten |
| Harness milestones added (H1a/H1b) | Multi-session work with no shared memory; findings were being lost | yes — `harness/PLAN.md` |

## Open questions (unresolved)

- [ ] Does F-011 need a factored belief, or is a flat categorical salvageable? — resolve
      empirically on dev, write the answer before implementing
- [ ] Is one held-out family enough to support an "unknown handling" claim? — F-018
- [ ] Does `state_compare_probe` earn its 3.0 price? — F-016 sensitivity sweep
- [ ] Should escalation carry an explicit cost now that attribution is primary? — revisit
      if escalation rates spike after F-012

## Open questions (resolved)

| Question | Answer | Date |
|---|---|---|
| Six families or six mechanism classes? | Families. Superseded anyway by the eleven-family revision. | 2026-08-12 |
| Are lexical leakage checks sufficient? | No. They passed while a zero-probe baseline scored 0.858. Empirical guard (G5) added. | 2026-08-12 |
| Does K1's stated remedy ("fix the probes") apply to the current failure? | No. `b2_strong` reaches 0.743 on the same probe set, which exonerates the probes. The belief model is the suspect. | 2026-08-12 |
| Can the corpus verifier reuse the policy's belief model? | No — never let the artefact under test judge the data it is tested on. | 2026-08-12 |
