"""Audit log helpers: every admin create/update/delete writes one `audit_logs` row.

The row is added to the same transaction as the change itself, so either both are saved
or neither is.
"""

import uuid
from enum import Enum
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditLog, User


def _jsonable(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, str | int | float | bool) or value is None:
        return value
    return str(value)  # UUIDs, datetimes


def apply_changes(obj: object, updates: dict[str, Any]) -> dict[str, list[Any]]:
    """Set attributes on `obj` and return what actually changed: {field: [old, new]}."""
    changes: dict[str, list[Any]] = {}
    for field, new_value in updates.items():
        old_value = getattr(obj, field)
        if old_value != new_value:
            setattr(obj, field, new_value)
            changes[field] = [_jsonable(old_value), _jsonable(new_value)]
    return changes


def snapshot(fields: dict[str, Any]) -> dict[str, Any]:
    """JSON-friendly copy of a new record's fields, for `*.create` entries."""
    return {key: _jsonable(value) for key, value in fields.items()}


def record(
    db: AsyncSession,
    actor: User,
    action: str,
    entity_id: uuid.UUID | None,
    changes: dict[str, Any] | None = None,
) -> None:
    """Add an audit entry. `action` looks like "vehicle.update"; the part before the dot
    is the entity type."""
    db.add(
        AuditLog(
            society_id=actor.society_id,
            actor_id=actor.id,
            action=action,
            entity_type=action.split(".", 1)[0],
            entity_id=entity_id,
            changes=changes or {},
        )
    )
