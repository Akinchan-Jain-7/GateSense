"""Signed, expiring links for visitors: "how much time do I have left?"

The link holds a JWT signed with the server secret: the visit id and an expiry (2 hours
after the visit's time limit). It can't be forged or changed, needs no login, and stops
working on its own. Its `type` is `visit_link`, so it can never be used as a login token.
"""

import uuid
from datetime import UTC, datetime, timedelta

import jwt

from app.core.config import Settings

LINK_TYPE = "visit_link"
VALID_AFTER_LIMIT = timedelta(hours=2)


def make_token(settings: Settings, visit_id: uuid.UUID, expected_exit_at: datetime) -> str:
    payload = {
        "sub": str(visit_id),
        "type": LINK_TYPE,
        "iat": datetime.now(UTC),
        "exp": expected_exit_at + VALID_AFTER_LIMIT,
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def make_link(settings: Settings, visit_id: uuid.UUID, expected_exit_at: datetime) -> str:
    token = make_token(settings, visit_id, expected_exit_at)
    return f"{settings.public_base_url.rstrip('/')}/visit/{token}"


def read_token(settings: Settings, token: str) -> uuid.UUID | None:
    """The visit id, or None if the link is invalid, tampered with or expired."""
    try:
        payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
    except jwt.PyJWTError:
        return None
    if payload.get("type") != LINK_TYPE:
        return None
    try:
        return uuid.UUID(str(payload.get("sub")))
    except ValueError:
        return None
