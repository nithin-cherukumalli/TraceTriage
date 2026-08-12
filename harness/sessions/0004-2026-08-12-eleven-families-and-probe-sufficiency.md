# Session 0004 — Eleven families, cross-evidence cases, probe-sufficiency

*Date: 2026-08-12*
*Feature: F-006, F-007, F-008*

> Retro-logged during session 0005.

## Goal

Rebuild the generator against the researcher's expanded taxonomy, and enforce the
requirement that every case contain evidence reachable through probes.

## Starting state

23 tests green. Six-family corpus, G1–G5 passing, K1 outstanding.

## Log

### 2026-08-12 — Taxonomy revised; two families made deliberately invisible

**What happened:** Researcher supplied eleven families across H1–H5, moving
`wrong tool selection` from H2 to H1.

**Decision:** Reclassification accepted — the tool was invoked correctly and behaved
correctly, so the fault is in the decision. It also makes H1 and H2 both surface at
`tool_call` steps and genuinely confusable, which is harder and closer to real debugging.
Cost recorded: eleven families at n=400 is ~36 cases each, so per-family CIs will be wide.

Two families were built to be invisible to any single probe — `wrong_reasoning_decision`
(correct policy retrieved, wrong conclusion drawn) and `misunderstood_output` (healthy 200
response misread). Both show schema-valid, output-clean, plan-sound in isolation. This
required extending the belief layer with **cross-evidence signatures** computed over the
whole evidence list, and rebuilding belief from scratch each turn rather than incrementally
— incremental updates would make the score depend on the order the policy happened to probe
in.

### 2026-08-12 — The verifier nearly condemned eight sound cases

**What happened:** First probe-sufficiency verifier swept every probe over every step, fed
the lot into `Belief`, and asked whether the posterior landed on the truth. It failed 8/44
cases, including **every** `api_failure`.

**Decision:** The cases were fine. The verifier was measuring the *policy's* belief model —
one `transport_failure` at P=0.92 for H4 drowned by four incidental `output_clean`
observations at P=0.05 each, harvested from innocent steps a real prober would never visit.
Acting on that reading would have meant rewriting sound cases to accommodate a known defect.

Rewritten as **subset existence**: does there exist a probe set of size ≤ 3 whose evidence
identifies the truth? Sufficiency is a property of the evidence, not of any one reasoner.
44/44 pass. The search also returns `oracle_probes`, the minimum probes per case — mean
1.22 — which is a lower bound no policy can beat and a better yardstick for probe economy
than any fixed procedure.

**Deviation from plan:** G6 and G7 added to the corpus requirements; `src/trace/verify.py`
added, which was not in the researcher's specified layout.

**Next:** Harness scaffolding, then regenerate the corpora under the new taxonomy.

## Verification run

```
$ python experiments/build_cases.py
```

Result: ACCEPTED. G1–G7 pass. 40/40 probe-sufficient, mean oracle probes 1.22, 8 cases
requiring ≥ 2 probes.

## Outcome

- [x] Eleven families implemented and verified
- [x] Cross-evidence families verified to require exactly 2 probes
- [x] 40-case inspection corpus emitted with an `agent_view.json` twin

## Carried forward

**Never let the artefact under test judge the data it is tested on.** Worth a line in the
paper. Also: the 40-case corpus is for inspection only — it cannot test PH1, and the file
says so.
