"""All models, imported here so `Base.metadata` knows every table (Alembic needs this)."""

from app.models.audit import AuditLog
from app.models.gate import Alert, Device, Gate, GateEvent, PlateCorrection
from app.models.notification import Notification
from app.models.society import Flat, Society, SocietySettings
from app.models.user import RefreshToken, Resident, User
from app.models.vehicle import Vehicle, WatchlistEntry
from app.models.visit import (
    Approval,
    EscalationTask,
    GuestPass,
    Visit,
    Visitor,
    VisitStatusChange,
)

__all__ = [
    "Alert",
    "Approval",
    "AuditLog",
    "Device",
    "EscalationTask",
    "Flat",
    "Gate",
    "GateEvent",
    "GuestPass",
    "Notification",
    "PlateCorrection",
    "RefreshToken",
    "Resident",
    "Society",
    "SocietySettings",
    "User",
    "Vehicle",
    "Visit",
    "VisitStatusChange",
    "Visitor",
    "WatchlistEntry",
]
