# Session 0002 — Restructure to agent-diagnosis; freeze the probe contract

*Date: 2026-08-12*
*Feature: F-001, F-002, F-003, F-004*

> Retro-logged during session 0005.

## Goal

Rebuild under the researcher's specified directory structure, apply four constraints
(six families, attribution primary, localization secondary, contract frozen before the
generator), and implement the model, probes and episode loop.

## Starting state

`adiag/` scaffold from session 0001, 17 tests green. Superseded by this session.

## Log

### 2026-08-12 — Metric hierarchy inverted

**What happened:** The constraint "attribution primary, localization secondary" invalidated
the previous headline metric, a blended "expected diagnostic cost".

**Decision:** Primary is now **escalation-aware attribution accuracy** — correct if the
mechanism matches, or if the policy escalated and the truth is out of taxonomy. Escalating
on a diagnosable case counts as incorrect, which closes the loophole where a policy
protects its score by refusing hard cases. Localization is conditioned on correct
attribution. Efficiency is an accuracy-vs-budget curve.

Rejected the blended scalar because it required defending a stipulated decision-cost matrix
(how much worse is a wrong diagnosis than a needless escalation?). A curve makes the same
point without a contestable weighting.

### 2026-08-12 — Amendment A1, mid-session

**What happened:** The researcher redrew the visibility boundary: tool names and arguments
move from probe-gated to visible.

**Decision:** Handled as a **dated amendment** to the frozen contract, not a silent edit —
the value of freezing is entirely in the audit trail. Consequence recorded honestly: this
partly hands `arg_type_violation` to the visible tier and shrinks the headroom on H2. The
contrast now rests on displaced-root-cause families where the open question is *which step*
to probe. Guard added: `VisibleOnlyPolicy` and kill criterion K5.

**Deviation from plan:** Directory structure changed to the researcher's specification.
Two files added beyond it — `synthesize.py` (the generator needs a home) and
`test_contract.py` (the mechanism that keeps the frozen contract from rotting).

**Next:** Build the case generator.

## Verification run

```
$ pytest -q
```

Result: 18 passed.

## Outcome

- [x] Contract frozen and amended on the record
- [x] Ground-truth isolation enforced by object-graph walk
- [x] Episode loop charges inapplicable probes and forces escalation at budget exhaustion

## Carried forward

Amendment A1 means B1 (the LLM baseline) benefits more than the signature-based policies,
since it can read argument values semantically. That advantage is real and must not be
engineered away.
