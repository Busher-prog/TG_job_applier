"""Reusable normalisers/validators for AI output."""

from __future__ import annotations

import re
from typing import Annotated, Any
from urllib.parse import urlparse

from pydantic import BeforeValidator

_EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+'-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")
_MONTHS = {
    # en
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
    # de
    "jän": 1, "mär": 3, "mai": 5, "okt": 10, "dez": 12,
}
PRESENT_WORDS = {
    "present", "current", "now", "today", "ongoing",
    "heute", "aktuell", "jetzt", "derzeit", "bis heute",
    "настоящее время", "наст. время", "по настоящее время", "сейчас", "н.в.",
    "теперішній час", "дотепер", "зараз", "по теперішній час",
}


def normalize_partial_date(value: Any) -> str | None:
    """Return 'YYYY' or 'YYYY-MM', or None. Never invents missing parts."""
    if value is None:
        return None
    text = str(value).strip().lower()
    if not text or text in PRESENT_WORDS:
        return None
    m = re.fullmatch(r"(\d{4})-(\d{1,2})(?:-\d{1,2})?", text)
    if m:
        year, month = int(m.group(1)), int(m.group(2))
        return f"{year:04d}-{month:02d}" if 1 <= month <= 12 and 1950 <= year <= 2100 else None
    m = re.fullmatch(r"(\d{1,2})[./](\d{4})", text)
    if m:
        month, year = int(m.group(1)), int(m.group(2))
        return f"{year:04d}-{month:02d}" if 1 <= month <= 12 and 1950 <= year <= 2100 else None
    m = re.fullmatch(r"(\d{1,2})[./](\d{1,2})[./](\d{4})", text)
    if m:
        month, year = int(m.group(2)), int(m.group(3))
        return f"{year:04d}-{month:02d}" if 1 <= month <= 12 and 1950 <= year <= 2100 else None
    m = re.fullmatch(r"([a-zä]{3})[a-zä]*\.?\s+(\d{4})", text)
    if m and m.group(1) in _MONTHS:
        return f"{int(m.group(2)):04d}-{_MONTHS[m.group(1)]:02d}"
    m = re.fullmatch(r"(\d{4})", text)
    if m and 1950 <= int(text) <= 2100:
        return text
    return None


def is_present(value: Any) -> bool:
    return value is not None and str(value).strip().lower() in PRESENT_WORDS


def normalize_url(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip().rstrip(".,;)")
    if not text:
        return None
    if not re.match(r"^https?://", text, re.I):
        if re.match(r"^(www\.)?[\w-]+(\.[\w-]+)+(/.*)?$", text):
            text = "https://" + text
        else:
            return None
    parsed = urlparse(text)
    if parsed.scheme not in ("http", "https") or not parsed.netloc or "." not in parsed.netloc:
        return None
    if " " in text or len(text) > 500:
        return None
    return text


def normalize_email(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip().strip("<>").lower()
    if text.startswith("mailto:"):
        text = text[7:]
    return text if _EMAIL_RE.match(text) and len(text) <= 320 else None


def normalize_phone(value: Any) -> str | None:
    if value is None:
        return None
    text = re.sub(r"[^\d+()\-\s./]", "", str(value)).strip()
    digits = re.sub(r"\D", "", text)
    if not 7 <= len(digits) <= 15:
        return None
    return re.sub(r"\s+", " ", text)


def clean_str(value: Any, max_len: int = 500) -> str | None:
    if value is None:
        return None
    text = re.sub(r"\s+", " ", str(value)).strip()
    return text[:max_len] or None


def clean_list(value: Any, max_items: int = 50, max_len: int = 300) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        value = [value]
    out: list[str] = []
    seen: set[str] = set()
    for item in value:
        text = clean_str(item, max_len)
        if text and text.lower() not in seen:
            seen.add(text.lower())
            out.append(text)
        if len(out) >= max_items:
            break
    return out


PartialDate = Annotated[str | None, BeforeValidator(normalize_partial_date)]
OptionalUrl = Annotated[str | None, BeforeValidator(normalize_url)]
OptionalEmail = Annotated[str | None, BeforeValidator(normalize_email)]
OptionalPhone = Annotated[str | None, BeforeValidator(normalize_phone)]
ShortStr = Annotated[str | None, BeforeValidator(lambda v: clean_str(v, 300))]
LongStr = Annotated[str | None, BeforeValidator(lambda v: clean_str(v, 4000))]
StrList = Annotated[list[str], BeforeValidator(clean_list)]
