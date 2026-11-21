from pydantic import BaseModel, Field

from app.schemas.common import WriteModel


class VisitSettingsRead(BaseModel):
    guest_minutes: int
    delivery_minutes: int
    cab_minutes: int
    service_minutes: int = Field(description="Default when a resident doesn't set a duration")
    approval_timeout_seconds: int = Field(description="Time residents get before the guard decides")


class VisitSettingsUpdate(WriteModel):
    guest_minutes: int | None = Field(default=None, ge=5, le=24 * 60)
    delivery_minutes: int | None = Field(default=None, ge=5, le=240)
    cab_minutes: int | None = Field(default=None, ge=2, le=120)
    service_minutes: int | None = Field(default=None, ge=10, le=24 * 60)
    approval_timeout_seconds: int | None = Field(default=None, ge=30, le=1800)
