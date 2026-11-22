import uuid
from datetime import datetime

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import select

from app.api.deps import AdminUser, DbSession, Pagination
from app.models import Notification
from app.models.enums import NotificationChannel, NotificationStatus
from app.schemas.common import Page
from app.services.pagination import paginate

router = APIRouter(prefix="/notifications", tags=["notifications"])


class NotificationRead(BaseModel):
    id: uuid.UUID
    channel: NotificationChannel
    kind: str
    recipient: str
    subject: str | None
    status: NotificationStatus
    attempts: int
    last_error: str | None
    visit_id: uuid.UUID | None
    created_at: datetime
    sent_at: datetime | None
    next_attempt_at: datetime | None


@router.get("", response_model=Page[NotificationRead])
async def list_notifications(
    admin: AdminUser, db: DbSession, page: Pagination, status: NotificationStatus | None = None
) -> Page[NotificationRead]:
    """The log of emails and Telegram messages (newest first), for checking delivery."""
    statement = (
        select(Notification)
        .where(Notification.society_id == admin.society_id)
        .order_by(Notification.created_at.desc())
    )
    if status:
        statement = statement.where(Notification.status == status)
    result = await paginate(db, statement, page)
    return Page[NotificationRead].model_validate(result, from_attributes=True)
