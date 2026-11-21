"""Passwords, JWTs and device API keys.

- Passwords: Argon2id (slow on purpose, so stolen hashes are expensive to crack).
- Login sessions: short-lived JWT access tokens + longer-lived refresh tokens.
- Devices: random API keys. Only a SHA-256 hash is stored. A fast hash is fine here
  because the key is 32 random bytes, so there is nothing to guess (unlike a password).
"""

import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

from app.core.config import Settings

TokenType = Literal["access", "refresh"]

_password_hasher = PasswordHasher()

# Verified against when the email doesn't exist, so a login for an unknown email takes
# as long as one with a wrong password (attackers can't time which emails are registered).
_DUMMY_PASSWORD_HASH = _password_hasher.hash("not-a-real-password")

DEVICE_KEY_PREFIX = "gsd_"  # "GateSense device": makes a leaked key easy to recognise


def hash_password(password: str) -> str:
    return _password_hasher.hash(password)


def verify_password(password: str, password_hash: str | None) -> bool:
    """Check a password. Pass `None` for an unknown user: we still do the slow check."""
    try:
        matches = _password_hasher.verify(password_hash or _DUMMY_PASSWORD_HASH, password)
    except (VerificationError, InvalidHashError):
        return False
    return matches and password_hash is not None


def password_needs_rehash(password_hash: str) -> bool:
    """True when Argon2 settings changed since this hash was made (we then re-hash)."""
    return _password_hasher.check_needs_rehash(password_hash)


@dataclass(frozen=True)
class TokenClaims:
    subject: uuid.UUID  # user id
    token_type: TokenType
    jti: uuid.UUID  # unique token id
    expires_at: datetime


class InvalidTokenError(Exception):
    """The token is malformed, expired, has a bad signature, or is the wrong type."""


def create_token(
    settings: Settings,
    user_id: uuid.UUID,
    token_type: TokenType,
    *,
    now: datetime | None = None,
) -> tuple[str, TokenClaims]:
    issued_at = now or datetime.now(UTC)
    lifetime = (
        timedelta(minutes=settings.access_token_expire_minutes)
        if token_type == "access"  # noqa: S105 - token kind, not a password
        else timedelta(days=settings.refresh_token_expire_days)
    )
    claims = TokenClaims(
        subject=user_id,
        token_type=token_type,
        jti=uuid.uuid4(),
        expires_at=issued_at + lifetime,
    )
    payload = {
        "sub": str(claims.subject),
        "type": claims.token_type,
        "jti": str(claims.jti),
        "iat": issued_at,
        "exp": claims.expires_at,
    }
    token = jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)
    return token, claims


def decode_token(settings: Settings, token: str, expected_type: TokenType) -> TokenClaims:
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret_key,
            # Pin the algorithm: never let the token itself choose (e.g. "none").
            algorithms=[settings.jwt_algorithm],
            options={"require": ["sub", "type", "jti", "exp"]},
        )
        claims = TokenClaims(
            subject=uuid.UUID(payload["sub"]),
            token_type=payload["type"],
            jti=uuid.UUID(payload["jti"]),
            expires_at=datetime.fromtimestamp(payload["exp"], tz=UTC),
        )
    except (jwt.PyJWTError, ValueError, KeyError) as exc:
        raise InvalidTokenError(str(exc)) from exc
    # An access token must not be usable as a refresh token, and vice versa.
    if claims.token_type != expected_type:
        raise InvalidTokenError(f"expected a {expected_type} token")
    return claims


@dataclass(frozen=True)
class DeviceKey:
    plaintext: str  # shown to the admin once, never stored
    hash: str
    prefix: str


def hash_api_key(api_key: str) -> str:
    return hashlib.sha256(api_key.encode()).hexdigest()


def generate_device_key() -> DeviceKey:
    plaintext = DEVICE_KEY_PREFIX + secrets.token_urlsafe(32)
    return DeviceKey(
        plaintext=plaintext,
        hash=hash_api_key(plaintext),
        prefix=plaintext[: len(DEVICE_KEY_PREFIX) + 6],
    )
