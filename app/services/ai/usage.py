"""In-process AI usage counters (persisted to Redis by the admin metrics job)."""

from __future__ import annotations

from collections import Counter
from threading import Lock
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.providers.llm.base import LLMUsage

_lock = Lock()
_calls: Counter[str] = Counter()
_tokens_in: Counter[str] = Counter()
_tokens_out: Counter[str] = Counter()


def record_usage(usage: "LLMUsage") -> None:
    key = f"{usage.provider}:{usage.model}"
    with _lock:
        _calls[key] += 1
        _tokens_in[key] += usage.input_tokens
        _tokens_out[key] += usage.output_tokens


def snapshot(reset: bool = False) -> dict[str, dict[str, int]]:
    with _lock:
        data = {
            key: {"calls": _calls[key], "input_tokens": _tokens_in[key], "output_tokens": _tokens_out[key]}
            for key in _calls
        }
        if reset:
            _calls.clear()
            _tokens_in.clear()
            _tokens_out.clear()
    return data
