"""Reproducible trace -> LLM input conversion.

**This module is the leakage boundary for B1.** `format_observation()` takes an
`Observation` — the redacted projection produced by `make_observation()`, which
`tests/test_contract.py` already proves cannot reach a `GroundTruth`. B1 therefore inherits
that proof instead of restating it, and no ad-hoc prompt anywhere in the codebase is allowed
to assemble trace text by hand.

`format_full_trace()` exists for the FULL view and is the one function here that touches a
`Trace`. It reads only fields tagged VISIBLE or PROBE in `schemas/trace_schema.json` and
never `ground_truth`; a test enforces that by scanning its output for hidden values.

Two views, because the pre-registration and the researcher's spec disagree:

* `TraceView.VISIBLE` — task, step headers, tool names, tool arguments, final outcome. What
  a debugging engineer sees before doing any work, and exactly what the probing policies
  start from. This is the fair-information comparison.
* `TraceView.FULL` — everything a probe could ever reveal, handed over at once. The
  faithful reproduction of "paste the whole log into an LLM", which is the practice under
  criticism.

Both are run and both are reported. Picking one silently would decide a question the
experiment is supposed to answer.
"""
from __future__ import annotations

import json
from enum import Enum

from trace.models import Observation, Trace


class TraceView(str, Enum):
    VISIBLE = "visible"
    FULL = "full"


#: Bumped whenever the rendering changes. Results carry it, because a formatter change
#: silently invalidates comparison across runs.
FORMAT_VERSION = "tf-v1"


def _args(arguments: dict | None) -> str:
    if not arguments:
        return "—"
    return json.dumps(arguments, sort_keys=True)


def _steps_table(rows: list[tuple[int, str, str, str, str]]) -> list[str]:
    out = ["| step | kind | summary | tool | arguments |",
           "|---|---|---|---|---|"]
    for idx, kind, summary, tool, args in rows:
        out.append(f"| {idx} | {kind} | {summary} | {tool} | {args} |")
    return out


# --------------------------------------------------------------------------- visible

def format_observation(obs: Observation) -> str:
    """Render the VISIBLE tier. The only input B1 gets under the default configuration."""
    rows = [(h.index, h.kind, h.summary, h.tool_name or "—", _args(h.tool_arguments))
            for h in obs.headers]

    lines = [
        "# FAILED AGENT RUN",
        "",
        "## Task given to the agent",
        obs.task,
        "",
        "## Outcome",
        f"- returned to the user: {obs.final_result or '(nothing)'}",
        f"- error raised: {obs.final_error if obs.final_error else '(none — the run raised no error)'}",
        "",
        "## Execution steps",
        "",
    ]
    lines += _steps_table(rows)
    lines += [
        "",
        "## Metadata",
        f"- total steps: {len(obs.headers)}",
        f"- a known-good reference run of this task exists: "
        f"{'yes' if obs.has_reference_trace else 'no'}",
        "",
        "## What is NOT shown to you",
        "",
        "The following were recorded during the run but are withheld:",
        "",
        "- the text of any plan or reflection step",
        "- raw tool outputs, response status, HTTP codes and latencies",
        "- the declared schema each tool call was validated against",
        "- retrieval queries, retrieved documents and relevance scores",
        "- any preserved replay record",
        "- the contents of the known-good reference run, if one exists",
        "",
        "You cannot obtain these. Diagnose from what is above, and let your confidence "
        "reflect that.",
    ]
    return "\n".join(lines)


# --------------------------------------------------------------------------- full

def format_full_trace(trace: Trace) -> str:
    """Render the FULL view: everything a probe could reveal, handed over at once.

    Reads only VISIBLE and PROBE fields. Never `ground_truth` — enforced by a test that
    scans the output for the hidden mechanism, family and step values.
    """
    rows = [(s.index, s.kind, s.summary,
             s.tool_call.name if s.tool_call else "—",
             _args(s.tool_call.arguments if s.tool_call else None))
            for s in trace.steps]

    lines = [
        "# FAILED AGENT RUN (complete record)",
        "",
        "## Task given to the agent",
        trace.task,
        "",
        "## Outcome",
        f"- returned to the user: {trace.final_result or '(nothing)'}",
        f"- error raised: {trace.final_error if trace.final_error else '(none — the run raised no error)'}",
        "",
        "## Execution steps",
        "",
    ]
    lines += _steps_table(rows)
    lines += ["", "## Step detail", ""]

    for s in trace.steps:
        lines.append(f"### Step {s.index} — {s.kind}: {s.summary}")
        if s.plan_text:
            lines.append(f"- reasoning: {s.plan_text}")
        if s.tool_call:
            tc = s.tool_call
            lines += [
                f"- tool: {tc.name}",
                f"- arguments: {_args(tc.arguments)}",
                f"- declared schema: {json.dumps(tc.schema, sort_keys=True) if tc.schema else '—'}",
                f"- status: {tc.status}",
                f"- http_status: {tc.http_status if tc.http_status is not None else '—'}",
                f"- latency_ms: {tc.latency_ms}",
                f"- raw output: {tc.raw_output if tc.raw_output else '(empty)'}",
            ]
            if s.replay_record is not None:
                lines.append(f"- preserved replay record: {json.dumps(s.replay_record, sort_keys=True)}")
            else:
                lines.append("- preserved replay record: none captured (replay is impossible here)")
        if s.retrieval:
            r = s.retrieval
            lines += [
                f"- retrieval query: {r.query}",
                f"- retrieved documents: {json.dumps(r.documents)}",
                f"- relevance scores: {r.scores}",
            ]
        lines.append("")

    lines += ["## Metadata",
              f"- total steps: {len(trace.steps)}",
              f"- a known-good reference run of this task exists: "
              f"{'yes' if trace.reference_trace_id else 'no'}"]
    return "\n".join(lines)


# --------------------------------------------------------------------------- dispatch

def format_trace(source, view: TraceView = TraceView.VISIBLE) -> str:
    """Single entry point.

    VISIBLE accepts an Observation (and only an Observation — passing a Trace is an error,
    not a convenience, because it is exactly the mistake that would leak). FULL accepts a
    Trace.
    """
    if view is TraceView.VISIBLE:
        if not isinstance(source, Observation):
            raise TypeError(
                "the VISIBLE view takes an Observation, not a "
                f"{type(source).__name__}. Build it with make_observation(); handing a "
                "Trace to the formatter is how ground truth leaks into a baseline.")
        return format_observation(source)
    if not isinstance(source, Trace):
        raise TypeError(f"the FULL view takes a Trace, not a {type(source).__name__}")
    return format_full_trace(source)


def visible_step_ids(obs: Observation) -> set[int]:
    """Step indices the model could legitimately cite. Used by the grounding metric."""
    return {h.index for h in obs.headers}
