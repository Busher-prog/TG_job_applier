"""LLM provider interface.

Every AI agent call goes through :meth:`LLMProvider.generate_json`, which
returns a Pydantic model validated against the agent's JSON Schema. The model
output is never executed — backend services decide what to do with it.
"""

from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

logger = logging.getLogger("ai.usage")

T = TypeVar("T", bound=BaseModel)


class LLMError(RuntimeError):
    """Provider failure (network, quota, invalid output after retries)."""


class LLMNotConfiguredError(LLMError):
    pass


@dataclass(slots=True)
class LLMUsage:
    task: str
    provider: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0


class LLMProvider(ABC):
    name: str = "base"
    max_validation_retries: int = 1

    async def generate_json(
        self,
        *,
        task: str,
        system: str,
        user: str,
        schema: type[T],
        context: dict[str, Any] | None = None,
        temperature: float = 0.2,
    ) -> T:
        """Run one structured-output call and validate the result."""
        json_schema = schema.model_json_schema()
        last_error: Exception | None = None
        prompt = user
        for _attempt in range(self.max_validation_retries + 1):
            raw, usage = await self._complete_json(
                task=task,
                system=system,
                user=prompt,
                json_schema=json_schema,
                schema_name=task,
                context=context or {},
                temperature=temperature,
            )
            self._record_usage(usage)
            try:
                data = json.loads(raw) if isinstance(raw, str) else raw
                return schema.model_validate(data)
            except (json.JSONDecodeError, ValidationError) as exc:
                last_error = exc
                prompt = (
                    f"{user}\n\nYour previous answer did not match the required JSON schema. "
                    f"Validation errors: {str(exc)[:1500]}\nReturn corrected JSON only."
                )
        raise LLMError(f"Invalid structured output for task {task}") from last_error

    @abstractmethod
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
    ) -> tuple[str | dict[str, Any], LLMUsage]:
        """Return raw JSON (string or dict) and token usage."""

    @abstractmethod
    async def transcribe(self, audio: bytes, filename: str, language: str | None = None) -> str:
        """Speech-to-text for Telegram voice messages."""

    def _record_usage(self, usage: LLMUsage) -> None:
        # Only metadata is logged — never prompts or completions.
        logger.info(
            "llm_call task=%s provider=%s model=%s in=%s out=%s",
            usage.task,
            usage.provider,
            usage.model,
            usage.input_tokens,
            usage.output_tokens,
        )
        from app.services.ai.usage import record_usage

        record_usage(usage)
