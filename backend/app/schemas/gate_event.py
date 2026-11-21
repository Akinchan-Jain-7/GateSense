import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from app.models.enums import (
    AlertKind,
    AlertSeverity,
    LaneDirection,
    MatchResult,
    ReviewReason,
)
from app.schemas.common import ReadModel, WriteModel


class GateEventRead(ReadModel):
    id: uuid.UUID
    gate_id: uuid.UUID
    device_id: uuid.UUID
    direction: LaneDirection
    plate_raw: str = Field(description="Exactly what OCR read")
    plate_normalized: str | None = Field(description="The repaired plate; null if unreadable")
    ocr_fixes: int | None = Field(description="Look-alike characters swapped (O→0, B→8…)")
    confidence: float
    captured_at: datetime
    received_at: datetime
    match_result: MatchResult
    match_distance: int | None = Field(description="0 = exact match, 1 = one character off")
    vehicle_id: uuid.UUID | None
    visit_id: uuid.UUID | None
    paired_event_id: uuid.UUID | None = Field(
        description="On a resident exit: the entry event it closes"
    )
    needs_review: bool
    review_reason: ReviewReason | None
    reviewed_at: datetime | None
    reviewed_by_id: uuid.UUID | None
    has_snapshot: bool


class GateEventIngestResponse(BaseModel):
    status: Literal["created", "duplicate", "debounced"] = Field(
        description=(
            "created: a new event. duplicate: this exact read was already received "
            "(safe retry). debounced: the same plate was just seen on this lane, so the "
            "read was folded into that event."
        )
    )
    event: GateEventRead | None


class ReviewDecision(WriteModel):
    """A guard resolves a review item."""

    action: Literal["correct", "dismiss"] = Field(
        description="correct: give the right plate (also to confirm OCR was right). "
        "dismiss: not a vehicle / nothing to do."
    )
    plate: str | None = Field(default=None, max_length=20, examples=["DL01AB1234"])

    @model_validator(mode="after")
    def _plate_matches_action(self) -> "ReviewDecision":
        if self.action == "correct" and not self.plate:
            raise ValueError("'plate' is required when action is 'correct'")
        if self.action == "dismiss" and self.plate is not None:
            raise ValueError("leave 'plate' out when action is 'dismiss'")
        return self


class AlertRead(ReadModel):
    id: uuid.UUID
    kind: AlertKind
    severity: AlertSeverity
    message: str
    gate_event_id: uuid.UUID | None
    acknowledged_at: datetime | None
    acknowledged_by_id: uuid.UUID | None
    created_at: datetime
