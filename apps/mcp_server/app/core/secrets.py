from __future__ import annotations

import base64
import hashlib
import hmac
import secrets

from cryptography.fernet import Fernet


def _fernet_key(secret: str) -> bytes:
    digest = hashlib.sha256(secret.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest)


def encrypt_secret(value: str, key: str) -> str:
    return Fernet(_fernet_key(key)).encrypt(value.encode("utf-8")).decode("utf-8")


def decrypt_secret(value: str, key: str) -> str:
    return Fernet(_fernet_key(key)).decrypt(value.encode("utf-8")).decode("utf-8")


def hash_token(token: str, salt: str) -> str:
    return hashlib.sha256(f"{salt}:{token}".encode("utf-8")).hexdigest()


def verify_token(token: str, expected_hash: str | None, salt: str) -> bool:
    if not expected_hash:
        return False
    return hmac.compare_digest(hash_token(token, salt), expected_hash)


def issue_token(prefix: str) -> str:
    return f"{prefix}_{secrets.token_urlsafe(32)}"

