# Probe Contract — FROZEN

**Frozen 2026-08-12, before any line of `src/trace/synthesize.py` was written.**

This ordering is the point. If probe semantics were authored after the case generator,
the adaptive policy would be reading its author's mind and the result would be circular.
This file is write-once. Changes require a dated amendment below and a re-run of every
affected experiment.

## Closed probe set (v0)

| module | id | target | reveals | cost |
|---|---|---|---|---|
| `plan_probe` | `inspect_plan` | step (`plan`, `reflect`) | `plan_text` | 1.0 |
| `schema_probe` | `validate_tool_args` | step (`tool_call`) | `schema`, `schema_valid`, `violations` | 1.0 |
| `tool_output_probe` | `inspect_tool_output` | step (`tool_call`) | `raw_output`, `status`, `http_status`, `latency_ms` | 1.5 |
| `context_probe` | `inspect_context` | step (`retrieval`) | `query`, `documents`, `scores` | 2.0 |
| `state_compare_probe` | `compare_known_good` | trace | `first_divergent_step`, `aligned_diff` | 3.0 |
| `replay_probe` | `replay_tool_call` | step (`tool_call`) | `replay_record`, `divergence` | 4.0 |

Costs are ordinal stand-ins for analyst time, frozen before any policy is tuned. A
sensitivity sweep (±50% per probe) is required before publication; if the policy ranking
flips, the result is a cost-model artefact and must be reported as such.

## Semantics

1. A probe is **read-only unredaction** of a stored trace. It never mutates the trace and
   never returns a diagnosis, a hypothesis label, or a hint.
2. An inapplicable probe returns `ok=False` and is **still charged in full**. Wasted
   probes must hurt, or probe count stops measuring anything.
3. `replay_tool_call` returns **preserved external observations**, not a live re-execution.
   Verdict ∈ `{none, output_differs, unavailable}`. `unavailable` is the honest answer when
   the trace carries no preserved observation. This is how replay-vs-rerun becomes
   measurable rather than assumed.
4. `compare_known_good` requires a reference trace for the same task. Absent one it returns
   `ok=False` at full cost.

## Evidence object

```
Evidence(probe_id, step_index, ok: bool, payload: dict, note: str)
```
`payload` carries only the fields listed under `reveals`.

## Leakage rules (enforced by `tests/test_contract.py`)

- **L1** No `payload` value may contain a mechanism label (`H1`–`H5`) or a family id.
- **L2** `Step.summary` — always visible — is generated from `kind` and surface arguments
  only. The generator may not write mechanism-revealing prose into it.
- **L3** An `Observation` object graph must not reach a `GroundTruth` instance. The test
  walks the graph and asserts this.

## Visibility tiers

Authoritative machine-readable version: `schemas/trace_schema.json`, field `x-visibility`.

**VISIBLE (free at episode start)** — task; step index, kind and one-line summary; tool
names; tool arguments; final result; final error if present; whether a reference trace
exists.

**PROBE (costed)** — tool schema and validation verdict; raw tool outputs, status, HTTP
code, latency; retrieval query, documents and scores; plan and reflection text; state
differences against a known-good run; replay results.

**HIDDEN (evaluator only)** — true failure mechanism; true failure step; fault family;
crash step; in-taxonomy flag; distractor step list.

## Amendments

### A1 — 2026-08-12 — tool names and arguments move to the VISIBLE tier

**Change.** `tool_call.name` and `tool_call.arguments` were PROBE-gated behind
`validate_tool_args`; they are now VISIBLE. `validate_tool_args` now reveals the declared
`schema` and the validation verdict instead.

**Rationale.** Every real tracing UI shows the call signature for free. Charging for it
modelled a cost that does not exist, and made the baseline unrealistically blind.

**Consequence, recorded honestly.** This *weakens* the experiment on H2. The
`arg_type_violation` family is now partially detectable from the visible tier alone: a
reader who sees `amount="45.00"` may guess a type violation without paying for the schema.
Expected effects:

- headroom for adaptive probing shrinks on H2;
- the contrast between adaptive and fixed policies now rests mainly on the families whose
  root cause is displaced from the crash — `stale_document`, `missing_precondition`,
  `wrong_tool_selected` — where the question is *which step* to probe, not which probe;
- an LLM baseline (B1) benefits more than the signature-based policies, since it can
  read argument values semantically. This is a real advantage for B1 and must not be
  engineered away.

**New guard.** Kill criterion **K5** and a `VisibleOnlyPolicy` baseline: measure
attribution accuracy using the visible tier and zero probes. If K5 fires the visible tier
is doing the work and the probes are decorative.

**Status.** No experiments had been run under the pre-amendment contract, so nothing
requires re-running.
