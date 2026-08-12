# Problem Formulation

## Research question

When an AI agent fails and multiple failure mechanisms are possible, can an adaptive
diagnostic agent choose better evidence-gathering actions than fixed debugging procedures?

## Formal statement

A **diagnostic episode** is a sequential decision problem under partial observability:

- **Hidden state** `z = (mechanism, family, root_cause_step)`
- **Observation** `o_t` = redacted trace (step headers + final error) + evidence collected so far
- **Actions** `a_t ∈ {probe(p, step)} ∪ {diagnose(mechanism, step)} ∪ {escalate}`
- **Budget** at most 6 probes per episode
- **Objective** maximise attribution accuracy at a given probe budget

The agent never sees the trace body until it pays for it. This is what makes probe
selection a decision rather than a formatting choice.

## Task hierarchy (constraint: attribution primary, localization secondary)

**Primary task — attribution.** Name the failure mechanism, or escalate. Scored
escalation-aware: an episode is correct if the diagnosed mechanism matches the truth,
*or* the policy escalated and the truth is out of taxonomy. Escalating on a diagnosable
trace counts as incorrect. This closes the loophole where a policy escalates on hard
cases to protect its accuracy.

**Secondary task — localization.** Identify the **first meaningful wrong step**
(`root_cause_step`), not the step where the failure surfaced (`crash_step`). Scored only
on episodes that attributed correctly, so a lucky localization on a wrong mechanism earns
nothing. Reported separately, never folded into the primary number.

## Taxonomy

| id | mechanism |
|---|---|
| H1 | Planning / reasoning failure — wrong plan or decision given correct inputs |
| H2 | Tool interaction failure — misuse of a correctly functioning tool |
| H3 | Context / retrieval failure — wrong, missing, stale or truncated evidence |
| H4 | External / system failure — the tool or environment itself failed |
| H5 | Out-of-taxonomy — none of the above; reachable only by escalation |

`H5` is never a predicted class. It is detected by exclusion, and is realised in the
corpus by **held-out families that appear only in the test split**.

## Eleven failure families (taxonomy revision 2026-08-12)

| family | mechanism | root cause | crash | probes needed |
|---|---|---|---|---|
| `wrong_tool_selected` | H1 | a schema-valid call to a tool that cannot serve the subgoal | later step | 1 |
| `wrong_reasoning_decision` | H1 | correct evidence read, wrong conclusion drawn | later step | **2** |
| `incorrect_routing` | H1 | request routed into a workflow that does not match the task | later step | 1 |
| `malformed_arguments` | H2 | argument value violates the declared type | same step | 1 |
| `schema_mismatch` | H2 | required field absent, unrecognised field supplied | same step | 1 |
| `misunderstood_output` | H2 | healthy 200 response misread by the agent | later step | **2** |
| `missing_context` | H3 | retrieval returns nothing usable | later step | 1 |
| `wrong_retrieved_information` | H3 | retrieval returns a superseded document | later step | 1 |
| `api_failure` | H4 | backing service returns a server error on valid input | same step | 1 |
| `service_unavailable` | H4 | service times out after elevated latency | same step | 1 |
| `silent_state_corruption` | H5 | unlogged agent state; no step is individually wrong | — | **held out** |

`wrong_tool_selected` moved H2 -> H1: selecting the wrong tool is a decision error, and the
tool that was called behaved perfectly. Consequence accepted deliberately -- H1 and H2 now
both surface at `tool_call` steps and are genuinely confusable.

**Cross-evidence families.** `wrong_reasoning_decision` and `misunderstood_output` are
invisible to every single probe: schema valid, output clean, plan sound in isolation. They
only appear when plan text is held against retrieved context or against a tool response.
They are the strongest argument in the project for sequential evidence gathering over
one-shot reading, and `tests/test_contract.py` fails if either becomes single-probe
solvable.

## Why this family set is not trivially separable

Each probe carries a distinct discriminative role, and no single probe resolves the set:

- `schema_probe` separates `arg_type_violation` from every other family
- `tool_output_probe` separates `upstream_error` (transport failure) from semantic failures
- `context_probe` separates `stale_document` from H1/H2
- `plan_probe` separates H1 from `wrong_tool_selected` (plan correct, execution wrong)
- `replay_probe` separates nondeterministic H4 from deterministic failures
- `state_compare_probe` yields a first-divergence signal, weakly informative everywhere

**Where adaptivity is expected to pay is step targeting, not probe type.** For
`stale_document` and `missing_precondition` the root cause sits several steps before the
crash, behind distractor steps. A fixed procedure must guess where to point each probe;
an adaptive one can follow the evidence backwards. State this claim explicitly in the
paper — it is sharper and more falsifiable than "adaptive beats fixed".
