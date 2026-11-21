import uuid
from datetime import datetime

from pydantic import BaseModel

from app.models.enums import UserRole
from app.schemas.common import ReadModel, WriteModel
from app.schemas.flat import FlatSummary


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"  # noqa: S105 - OAuth2 token type name
    expires_in: int


class RefreshRequest(WriteModel):
    refresh_token: str


class CurrentUserResponse(ReadModel):
    id: uuid.UUID
    society_id: uuid.UUID
    email: str
    full_name: str
    phone: str | None
    role: UserRole
    last_login_at: datetime | None
    flats: list[FlatSummary] = []  # filled for residents


class DeviceIdentity(ReadModel):
    id: uuid.UUID
    name: str
    gate_id: uuid.UUID
    direction: str
