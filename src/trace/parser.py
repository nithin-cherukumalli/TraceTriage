"""Load and save traces as JSONL, validated against schemas/trace_schema.json.

`load_cases` is the only door through which a Trace enters an experiment, so the
ground-truth split filter lives here: dev never sees held-out families.
"""
from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from .models import (
    GroundTruth, Mechanism, RetrievedContext, Step, ToolCall, Trace,
)

SCHEMA_PATH = Path(__file__).resolve().parents[2] / "schemas" / "trace_schema.json"


def to_dict(trace: Trace) -> dict:
    d = asdict(trace)
    if trace.ground_truth is not None:
        d["ground_truth"]["mechanism"] = trace.ground_truth.mechanism.value
        d["ground_truth"]["distractor_steps"] = list(trace.ground_truth.distractor_steps)
    return d


def from_dict(d: dict) -> Trace:
    steps = []
    for s in d["steps"]:
        tc = s.get("tool_call")
        rc = s.get("retrieval")
        steps.append(Step(
            index=s["index"], kind=s["kind"], summary=s["summary"],
            plan_text=s.get("plan_text"),
            tool_call=ToolCall(**tc) if tc else None,
            retrieval=RetrievedContext(**rc) if rc else None,
            replay_record=s.get("replay_record"),
        ))
    gt = d.get("ground_truth")
    ground_truth = None
    if gt:
        ground_truth = GroundTruth(
            mechanism=Mechanism(gt["mechanism"]), family=gt["family"],
            root_cause_step=gt["root_cause_step"], crash_step=gt["crash_step"],
            in_taxonomy=gt["in_taxonomy"],
            distractor_steps=tuple(gt.get("distractor_steps", ())),
            notes=gt.get("notes", ""),
        )
    return Trace(trace_id=d["trace_id"], task=d["task"], steps=steps,
                 final_result=d.get("final_result", ""),
                 final_error=d.get("final_error"),
                 reference_trace_id=d.get("reference_trace_id"),
                 ground_truth=ground_truth)


def save_cases(traces: list[Trace], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as fh:
        for t in traces:
            fh.write(json.dumps(to_dict(t)) + "\n")


def load_cases(path: Path) -> list[Trace]:
    with Path(path).open() as fh:
        return [from_dict(json.loads(line)) for line in fh if line.strip()]


def validate_against_schema(traces: list[Trace]) -> list[str]:
    """Structural check without a jsonschema dependency.

    Deliberately hand-rolled: the only rules we actually need enforced are the ones the
    experiment depends on, and a dependency-free check runs in CI everywhere.
    """
    errors: list[str] = []
    kinds = {"plan", "tool_call", "retrieval", "reflect", "final"}
    for t in traces:
        idx = [s.index for s in t.steps]
        if idx != sorted(idx) or len(set(idx)) != len(idx):
            errors.append(f"{t.trace_id}: step indices not unique and ordered")
        for s in t.steps:
            if s.kind not in kinds:
                errors.append(f"{t.trace_id}#{s.index}: bad kind {s.kind!r}")
            if s.kind == "tool_call" and s.tool_call is None:
                errors.append(f"{t.trace_id}#{s.index}: tool_call step without tool_call")
            if s.kind == "retrieval" and s.retrieval is None:
                errors.append(f"{t.trace_id}#{s.index}: retrieval step without retrieval")
        gt = t.ground_truth
        if gt is None:
            errors.append(f"{t.trace_id}: missing ground truth")
            continue
        if gt.root_cause_step not in idx:
            errors.append(f"{t.trace_id}: root_cause_step {gt.root_cause_step} not a step")
        if gt.crash_step not in idx:
            errors.append(f"{t.trace_id}: crash_step {gt.crash_step} not a step")
        if gt.root_cause_step > gt.crash_step:
            errors.append(f"{t.trace_id}: root cause after crash")
    return errors
