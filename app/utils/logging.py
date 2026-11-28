"""Logging setup that keeps personal data out of application logs."""

from __future__ import annotations

import logging
import re
import sys

_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_TOKEN_RE = re.compile(r"\b\d{6,12}:[A-Za-z0-9_-]{30,}\b")  # Telegram bot token
_BEARER_RE = re.compile(r"(?i)(bearer\s+|refresh_token[\"'=:\s]+|api[_-]?key[\"'=:\s]+)[A-Za-z0-9._\-]{10,}")
_PHONE_RE = re.compile(r"\+?\d[\d\s().-]{8,}\d")


class RedactingFilter(logging.Filter):
    """Masks emails, phone numbers and credentials in every log record."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:  # pragma: no cover - malformed record
            return True
        redacted = redact(message)
        if redacted != message:
            record.msg = redacted
            record.args = ()
        return True


def redact(text: str) -> str:
    text = _TOKEN_RE.sub("[REDACTED_TOKEN]", text)
    text = _BEARER_RE.sub(lambda m: m.group(1) + "[REDACTED]", text)
    text = _EMAIL_RE.sub("[EMAIL]", text)
    text = _PHONE_RE.sub("[PHONE]", text)
    return text


def setup_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    handler.addFilter(RedactingFilter())
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level.upper())
    # aiogram logs full update payloads at DEBUG — keep it at INFO at most.
    logging.getLogger("aiogram.event").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
