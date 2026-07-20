"""Password and token primitives for database-backed authentication."""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from uuid import UUID

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError


_PASSWORD_HASHER = PasswordHasher()
_API_KEY_PREFIX = "pptm_"
_DUMMY_PASSWORD_HASH = _PASSWORD_HASHER.hash("not-a-real-user-password")


@dataclass(frozen=True)
class AuthenticatedUser:
    """Authenticated user identity attached to one request."""

    id: UUID
    username: str
    is_admin: bool


def normalize_username(username: str) -> str:
    """Normalize usernames consistently for creation and login."""
    return username.strip().casefold()


def validate_new_password(password: str) -> None:
    """Reject passwords that are unsuitable for a new account."""
    if len(password) < 12:
        raise ValueError("password must contain at least 12 characters")
    if len(password) > 1024:
        raise ValueError("password must contain at most 1024 characters")


def hash_password(password: str) -> str:
    """Hash a password with Argon2id."""
    validate_new_password(password)
    return _PASSWORD_HASHER.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    """Verify a supplied password without exposing hash parsing errors."""
    try:
        return _PASSWORD_HASHER.verify(password_hash, password)
    except (InvalidHashError, VerificationError, VerifyMismatchError):
        return False


def verify_missing_user(password: str) -> None:
    """Consume one password verification for an unknown username."""
    verify_password(_DUMMY_PASSWORD_HASH, password)


def password_needs_rehash(password_hash: str) -> bool:
    """Return whether a valid password hash uses outdated parameters."""
    try:
        return _PASSWORD_HASHER.check_needs_rehash(password_hash)
    except InvalidHashError:
        return False


def generate_session_token() -> str:
    """Generate an opaque browser session token."""
    return secrets.token_urlsafe(32)


def generate_api_key() -> tuple[str, str]:
    """Generate a bearer API key and its non-secret display prefix."""
    key = f"{_API_KEY_PREFIX}{secrets.token_urlsafe(32)}"
    return key, key[:13]


def hash_token(token: str) -> str:
    """Create the database representation of an opaque token."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
