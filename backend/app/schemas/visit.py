import re
import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator

from app.models.enums import ApprovalChannel, ApprovalStatus, VisitCategory, VisitStatus
from app.schemas.common import WriteModel

PHONE = re.compile(r"^(\+91)?[6-9]\d{9}$")


def clean_phone(value: str) -> str:
    """'+91 98765-43210' -> '+919876543210'. Indian mobile numbers only."""
    digits = re.sub(r"[\s\-()]", "", value)
    if not PHONE.match(digits):
        raise ValueError("Enter a 10-digit Indian mobile number, e.g. 98765 43210")
    return digits if digits.startswith("+91") else "+91" + digits


def mask_phone(phone: str | None) -> str | None:
    """'+919876543210' -> '+91 98•••••210': lists show enough to recognise, not to copy."""
    if not phone:
        return None
    local = phone.removeprefix("+91")
    return f"+91 {local[:2]}{'•' * (len(local) - 5)}{local[-3:]}"


class VisitorRegistration(WriteModel):
    """A guard registers a visitor at the gate; the flat's residents are asked to approve."""

    full_name: str = Field(min_length=2, max_length=120, examples=["Rohit Sharma"])
    phone: str = Field(examples=["98765 43210"])
    email: EmailStr | None = None
    flat_id: uuid.UUID
    category: VisitCategory = VisitCategory.GUEST
    purpose: str | None = Field(default=None, max_length=255, examples=["Family visit"])
    plate: str | None = Field(default=None, max_length=20, examples=["DL01AB1234"])
    duration_minutes: int | None = Field(
        default=None, ge=10, le=24 * 60, description="Service visits: the agreed duration"
    )
    gate_event_id: uuid.UUID | None = Field(
        default=None,
        description="The unknown entry read this visitor came in with: on approval the car "
        "is admitted at once",
    )

    @field_validator("phone")
    @classmethod
    def _phone(cls, value: str) -> str:
        return clean_phone(value)

    @model_validator(mode="after")
    def _duration_only_for_service(self) -> "VisitorRegistration":
        if self.duration_minutes is not None and self.category is not VisitCategory.SERVICE:
            raise ValueError("duration_minutes is only for service visits")
        return self


class Decision(WriteModel):
    decision: Literal["approve", "deny"]


class VisitRead(BaseModel):
    id: uuid.UUID
    flat_id: uuid.UUID
    flat_label: str
    category: VisitCategory
    status: VisitStatus
    purpose: str | None
    plate_normalized: str | None
    visitor_name: str | None
    visitor_phone: str | None = Field(description="Masked, e.g. +91 98•••••210")
    guest_pass_id: uuid.UUID | None
    duration_minutes: int | None
    entered_at: datetime | None
    expected_exit_at: datetime | None
    exited_at: datetime | None
    approved_by_id: uuid.UUID | None
    registered_by_id: uuid.UUID | None
    entry_event_id: uuid.UUID | None
    created_at: datetime


class ApprovalRead(BaseModel):
    id: uuid.UUID
    status: ApprovalStatus
    requested_at: datetime
    expires_at: datetime
    decided_at: datetime | None
    decided_by_id: uuid.UUID | None
    channel: ApprovalChannel | None
    visit: VisitRead


class VisitRegistered(BaseModel):
    visit: VisitRead
    approval: ApprovalRead
