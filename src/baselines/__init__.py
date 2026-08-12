"""Comparison baselines.

Nothing in this package may import from `src/probes/`. B1 is defined by what it cannot do,
and `tests/test_baselines.py` enforces that by scanning these modules' imports rather than
trusting the convention.
"""
from .trace_formatter import FORMAT_VERSION, TraceView, format_trace
from .whole_trace_llm import (
    PROMPT_VERSION, B1Result, Diagnosis, WholeTraceLLMBaseline, parse_diagnosis,
)

__all__ = ["FORMAT_VERSION", "TraceView", "format_trace", "PROMPT_VERSION", "B1Result",
           "Diagnosis", "WholeTraceLLMBaseline", "parse_diagnosis"]
