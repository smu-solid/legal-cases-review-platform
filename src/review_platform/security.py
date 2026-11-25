"""Password and opaque-token security primitives."""

from __future__ import annotations

import hashlib
import hmac
import secrets
import unicodedata

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from review_platform.settings import Settings

PASSWORD_HASHER = PasswordHasher(time_cost=2, memory_cost=65_536, parallelism=2)
DUMMY_PASSWORD_HASH = PASSWORD_HASHER.hash("not-a-real-password-value")


class InvalidPasswordError(ValueError):
    pass


def normalize_email(value: str) -> str:
    return unicodedata.normalize("NFKC", value).strip().casefold()


def validate_password(password: str, settings: Settings) -> None:
    if len(password) < settings.password_min_length:
        raise InvalidPasswordError("password is too short")
    if len(password.encode("utf-8")) > settings.password_max_bytes:
        raise InvalidPasswordError("password is too long")


def hash_password(password: str, settings: Settings) -> str:
    validate_password(password, settings)
    return PASSWORD_HASHER.hash(password)


def verify_password(encoded: str | None, candidate: str) -> bool:
    target = encoded or DUMMY_PASSWORD_HASH
    try:
        verified = PASSWORD_HASHER.verify(target, candidate)
    except (InvalidHashError, VerificationError, VerifyMismatchError):
        return False
    return bool(verified and encoded is not None)


def password_needs_rehash(encoded: str) -> bool:
    return PASSWORD_HASHER.check_needs_rehash(encoded)


def new_token() -> str:
    return secrets.token_urlsafe(48)


def token_digest(token: str, key: str) -> bytes:
    return hmac.new(key.encode(), token.encode(), hashlib.sha256).digest()


def constant_time_equal(left: str | None, right: str | None) -> bool:
    if left is None or right is None:
        return False
    return hmac.compare_digest(left, right)
