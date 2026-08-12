"""Reveal the raw tool response and transport-level status.

Discriminative role: separates `upstream_error` (H4 — transport failure, 5xx or timeout,
high latency) from semantic failures that return HTTP 200 with a refusal body.
"""
from __future__ import annotations

from trace.models import Evidence, Trace
from .base import ProbeSpec, failed, register

SPEC = ProbeSpec(
    id="inspect_tool_output",
    description="Reveal raw tool response, status, HTTP code and latency.",
    target="step", applies_to_kinds=("tool_call",),
    reveals=("raw_output", "status", "http_status", "latency_ms"),
)


class ToolOutputProbe:
    spec = SPEC

    def execute(self, trace: Trace, step_index: int | None) -> Evidence:
        s = trace.step(step_index)
        if s is None or s.tool_call is None:
            return failed(SPEC, step_index, "not a tool call")
        tc = s.tool_call
        return Evidence(SPEC.id, step_index, True, {
            "raw_output": tc.raw_output,
            "status": tc.status,
            "http_status": tc.http_status,
            "latency_ms": tc.latency_ms,
        })


register(ToolOutputProbe())
