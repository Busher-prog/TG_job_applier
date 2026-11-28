"""Deterministic offline provider for development and tests (MOCK_MODE only).

It does not call any model. Each task is served by a registered handler that
derives output strictly from the input context (e.g. the heuristic CV parser),
so mock results never contain invented facts. Forbidden in production by
``Settings``.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.providers.llm.base import LLMError, LLMProvider, LLMUsage

MockHandler = Callable[[dict[str, Any]], dict[str, Any]]
_HANDLERS: dict[str, MockHandler] = {}


def mock_handler(task: str) -> Callable[[MockHandler], MockHandler]:
    def decorator(fn: MockHandler) -> MockHandler:
        _HANDLERS[task] = fn
        return fn

    return decorator


class MockLLMProvider(LLMProvider):
    name = "mock"

    async def _complete_json(
        self,
        *,
        task: str,
        system: str,
        user: str,
        json_schema: dict[str, Any],
        schema_name: str,
        context: dict[str, Any],
        temperature: float,
    ) -> tuple[dict[str, Any], LLMUsage]:
        # Import lazily so handlers register themselves.
        import app.services.ai.mock_handlers  # noqa: F401

        handler = _HANDLERS.get(task)
        if handler is None:
            raise LLMError(f"No mock handler for task {task}")
        return handler(context), LLMUsage(task=task, provider=self.name, model="mock")

    async def transcribe(self, audio: bytes, filename: str, language: str | None = None) -> str:
        raise LLMError("Voice transcription is not available in MOCK_MODE")
