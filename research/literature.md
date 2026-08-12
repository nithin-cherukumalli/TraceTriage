# Literature

Kept short and load-bearing. Each entry records what it gives us and where it stops.

## Failure attribution benchmarks

**TRAIL: Trace Reasoning and Agentic Issue Localization** (arXiv:2505.08638, Patronus AI).
Human-annotated OpenTelemetry traces with an error taxonomy and span-level locations.
*Gives us:* a real-trace evaluation target and prior art for treating localization as a
distinct task. *Stops at:* static traces, no preserved re-execution records — so
`replay_probe` must return `unavailable` on every TRAIL case. Report that as a finding
about tracing infrastructure, not as a limitation of the method.

**Which Agent Causes Task Failures and When? (Who&When)** (ag2ai). Labels the responsible
agent and the decisive step in multi-agent logs. *Gives us:* an external notion of
"decisive step" that is closer to our `root_cause_step` than to `crash_step`, which
independently supports the lesson-6 distinction. *Stops at:* coarse mechanism labels;
mapping onto H1–H4 will be lossy and must ship a documented mapping table.

**AgenTracer** (arXiv:2509.03312) and follow-on attribution work. *Gives us:* evidence
that whole-trace LLM attribution underperforms, which is exactly the B1 baseline claim.

## Positioning

All of the above are **one-shot attribution over a fully visible trace**. None treats
evidence gathering as a decision. That gap is this project's contribution: the diagnostic
agent starts blind and must pay for what it looks at.

## To read and summarise here

- Sequential hypothesis testing / optimal experiment design (classical statistics)
- Software fault localization: spectrum-based and delta debugging
- Model-based diagnosis (Reiter, de Kleer) — consistency-based diagnosis is the closest
  classical framing to what we are doing
