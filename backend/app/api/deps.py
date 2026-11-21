"""FastAPI dependencies: database, Redis, storage, settings, current user, roles, devices.

Role-based access control (RBAC) lives here. A route declares who may call it by
asking for a typed user, e.g. `admin: AdminUser`. FastAPI runs the check before the
route body, so a guard calling an admin route gets 403 and the route never runs.
"""

from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import Depends, HTTPException, Query, Request, Security, status
from fastapi.security import APIKeyHeader, OAuth2PasswordBearer
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.security import InvalidTokenError, decode_token
from app.db.session import get_db
from app.models import Device, User
from app.models.enums import UserRole
from app.services import gates as gates_service
from app.services.pagination import PageRequest
from app.services.storage import SnapshotStorage

DbSession = Annotated[AsyncSession, Depends(get_db)]
AppSettings = Annotated[Settings, Depends(get_settings)]


def get_redis(request: Request) -> Redis:
    """The Redis client created at start-up (see `lifespan` in main.py)."""
    redis: Redis = request.app.state.redis
    return redis


def get_snapshot_storage(request: Request) -> SnapshotStorage:
    """Where plate snapshots go: a local folder or S3, chosen by settings at start-up."""
    storage: SnapshotStorage = request.app.state.snapshot_storage
    return storage


RedisClient = Annotated[Redis, Depends(get_redis)]
SnapshotStore = Annotated[SnapshotStorage, Depends(get_snapshot_storage)]

# tokenUrl powers the "Authorize" button in /docs (it posts the login form there).
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login", auto_error=False)
device_key_header = APIKeyHeader(
    name="X-Device-Key", auto_error=False, description="API key of a gate camera device"
)


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


async def get_current_user(
    db: DbSession,
    settings: AppSettings,
    token: Annotated[str | None, Security(oauth2_scheme)],
) -> User:
    if token is None:
        raise _unauthorized("Not authenticated")
    try:
        claims = decode_token(settings, token, expected_type="access")
    except InvalidTokenError as exc:
        raise _unauthorized("Invalid or expired access token") from exc
    # Load the user on every request (one primary-key lookup), so deactivating a user
    # locks them out at once instead of when their token expires.
    user = await db.get(User, claims.subject)
    if user is None or not user.is_active:
        raise _unauthorized("User not found or deactivated")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_roles(*roles: UserRole) -> Callable[[User], Awaitable[User]]:
    """Dependency factory: `Depends(require_roles(UserRole.ADMIN))`."""

    async def check(user: CurrentUser) -> User:
        if user.role not in roles:
            allowed = ", ".join(role.value for role in roles)
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"This action needs one of these roles: {allowed}",
            )
        return user

    return check


AdminUser = Annotated[User, Depends(require_roles(UserRole.ADMIN))]
# Admins and guards: e.g. a guard looks up flats and vehicles at the gate.
StaffUser = Annotated[User, Depends(require_roles(UserRole.ADMIN, UserRole.GUARD))]


async def get_current_device(
    db: DbSession, api_key: Annotated[str | None, Security(device_key_header)]
) -> Device:
    if api_key is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Missing X-Device-Key header")
    return await gates_service.authenticate_device(db, api_key)


CurrentDevice = Annotated[Device, Depends(get_current_device)]


def page_params(
    settings: AppSettings,
    limit: Annotated[int | None, Query(ge=1, description="Page size")] = None,
    offset: Annotated[int, Query(ge=0, description="Records to skip")] = 0,
) -> PageRequest:
    size = min(limit or settings.default_page_size, settings.max_page_size)
    return PageRequest(limit=size, offset=offset)


Pagination = Annotated[PageRequest, Depends(page_params)]
