import uuid
from datetime import date, datetime

from pydantic import BaseModel, Field

from app.models.enums import VisitCategory
from app.schemas.common import ReadModel


class HourCountRead(ReadModel):
    hour: int = Field(description="Hour of the day in IST, 0-23")
    residents: int
    visitors: int


class DayCountRead(ReadModel):
    day: date
    visits: int


class CategoryStatRead(ReadModel):
    category: VisitCategory
    visits: int
    average_minutes: float | None


class FrequentVisitorRead(ReadModel):
    visitor_id: uuid.UUID
    name: str
    phone_masked: str
    visits: int
    last_visit_at: datetime
    flats: list[str]


class AnalyticsOverview(ReadModel):
    days: int
    since: datetime
    visits: int = Field(description="Visits that entered in the window")
    average_visit_minutes: float | None
    overstayed_visits: int
    overstay_rate: float | None = Field(description="0-1; null when no visits entered")
    vehicles_inside: int
    visitors_inside: int
    residents_inside: int
    visitor_vehicles_inside: int
    visitor_parking_slots: int
    busiest_hours: list[HourCountRead]
    daily_visits: list[DayCountRead]
    categories: list[CategoryStatRead]
    frequent_visitors: list[FrequentVisitorRead]


class InsideNowRead(ReadModel):
    vehicles_inside: int
    visitors_inside: int
    residents_inside: int
    visitor_vehicles_inside: int
    visitor_parking_slots: int


class AuditActor(ReadModel):
    id: uuid.UUID
    full_name: str


class AuditLogRead(ReadModel):
    id: uuid.UUID
    action: str
    entity_type: str
    entity_id: uuid.UUID | None
    changes: dict[str, object]
    created_at: datetime
    actor: AuditActor | None


class DemoAccount(BaseModel):
    role: str
    email: str
    name: str


class DemoInfo(BaseModel):
    enabled: bool
    password: str | None = Field(description="The shared demo password (only in demo mode)")
    accounts: list[DemoAccount]


class DemoResetResult(BaseModel):
    flats: int
    residents: int
    vehicles: int
    history_visits: int
    history_gate_events: int
