"""Google Gemini provider via the public REST API (generateContent)."""

from __future__ import annotations

import base64
import json
from typing import Any

import httpx

from app.providers.llm.base import LLMError, LLMNotConfiguredError, LLMProvider, LLMUsage

API_ROOT = "https://generativelanguage.googleapis.com/v1beta/models"


class GeminiProvider(LLMProvider):
    name = "gemini"

    def __init__(self, api_key: str, model: str, timeout: float) -> None:
        if not api_key:
            raise LLMNotConfiguredError("GEMINI_API_KEY is not set")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout

    async def _generate(self, body: dict[str, Any]) -> dict[str, Any]:
        url = f"{API_ROOT}/{self.model}:generateContent"
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                # Key goes in a header so it never appears in URLs / access logs.
                response = await client.post(url, json=body, headers={"x-goog-api-key": self.api_key})
        except httpx.HTTPError as exc:
            raise LLMError(f"Gemini request failed: {type(exc).__name__}") from exc
        if response.status_code != 200:
            raise LLMError(f"Gemini HTTP {response.status_code}")
        return response.json()

    @staticmethod
    def _text(payload: dict[str, Any]) -> str:
        try:
            parts = payload["candidates"][0]["content"]["parts"]
        except (KeyError, IndexError) as exc:
            raise LLMError("Gemini returned no content") from exc
        # Newer models may return reasoning parts flagged "thought": they are not the answer.
        return "".join(p.get("text", "") for p in parts if not p.get("thought"))

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
        system_full = (
            f"{system}\n\nRespond with a single JSON object that validates against this JSON Schema:\n"
            f"{json.dumps(json_schema, ensure_ascii=False)}"
        )
        body = {
            "systemInstruction": {"parts": [{"text": system_full}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": {"responseMimeType": "application/json", "temperature": temperature},
        }
        payload = await self._generate(body)
        meta = payload.get("usageMetadata", {})
        usage = LLMUsage(
            task=task,
            provider=self.name,
            model=self.model,
            input_tokens=meta.get("promptTokenCount", 0),
            output_tokens=meta.get("candidatesTokenCount", 0),
        )
        return self._text(payload), usage

    async def transcribe(self, audio: bytes, filename: str, language: str | None = None) -> str:
        mime = "audio/ogg" if filename.endswith((".oga", ".ogg")) else "audio/mpeg"
        body = {
            "contents": [
                {
                    "role": "user",
                    "parts": [
                        {"text": "Transcribe this audio verbatim. Return only the transcript."},
                        {"inlineData": {"mimeType": mime, "data": base64.b64encode(audio).decode()}},
                    ],
                }
            ],
            "generationConfig": {"temperature": 0},
        }
        payload = await self._generate(body)
        self._record_usage(LLMUsage(task="transcribe", provider=self.name, model=self.model))
        return self._text(payload).strip()
