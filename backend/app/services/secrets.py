"""Encrypt API keys at rest. Derived from JWT_SECRET so we do not add another env var."""

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from app.config import JWT_SECRET


def _fernet() -> Fernet:
    digest = hashlib.sha256(JWT_SECRET.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_secret(value: str) -> str:
    return _fernet().encrypt(value.encode("utf-8")).decode("ascii")


def decrypt_secret(token: str) -> str:
    try:
        return _fernet().decrypt(token.encode("ascii")).decode("utf-8")
    except InvalidToken as exc:
        raise ValueError("Stored API key could not be decrypted.") from exc


def key_hint(value: str) -> str:
    trimmed = value.strip()
    if len(trimmed) <= 4:
        return "****"
    return trimmed[-4:]
