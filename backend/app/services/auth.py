"""Login, token refresh (with rotation) and logout.

Access token: lives 15 minutes, sent on every request, never stored by us.
Refresh token: lives 7 days, used only to get a new pair. Each one is stored (by its
`jti`) and works exactly once: refreshing revokes the old token and issues a new one.
If a revoked refresh token is used again, someone may have stolen it, so we revoke
every session of that user ("reuse detection").
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.security import (
    InvalidTokenError,
    create_token,
    decode_token,
    hash_password,
    password_needs_rehash,
    verify_password,
)
from app.models import RefreshToken, User
from app.services.errors import AuthenticationError


@dataclass(frozen=True)
class TokenPair:
    access_token: str
    refresh_token: str
    expires_in: int  # seconds until the access token expires


async def authenticate(db: AsyncSession, email: str, password: str) -> User:
    user = await db.scalar(select(User).where(User.email == email.strip().lower()))
    # Always run the (slow) password check, even for unknown emails, then give the same
    # error for "no such user", "wrong password" and "deactivated". The response and its
    # timing never reveal which emails are registered.
    password_ok = verify_password(password, user.password_hash if user else None)
    if user is None or not password_ok or not user.is_active:
        raise AuthenticationError("Incorrect email or password")

    if password_needs_rehash(user.password_hash):
        user.password_hash = hash_password(password)
    user.last_login_at = datetime.now(UTC)
    return user


async def issue_tokens(db: AsyncSession, settings: Settings, user: User) -> TokenPair:
    access_token, _ = create_token(settings, user.id, "access")
    refresh_token, refresh_claims = create_token(settings, user.id, "refresh")
    db.add(
        RefreshToken(jti=refresh_claims.jti, user_id=user.id, expires_at=refresh_claims.expires_at)
    )
    await db.commit()
    return TokenPair(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=settings.access_token_expire_minutes * 60,
    )


async def login(db: AsyncSession, settings: Settings, email: str, password: str) -> TokenPair:
    user = await authenticate(db, email, password)
    return await issue_tokens(db, settings, user)


async def _stored_refresh_token(
    db: AsyncSession, settings: Settings, refresh_token: str
) -> RefreshToken:
    try:
        claims = decode_token(settings, refresh_token, expected_type="refresh")
    except InvalidTokenError as exc:
        raise AuthenticationError("Invalid refresh token") from exc
    stored = await db.get(RefreshToken, claims.jti)
    if stored is None or stored.user_id != claims.subject:
        raise AuthenticationError("Invalid refresh token")
    return stored


async def refresh(db: AsyncSession, settings: Settings, refresh_token: str) -> TokenPair:
    stored = await _stored_refresh_token(db, settings, refresh_token)

    if stored.revoked_at is not None:
        await revoke_all_sessions(db, stored.user_id)
        await db.commit()
        raise AuthenticationError("Refresh token already used; please log in again")

    user = await db.get(User, stored.user_id)
    if user is None or not user.is_active:
        raise AuthenticationError("Invalid refresh token")

    stored.revoked_at = datetime.now(UTC)
    return await issue_tokens(db, settings, user)


async def logout(db: AsyncSession, settings: Settings, refresh_token: str) -> None:
    stored = await _stored_refresh_token(db, settings, refresh_token)
    if stored.revoked_at is None:
        stored.revoked_at = datetime.now(UTC)
    await db.commit()


async def revoke_all_sessions(db: AsyncSession, user_id: uuid.UUID) -> None:
    """Revoke every refresh token of a user (used on reuse detection and deactivation)."""
    await db.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=datetime.now(UTC))
    )
