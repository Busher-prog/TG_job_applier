"""OpenAI provider (Chat Completions with JSON Schema response format)."""

from __future__ import annotations

from typing import Any

from app.providers.llm.base import LLMError, LLMNotConfiguredError, LLMProvider, LLMUsage


def _supports_temperature(model: str) -> bool:
    # Reasoning models reject a custom temperature.
    return not (model.startswith("o") or model.startswith("gpt-5"))


class OpenAIProvider(LLMProvider):
    name = "openai"

    def __init__(self, api_key: str, model: str, transcription_model: str, timeout: float) -> None:
        if not api_key:
            raise LLMNotConfiguredError("OPENAI_API_KEY is not set")
        from openai import AsyncOpenAI

        self.model = model
        self.transcription_model = transcription_model
        self.client = AsyncOpenAI(api_key=api_key, timeout=timeout, max_retries=2)

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
    ) -> tuple[str, LLMUsage]:
        from openai import OpenAIError

        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": schema_name[:64], "schema": json_schema, "strict": False},
            },
        }
        if _supports_temperature(self.model):
            kwargs["temperature"] = temperature
        try:
            response = await self.client.chat.completions.create(**kwargs)
        except OpenAIError as exc:
            raise LLMError(f"OpenAI request failed: {type(exc).__name__}") from exc
        choice = response.choices[0]
        content = choice.message.content or ""
        if getattr(choice.message, "refusal", None):
            raise LLMError("Model refused the request")
        usage = LLMUsage(
            task=task,
            provider=self.name,
            model=self.model,
            input_tokens=getattr(response.usage, "prompt_tokens", 0) or 0,
            output_tokens=getattr(response.usage, "completion_tokens", 0) or 0,
        )
        return content, usage

    async def transcribe(self, audio: bytes, filename: str, language: str | None = None) -> str:
        from openai import OpenAIError

        try:
            kwargs: dict[str, Any] = {"model": self.transcription_model, "file": (filename, audio)}
            if language:
                kwargs["language"] = language
            result = await self.client.audio.transcriptions.create(**kwargs)
        except OpenAIError as exc:
            raise LLMError(f"Transcription failed: {type(exc).__name__}") from exc
        self._record_usage(LLMUsage(task="transcribe", provider=self.name, model=self.transcription_model))
        return (getattr(result, "text", "") or "").strip()
