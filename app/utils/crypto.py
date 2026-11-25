"""Symmetric encryption for secrets at rest (OAuth refresh tokens)."""

from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from app.config import get_settings


class EncryptionError(RuntimeError):
    pass


def _fernet(key: str | None = None) -> Fernet:
    raw = key if key is not None else get_settings().encryption_key
    if not raw:
        raise EncryptionError("ENCRYPTION_KEY is not configured")
    try:
        return Fernet(raw.encode())
    except (ValueError, TypeError):
        # Accept any passphrase by deriving a 32-byte key from it.
        derived = base64.urlsafe_b64encode(hashlib.sha256(raw.encode()).digest())
        return Fernet(derived)


def encrypt(plaintext: str, key: str | None = None) -> bytes:
    return _fernet(key).encrypt(plaintext.encode("utf-8"))


def decrypt(token: bytes, key: str | None = None) -> str:
    try:
        return _fernet(key).decrypt(token).decode("utf-8")
    except InvalidToken as exc:
        raise EncryptionError("Unable to decrypt value") from exc


def generate_key() -> str:
    return Fernet.generate_key().decode()
