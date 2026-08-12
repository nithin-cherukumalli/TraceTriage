# Session 0005 — Harness scaffolding and the locked feature ledger

*Date: 2026-08-12*
*Feature: F-009*

## Goal

Install a harness per [awesome-harness-engineering](https://github.com/ai-boost/awesome-harness-engineering)
so that work across sessions is durable, and lock the feature list so the backlog cannot
drift silently.

## Starting state

23 tests green. Eleven-family generator complete, corpus verified, K1 outstanding, no
cross-session memory of any kind. Four sessions of work existed only in chat history.

## Log

### 2026-08-12 — Templates read from source, not guessed

**What happened:** Cloned the upstream repo rather than inferring its conventions. It ships
four templates: `AGENTS.md`, `PLAN.md`, `IMPLEMENT.md`, `HARNESS_CHECKLIST.md`, with
`CLAUDE.md` as a symlink to `AGENTS.md`. All four adopted, filled with real content rather
than left as placeholders.

**Decision:** The feature ledger is **hash-locked** over the fields that define what a
feature is — `id`, `area`, `title`, `why`, `depends_on`, `acceptance`, `verify`,
`milestone`. Status and session references stay mutable so ordinary progress does not churn
the hash. Rejected locking the whole file: every status update would demand a version bump,
and a lock that fires constantly gets ignored within a day.

**Decision:** The schema refuses under-specified features. Fewer than two acceptance
criteria, a `why` under 40 characters, or a missing `verify` command all fail validation. A
feature nobody can check is a wish, and wishes do not belong in a ledger.

**Decision:** Retro-logged sessions 0001–0004 rather than starting the record at the point
the harness was installed. Two of those four sessions produced findings — the 0.858
visible-only leak and the verifier that condemned sound cases — that would otherwise exist
nowhere. Each is marked as reconstructed rather than contemporaneous.

**Decision:** Filled the checklist's "when can this component be removed" table honestly.
Two rows say **never**: the leakage guards and the visible-only baseline compensate for
nothing about model capability — they establish that the experiment measures what it claims
to, and would be required even of a perfect agent. The rest of the harness is scaffolding
that should be deleted as models improve.

**Deviation from plan:** The harness was not in the original milestone list. Added as
H1a/H1b, justified by the fact that the project already spans multiple sessions with no
shared memory.

**Next:** F-021 (CI gate), then F-010 — regenerate the corpora under the eleven-family
taxonomy. Every downstream number is stale until that happens.

## Verification run

```
$ python scripts/harness.py check && pytest -q
```

Result: OK — v1, 22 features, 8 done / 1 in progress / 13 locked. Tests green.

## Outcome

- [x] Feature acceptance met
- [x] Verify command exits 0
- [x] Ledger updated
- [x] `research/discussion-record.md` updated

## Carried forward

Run `python scripts/harness.py next` at the start of every session. It answers "what am I
doing" from disk, which is the only place that answer survives.

The ledger's dependency graph makes the ordering non-negotiable: **F-010 gates everything
downstream**, because the only end-to-end run predates the taxonomy revision and used seeds
that are now burned.
