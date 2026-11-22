from pydantic import BaseModel, Field

from app.schemas.common import WriteModel


class VisitSettingsRead(BaseModel):
    guest_minutes: int
    delivery_minutes: int
    cab_minutes: int
    service_minutes: int = Field(description="Default when a resident doesn't set a duration")
    approval_timeout_seconds: int = Field(description="Time residents get before the guard decides")
    visitor_retention_days: int = Field(description="Visitor personal data is deleted after this")
    plate_confidence_threshold: float = Field(
        description="OCR reads below this go to the guard review queue"
    )
    visitor_parking_slots: int = Field(description="Parking spaces kept for visitors")


class VisitSettingsUpdate(WriteModel):
    guest_minutes: int | None = Field(default=None, ge=5, le=24 * 60)
    delivery_minutes: int | None = Field(default=None, ge=5, le=240)
    cab_minutes: int | None = Field(default=None, ge=2, le=120)
    service_minutes: int | None = Field(default=None, ge=10, le=24 * 60)
    approval_timeout_seconds: int | None = Field(default=None, ge=30, le=1800)
    visitor_retention_days: int | None = Field(default=None, ge=7, le=3650)
    plate_confidence_threshold: float | None = Field(default=None, ge=0.3, le=0.99)
    visitor_parking_slots: int | None = Field(default=None, ge=0, le=500)
