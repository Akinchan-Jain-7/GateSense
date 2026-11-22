import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.models.enums import EscalationOutcome, EscalationTaskStatus, ReconciliationKind
from app.schemas.common import WriteModel
from app.schemas.visit import VisitRead


class EscalationRead(BaseModel):
    id: uuid.UUID
    status: EscalationTaskStatus
    outcome: EscalationOutcome | None
    notes: str | None
    created_at: datetime
    resolved_at: datetime | None
    resolved_by_id: uuid.UUID | None
    visit: VisitRead


class EscalationResolution(WriteModel):
    outcome: EscalationOutcome = Field(
        description="reached: spoke to the resident. not_reached: no answer. "
        "vehicle_left: the car is gone (also closes the visit)."
    )
    notes: str | None = Field(default=None, max_length=500)


class ReconciliationFlagRead(BaseModel):
    id: uuid.UUID
    kind: ReconciliationKind
    gate_event_id: uuid.UUID | None
    visit_id: uuid.UUID | None
    details: str
    created_at: datetime
    resolved_at: datetime | None
    resolved_by_id: uuid.UUID | None
