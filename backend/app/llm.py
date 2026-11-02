"""Thin Claude wrapper: one JSON-schema call, every failure surfaced as LLMError.

Callers treat the LLM as optional. Anything raised here makes them fall back to the
deterministic path, so the app keeps working with no key, no network, or a refusal.
"""
from __future__ import annotations

import json
from typing import Protocol

DEFAULT_MODEL = "claude-opus-5-5"


class LLMError(Exception):
    pass


class LLMClient(Protocol):
    def complete_json(self, system: str, user: str, schema: dict) -> dict: ...


class ClaudeClient:
    def __init__(self, api_key: str, model: str = DEFAULT_MODEL, client=None):
        import anthropic

        self._errors = (anthropic.APIError,)
        self.model = model
        self._client = client or anthropic.Anthropic(api_key=api_key, timeout=30.0, max_retries=1)

    def complete_json(self, system: str, user: str, schema: dict) -> dict:
        try:
            response = self._client.beta.messages.create(
                model=self.model,
                max_tokens=8000,
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
                thinking={"type": "adaptive"},
                output_config={"effort": "medium", "format": {"type": "json_schema", "schema": schema}},
                system=system,
                messages=[{"role": "user", "content": user}],
            )
        except self._errors as e:
            raise LLMError(f"api_error: {type(e).__name__}") from e
        if response.stop_reason != "end_turn":
            raise LLMError(f"stop_reason: {response.stop_reason}")
        text = next((b.text for b in response.content if b.type == "text"), "")
        try:
            return json.loads(text)
        except json.JSONDecodeError as e:
            raise LLMError("invalid_json") from e
