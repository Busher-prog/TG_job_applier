"""Handlers used by MockLLMProvider. Output is derived only from the input context."""

from __future__ import annotations

from typing import Any

from app.providers.llm.mock_provider import mock_handler
from app.services.cv.heuristic_parser import heuristic_parse


@mock_handler("cv_parser")
def _cv_parser(context: dict[str, Any]) -> dict[str, Any]:
    return heuristic_parse(context.get("text", ""), context.get("links", []))
