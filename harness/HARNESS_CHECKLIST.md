# Harness Review Checklist

> Template: awesome-harness-engineering/templates/HARNESS_CHECKLIST.md
> A failing item is a blocker; a skipped item needs a written justification.

## Agent instructions (AGENTS.md)

- [x] Project overview is accurate and up to date
- [x] Repository structure reflects the current layout
- [x] Tool permissions are explicit — allowed, restricted, and not-allowed all specified
- [x] Verification gates are defined and commands are correct
- [x] No ambiguous instructions that could be interpreted multiple ways

AGENTS.md carries a "four things that make this repository unusual" section. Two of the
four are lessons from mistakes already made here, which is the only reason they are stated
as rules rather than assumed as common sense.

## Tool design

Tools here are the six diagnostic **probes** — the agent's action space.

- [x] Each probe has a clear, unambiguous name matching its module
- [x] Schemas are minimal: a probe takes `(trace, step_index)` and nothing else
- [x] Failure is informative — an inapplicable probe returns `ok=False` with a note saying
      why, and `replay_tool_call` distinguishes "replay disagreed" from "replay impossible"
- [x] Return values are consistent: every probe returns `Evidence`, success or failure
- [x] No probe does more than one conceptual thing
- [x] No probe returns a diagnosis, a hypothesis label, or a hint (contract rule 1)

## Context delivery

- [x] Context is scoped: a policy receives an `Observation`, never a `Trace`
- [x] Long-lived state is in files — `PLAN.md`, `IMPLEMENT.md`, `features.json`,
      `sessions/`, `research/discussion-record.md`
- [x] Compaction strategy defined: each session log ends with "Carried forward", written
      on the assumption that the next session remembers nothing
- [x] No secrets in agent-accessible context — the suite runs offline with `NullClient`

## Planning artifacts

- [x] PLAN.md exists and is current
- [x] Milestones have explicit verification commands
- [x] Scope boundaries written down, including an explicit out-of-scope list
- [x] IMPLEMENT.md captures decisions and deviations as they happen
- [x] Every feature carries acceptance criteria and a runnable verify command — enforced by
      schema, so an under-specified feature cannot be added quietly

## Permissions & sandbox

- [x] Minimum permissions: the restricted list names the five files that can invalidate a
      result if edited casually
- [x] Destructive operations gated — `harness.py done` refuses when verify fails;
      `start` refuses a second concurrent feature and unmet dependencies
- [x] Network access scoped — none required; tests are offline by construction
- [x] File system access scoped to project directories

## Verification loop

- [x] Tests exist for the agent's outputs — 23 contract tests + harness tests
- [x] The agent can run verification itself: `pytest -q`, `harness.py check`,
      `build_cases.py`. No gate is "human review"
- [x] Verification runs automatically — CI on every push (F-021)
- [x] Eval criteria written before the task starts — `research/preregistration.md`,
      dated ahead of the test split being scored

## When this harness component should be removed

> Every harness component exists because the model can't do something yet.
> Document what capability improvement would make this component unnecessary.

| Component | Exists because | Can be removed when |
|---|---|---|
| `AGENTS.md` | A fresh session has no memory of this repo's four load-bearing invariants and will break them plausibly and confidently | Models reliably infer project invariants from code and docs without being told which ones are load-bearing |
| Locked feature ledger (`features.json` + hash) | Agents silently reinterpret backlog items to match what they just built; scope drifts without anyone deciding to drift it | An agent reliably notices and flags that it is about to redefine a task rather than perform it |
| `one_at_a_time` enforcement | Agents start parallel work when blocked, producing several half-finished features and no verification | Agents reliably park blocked work with a written handoff instead of starting something new |
| Session logs | No shared memory across context windows; findings from session N are invisible in session N+1 | Durable cross-session memory exists at the model level, with the same auditability |
| `verify` command per feature | "Done" is otherwise a judgement call, and agents are optimistic about their own output | Self-assessment of completion is calibrated enough to trust without an external gate |
| `tests/test_contract.py` leakage guards | Nothing structurally prevents an agent from handing a policy the ground truth while refactoring | Never. This is an experimental validity guard, not a model-capability workaround — it stays regardless of how good models get |
| G5 visible-only baseline | Static leakage checks pass on broken corpora; only running a zero-probe baseline catches semantic leakage | Never. Same reason: it measures a property of the data, not a limitation of the agent |
| `harness.py` CLI | Ledger consistency (dependency order, status transitions, lock integrity) is tedious and therefore skipped by hand | Agents maintain structured state files without arithmetic or consistency errors — plausible soon; the schema and lock outlive the CLI |

Two rows say **never**, and the distinction matters. Most of this harness compensates for
what a model cannot yet do reliably, and should be deleted as models improve. The leakage
guards compensate for nothing — they establish that the experiment measures what it claims
to measure, and would be required even of a perfect agent.

---

*Reviewed: 2026-08-12*
*Reviewer: research engineer (session 0005)*
