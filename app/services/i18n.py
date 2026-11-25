"""Localisation: messages live in app/locales/<lang>.json."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.config import DEFAULT_LANGUAGE, SUPPORTED_LANGUAGES

LOCALES_DIR = Path(__file__).resolve().parent.parent / "locales"


class _SafeDict(dict[str, Any]):
    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


def _flatten(data: dict[str, Any], prefix: str = "") -> dict[str, Any]:
    flat: dict[str, Any] = {}
    for key, value in data.items():
        full = f"{prefix}{key}"
        if isinstance(value, dict) and not _is_plural(value):
            flat.update(_flatten(value, f"{full}."))
        else:
            flat[full] = value
    return flat


def _is_plural(value: dict[str, Any]) -> bool:
    return set(value) <= {"zero", "one", "few", "many", "other"} and "other" in value


@lru_cache
def load_locale(lang: str) -> dict[str, Any]:
    path = LOCALES_DIR / f"{lang}.json"
    with path.open(encoding="utf-8") as fh:
        return _flatten(json.load(fh))


def plural_form(lang: str, n: int) -> str:
    if lang in ("ru", "uk"):
        if n % 10 == 1 and n % 100 != 11:
            return "one"
        if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
            return "few"
        return "many"
    return "one" if n == 1 else "other"


class Translator:
    """Callable bound to one language: ``_("welcome.text", name=...)``."""

    def __init__(self, lang: str) -> None:
        self.lang = lang if lang in SUPPORTED_LANGUAGES else DEFAULT_LANGUAGE

    def __call__(self, key: str, **kwargs: Any) -> str:
        return gettext(self.lang, key, **kwargs)

    def plural(self, key: str, n: int, **kwargs: Any) -> str:
        return ngettext(self.lang, key, n, **kwargs)


def _lookup(lang: str, key: str) -> Any:
    value = load_locale(lang).get(key)
    if value is None and lang != DEFAULT_LANGUAGE:
        value = load_locale(DEFAULT_LANGUAGE).get(key)
    return value


def gettext(lang: str, key: str, **kwargs: Any) -> str:
    value = _lookup(lang, key)
    if value is None:
        return key
    if isinstance(value, dict):
        value = value.get("other", key)
    return str(value).format_map(_SafeDict(kwargs)) if kwargs else str(value)


def ngettext(lang: str, key: str, n: int, **kwargs: Any) -> str:
    value = _lookup(lang, key)
    if not isinstance(value, dict):
        return gettext(lang, key, n=n, **kwargs)
    form = plural_form(lang, n)
    template = value.get(form) or value.get("other") or key
    return str(template).format_map(_SafeDict({"n": n, **kwargs}))


def all_translations(key: str) -> set[str]:
    """Every localized variant of a key (used to match reply texts)."""
    return {gettext(lang, key) for lang in SUPPORTED_LANGUAGES}
