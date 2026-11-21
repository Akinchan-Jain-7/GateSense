"""Guards are users with role=guard. They are deactivated, never deleted."""

import uuid

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password
from app.models import User
from app.models.enums import UserRole
from app.schemas.user import GuardCreate, GuardUpdate
from app.services import audit
from app.services.auth import revoke_all_sessions
from app.services.db_helpers import integrity_guard
from app.services.errors import NotFoundError
from app.services.pagination import PageRequest, PageResult, paginate


async def list_guards(
    db: AsyncSession,
    actor: User,
    page: PageRequest,
    *,
    q: str | None = None,
    is_active: bool | None = None,
) -> PageResult[User]:
    statement = (
        select(User)
        .where(User.society_id == actor.society_id, User.role == UserRole.GUARD)
        .order_by(User.full_name)
    )
    if q:
        pattern = f"%{q.strip()}%"
        statement = statement.where(or_(User.full_name.ilike(pattern), User.email.ilike(pattern)))
    if is_active is not None:
        statement = statement.where(User.is_active == is_active)
    return await paginate(db, statement, page)


async def get_guard(db: AsyncSession, actor: User, guard_id: uuid.UUID) -> User:
    guard = await db.get(User, guard_id)
    if guard is None or guard.society_id != actor.society_id or guard.role != UserRole.GUARD:
        raise NotFoundError("Guard not found")
    return guard


async def create_guard(db: AsyncSession, actor: User, data: GuardCreate) -> User:
    guard = User(
        society_id=actor.society_id,
        email=data.email,
        full_name=data.full_name,
        phone=data.phone,
        role=UserRole.GUARD,
        password_hash=hash_password(data.password),
    )
    async with integrity_guard(db, f"A user with email {data.email} already exists"):
        db.add(guard)
    # Never put the password (or its hash) in the audit log.
    audit.record(
        db, actor, "guard.create", guard.id, audit.snapshot(data.model_dump(exclude={"password"}))
    )
    await db.commit()
    return guard


async def update_guard(
    db: AsyncSession, actor: User, guard_id: uuid.UUID, data: GuardUpdate
) -> User:
    guard = await get_guard(db, actor, guard_id)
    changes = audit.apply_changes(guard, data.changes())
    if changes.get("is_active") == [True, False]:
        await revoke_all_sessions(db, guard.id)
    if changes:
        audit.record(db, actor, "guard.update", guard.id, changes)
    await db.commit()
    return guard


async def deactivate_guard(db: AsyncSession, actor: User, guard_id: uuid.UUID) -> None:
    guard = await get_guard(db, actor, guard_id)
    if guard.is_active:
        guard.is_active = False
        await revoke_all_sessions(db, guard.id)
        audit.record(db, actor, "guard.deactivate", guard.id)
    await db.commit()
