"""Schemas for people: guards and residents (both are users with a role)."""

import uuid
from datetime import datetime

from pydantic import Field

from app.models.enums import ResidentType
from app.schemas.common import (
    LowerEmail,
    Name,
    Password,
    Phone,
    ReadModel,
    UpdateModel,
    WriteModel,
)
from app.schemas.flat import FlatSummary


class UserSummary(ReadModel):
    id: uuid.UUID
    email: str
    full_name: str
    phone: str | None
    is_active: bool


# --- Guards -------------------------------------------------------------------


class GuardCreate(WriteModel):
    full_name: Name = Field(examples=["Ramesh Yadav"])
    email: LowerEmail
    phone: Phone | None = None
    password: Password


class GuardUpdate(UpdateModel):
    nullable_fields = frozenset({"phone"})

    full_name: Name | None = None
    phone: Phone | None = None
    is_active: bool | None = None


class GuardRead(ReadModel):
    id: uuid.UUID
    email: str
    full_name: str
    phone: str | None
    is_active: bool
    last_login_at: datetime | None
    created_at: datetime


# --- Residents ----------------------------------------------------------------


class ResidentCreate(WriteModel):
    flat_id: uuid.UUID
    full_name: Name = Field(examples=["Priya Sharma"])
    email: LowerEmail
    phone: Phone | None = None
    password: Password
    resident_type: ResidentType = ResidentType.OWNER
    is_primary_contact: bool = False


class ResidentUpdate(UpdateModel):
    nullable_fields = frozenset({"phone"})

    full_name: Name | None = None
    phone: Phone | None = None
    resident_type: ResidentType | None = None
    is_primary_contact: bool | None = None
    is_active: bool | None = None


class ResidentRead(ReadModel):
    id: uuid.UUID
    resident_type: ResidentType
    is_primary_contact: bool
    created_at: datetime
    user: UserSummary
    flat: FlatSummary
