"""LLM provider factory."""

from __future__ import annotations

from app.config import get_settings
from app.providers.llm.base import LLMError, LLMNotConfiguredError, LLMProvider

_provider: LLMProvider | None = None


def build_provider() -> LLMProvider:
    settings = get_settings()
    kind = settings.effective_ai_provider
    if kind == "mock":
        from app.providers.llm.mock_provider import MockLLMProvider

        return MockLLMProvider()
    if kind == "gemini":
        from app.providers.llm.gemini_provider import GeminiProvider

        return GeminiProvider(settings.gemini_api_key, settings.gemini_model, settings.ai_timeout_seconds)
    from app.providers.llm.openai_provider import OpenAIProvider

    return OpenAIProvider(
        settings.openai_api_key,
        settings.openai_model,
        settings.openai_transcription_model,
        settings.ai_timeout_seconds,
    )


def get_llm() -> LLMProvider:
    global _provider
    if _provider is None:
        _provider = build_provider()
    return _provider


def set_llm(provider: LLMProvider | None) -> None:
    global _provider
    _provider = provider


__all__ = ["LLMError", "LLMNotConfiguredError", "LLMProvider", "get_llm", "set_llm"]
