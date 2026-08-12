"""Reveal the tool's DECLARED schema and report a validation verdict.

Amendment A1 (2026-08-12): argument values moved to the visible tier, so this probe no
longer reveals them -- it reveals the contract they were checked against. Seeing
`amount="45.00"` in a header tells you what was sent; only the schema tells you the tool
demanded a number. That is the real cost of schema validation in practice.

Discriminative role: isolates `arg_type_violation`. A clean verdict is strong evidence
*against* H2-by-malformed-arguments, which is exactly the kind of negative evidence a
confirmation-seeking policy fails to gather.
""" 
from __future__ import annotations

from typing import Any

from trace.models import Evidence, Trace
from .base import ProbeSpec, failed, register

SPEC = ProbeSpec(
    id="validate_tool_args",
    description="Reveal tool arguments and schema; report schema validation verdict.",
    target="step", applies_to_kinds=("tool_call",),
    reveals=("schema", "schema_valid", "violations"),
)

_JSON_TYPES: dict[str, Any] = {
    "string": str, "integer": int, "number": (int, float),
    "boolean": bool, "array": list, "object": dict,
}


def validate(arguments: dict, schema: dict | None) -> list[str]:
    """Required-field presence and JSON type match. Deliberately minimal."""
    if not schema:
        return []
    violations: list[str] = []
    props = schema.get("properties", {})
    for name in schema.get("required", []):
        if name not in arguments:
            violations.append(f"missing required field: {name}")
    for name, value in arguments.items():
        expected = props.get(name, {}).get("type")
        py = _JSON_TYPES.get(expected)
        if py is None:
            continue
        if expected == "integer" and isinstance(value, bool):
            violations.append(f"{name}: expected integer, got boolean")
        elif not isinstance(value, py):
            violations.append(f"{name}: expected {expected}, got {type(value).__name__}")
    return violations


class SchemaProbe:
    spec = SPEC

    def execute(self, trace: Trace, step_index: int | None) -> Evidence:
        s = trace.step(step_index)
        if s is None or s.tool_call is None:
            return failed(SPEC, step_index, "not a tool call")
        tc = s.tool_call
        violations = validate(tc.arguments, tc.schema)
        return Evidence(SPEC.id, step_index, True, {
            "schema": tc.schema,
            "schema_valid": not violations,
            "violations": violations,
        })


register(SchemaProbe())
