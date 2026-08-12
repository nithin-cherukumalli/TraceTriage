"""Provider-agnostic LLM interface.

Three rules this module exists to enforce:

1. **No provider logic escapes this file.** Everything upstream sees `LLMClient`. Swapping
   Anthropic for OpenAI must not touch a baseline, a metric, or a test.
2. **The suite runs with no API key.** `MockClient` is the default everywhere. Provider SDKs
   are imported lazily inside their constructors, so the core stays dependency-free and an
   offline machine never sees an ImportError it did not ask for.
3. **Token usage is part of the result, not a side channel.** B1's cost has to be comparable
   with probe cost, so `LLMResponse` carries it.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True)
class LLMResponse:
    text: str
    input_tokens: int = 0
    output_tokens: int = 0
    model: str = ""
    #: Set when the provider itself failed. A transport failure is a data point about the
    #: baseline's practicality, not an exception to swallow.
    error: str | None = None

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


class LLMClient(Protocol):
    name: str
    model: str

    def complete(self, system: str, user: str, *, max_tokens: int = 2048,
                 temperature: float = 0.0) -> LLMResponse:
        ...


# --------------------------------------------------------------------------- mock

#: Keyword rules over the VISIBLE tier only. Deliberately shallow: this is a stand-in for
#: an LLM in offline tests, not a competitor. `tests/test_baselines.py` asserts it never
#: touches ground truth, and it is scored like any other client so its numbers are honest.
_MOCK_RULES: tuple[tuple[str, str], ...] = (
    ("timeout", "H4_external"),
    ("tool_error", "H4_external"),
    ("unavailable", "H4_external"),
    ("task_incomplete", "H1_planning"),
    ("refund_failed", "H2_tool"),
)


class MockClient:
    """Deterministic offline client.

    `mode` selects the failure shape, so parser tests exercise what real models actually
    emit rather than what we wish they emitted:

      heuristic      well-formed JSON from shallow keyword rules
      fenced         the same JSON wrapped in a ```json block with a prose preamble
      malformed      truncated JSON that cannot parse
      missing_fields valid JSON missing required keys
      wrong_types    confidence as a string, step as a string, evidence as a dict
      hallucinating  cites step ids that do not exist and asserts an unseen HTTP status
      empty          returns nothing at all
      provider_error simulates a transport failure
    """

    name = "mock"

    def __init__(self, mode: str = "heuristic", model: str = "mock-v1"):
        self.mode = mode
        self.model = model
        self.calls: list[tuple[str, str]] = []

    def complete(self, system: str, user: str, *, max_tokens: int = 2048,
                 temperature: float = 0.0) -> LLMResponse:
        self.calls.append((system, user))
        if self.mode == "provider_error":
            return LLMResponse("", model=self.model, error="simulated transport failure")
        if self.mode == "empty":
            return LLMResponse("", 100, 0, self.model)
        if self.mode == "malformed":
            return LLMResponse('{"predicted_mechanism": "H2_tool", "confidence":',
                               100, 12, self.model)
        if self.mode == "missing_fields":
            return LLMResponse(json.dumps({"predicted_mechanism": "H2_tool"}),
                               100, 10, self.model)
        if self.mode == "wrong_types":
            return LLMResponse(json.dumps({
                "predicted_mechanism": "H2_tool", "predicted_failure_step": "step three",
                "confidence": "high", "evidence_used": {"step_id": "1"},
                "alternative_explanations": "maybe the tool", "uncertainty": None}),
                100, 30, self.model)

        payload = self._diagnose(user)
        if self.mode == "hallucinating":
            payload["evidence_used"] = [
                {"step_id": "99", "observation": "the tool returned HTTP 503 with an "
                                                 "internal_error body"},
                {"step_id": "-1", "observation": "the retrieved document was superseded"},
            ]
            payload["confidence"] = 0.95
        body = json.dumps(payload, indent=2)
        if self.mode == "fenced":
            body = ("Looking at this trace, the failure seems clear.\n\n```json\n"
                    + body + "\n```\n\nHope that helps.")
        return LLMResponse(body, len(user) // 4, len(body) // 4, self.model)

    def _diagnose(self, user: str) -> dict:
        text = user.lower()
        mechanism, confidence = "H2_tool", 0.55
        for needle, mech in _MOCK_RULES:
            if needle in text:
                mechanism, confidence = mech, 0.72
                break
        # A shallow reader blames the last thing it can see. That is the behaviour under
        # study, so the mock reproduces it rather than correcting for it.
        steps = [int(m) for m in re.findall(r"^\|\s*(\d+)\s*\|", user, re.M)]
        last = max(steps) if steps else 0
        crash = max([s for s in steps if s != last], default=last)
        return {
            "predicted_mechanism": mechanism,
            "predicted_failure_step": crash,
            "confidence": confidence,
            "evidence_used": [{"step_id": str(crash),
                               "observation": "this is the last step before the run ended"}],
            "alternative_explanations": ["H1_planning", "H3_context"],
            "uncertainty": "no tool outputs are visible, so this rests on the step summaries",
        }


# --------------------------------------------------------------------------- providers

class AnthropicClient:
    """Claude API. SDK imported lazily so the core has no hard dependency."""

    name = "anthropic"

    def __init__(self, model: str = "claude-opus-5", api_key: str | None = None):
        try:
            import anthropic
        except ImportError as exc:  # pragma: no cover - offline by default
            raise RuntimeError(
                "anthropic SDK not installed. `pip install -e '.[llm]'`, or use "
                "--client mock to run offline."
            ) from exc
        self.model = model
        self._client = anthropic.Anthropic(api_key=api_key or os.environ.get("ANTHROPIC_API_KEY"))

    def complete(self, system: str, user: str, *, max_tokens: int = 2048,
                 temperature: float = 0.0) -> LLMResponse:  # pragma: no cover - network
        try:
            r = self._client.messages.create(
                model=self.model, max_tokens=max_tokens, temperature=temperature,
                system=system, messages=[{"role": "user", "content": user}])
        except Exception as exc:
            return LLMResponse("", model=self.model, error=f"{type(exc).__name__}: {exc}")
        text = "".join(b.text for b in r.content if getattr(b, "type", "") == "text")
        return LLMResponse(text, r.usage.input_tokens, r.usage.output_tokens, self.model)


class OpenAIClient:
    """OpenAI API. SDK imported lazily."""

    name = "openai"

    def __init__(self, model: str = "gpt-4o", api_key: str | None = None):
        try:
            import openai
        except ImportError as exc:  # pragma: no cover - offline by default
            raise RuntimeError(
                "openai SDK not installed. `pip install -e '.[llm]'`, or use "
                "--client mock to run offline."
            ) from exc
        self.model = model
        self._client = openai.OpenAI(api_key=api_key or os.environ.get("OPENAI_API_KEY"))

    def complete(self, system: str, user: str, *, max_tokens: int = 2048,
                 temperature: float = 0.0) -> LLMResponse:  # pragma: no cover - network
        try:
            r = self._client.chat.completions.create(
                model=self.model, max_tokens=max_tokens, temperature=temperature,
                messages=[{"role": "system", "content": system},
                          {"role": "user", "content": user}])
        except Exception as exc:
            return LLMResponse("", model=self.model, error=f"{type(exc).__name__}: {exc}")
        return LLMResponse(r.choices[0].message.content or "",
                           r.usage.prompt_tokens, r.usage.completion_tokens, self.model)


_REGISTRY = {"mock": MockClient, "anthropic": AnthropicClient, "openai": OpenAIClient}


def get_client(name: str = "mock", **kwargs) -> LLMClient:
    """Factory. Defaults to mock so nothing accidentally spends money or needs a key."""
    if name not in _REGISTRY:
        raise ValueError(f"unknown client {name!r}; available: {sorted(_REGISTRY)}")
    return _REGISTRY[name](**kwargs)
