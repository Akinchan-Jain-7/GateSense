import uuid
from datetime import datetime

from pydantic import BaseModel, Field, field_validator, model_validator

from app.models.enums import VisitCategory
from app.schemas.common import WriteModel
from app.schemas.visit import clean_phone, mask_phone


class GuestPassCreate(WriteModel):
    """Created by a resident ahead of time. Give a plate, ask for a code, or both."""

    guest_name: str = Field(min_length=2, max_length=120, examples=["Priya Nair"])
    guest_phone: str | None = None
    category: VisitCategory = VisitCategory.GUEST
    flat_id: uuid.UUID | None = Field(
        default=None, description="Needed only for multi-flat residents"
    )
    plate: str | None = Field(default=None, max_length=20, examples=["KA05MN0042"])
    with_code: bool = Field(
        default=False, description="Also create a one-time code to show the guard"
    )
    valid_from: datetime
    valid_until: datetime
    max_uses: int = Field(default=1, ge=1, le=50)

    @field_validator("guest_phone")
    @classmethod
    def _phone(cls, value: str | None) -> str | None:
        return clean_phone(value) if value else None

    @model_validator(mode="after")
    def _check(self) -> "GuestPassCreate":
        if not self.plate and not self.with_code:
            raise ValueError("Give the guest's plate, or set with_code to get a code")
        if self.valid_from.tzinfo is None or self.valid_until.tzinfo is None:
            raise ValueError("valid_from and valid_until need a timezone")
        if self.valid_until <= self.valid_from:
            raise ValueError("valid_until must be after valid_from")
        if (self.valid_until - self.valid_from).days > 30:
            raise ValueError("A guest pass can be valid for at most 30 days")
        return self


class GuestPassRead(BaseModel):
    id: uuid.UUID
    flat_id: uuid.UUID
    guest_name: str
    guest_phone: str | None
    category: VisitCategory
    plate_normalized: str | None
    has_code: bool
    valid_from: datetime
    valid_until: datetime
    max_uses: int
    use_count: int
    revoked_at: datetime | None
    created_at: datetime

    @field_validator("guest_phone", mode="before")
    @classmethod
    def _mask(cls, value: str | None) -> str | None:
        return mask_phone(value)


class GuestPassCreated(BaseModel):
    guest_pass: GuestPassRead
    code: str | None = Field(description="Shown only now; only a hash is stored")


class CodeRedemption(WriteModel):
    code: str = Field(min_length=6, max_length=12, examples=["K7QM2XRT"])
    plate: str | None = Field(default=None, max_length=20)
