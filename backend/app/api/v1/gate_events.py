import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, File, Form, HTTPException, Query, Response, UploadFile, status

from app.api.deps import (
    AppSettings,
    CurrentDevice,
    DbSession,
    Pagination,
    RedisClient,
    SnapshotStore,
    StaffUser,
)
from app.models.enums import LaneDirection, MatchResult
from app.schemas.common import Page
from app.schemas.gate_event import GateEventIngestResponse, GateEventRead, ReviewDecision
from app.services import gate_events as service
from app.services.errors import NotFoundError
from app.services.storage import content_type_for

router = APIRouter(prefix="/gate-events", tags=["gate events"])


@router.post(
    "",
    response_model=GateEventIngestResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        200: {"model": GateEventIngestResponse, "description": "Duplicate or debounced read"},
        413: {"description": "Snapshot larger than SNAPSHOT_MAX_BYTES"},
    },
)
async def ingest_gate_event(
    response: Response,
    device: CurrentDevice,
    db: DbSession,
    redis: RedisClient,
    storage: SnapshotStore,
    settings: AppSettings,
    plate_text: Annotated[
        str, Form(min_length=1, max_length=32, description="Plate text as OCR read it")
    ],
    confidence: Annotated[float, Form(ge=0, le=1, description="OCR confidence, 0 to 1")],
    captured_at: Annotated[
        datetime | None,
        Form(description="When the camera saw the plate (ISO 8601 with timezone). Default: now"),
    ] = None,
    direction: Annotated[
        LaneDirection | None,
        Form(description="Optional check: must match the lane this device is registered for"),
    ] = None,
    snapshot: Annotated[
        UploadFile | None, File(description="JPEG, PNG or WebP image of the vehicle")
    ] = None,
) -> GateEventIngestResponse:
    """For cameras (send the device key in `X-Device-Key`): report one plate read.

    Send it as `multipart/form-data`. Retrying the same read is safe: you get the original
    event back with `status: duplicate`.
    """
    if direction is not None and direction is not device.direction:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"This device is registered for the {device.direction.value} lane",
        )
    data = None
    if snapshot is not None:
        # Read one byte past the limit: enough to know it's too big, without reading it all.
        data = await snapshot.read(settings.snapshot_max_bytes + 1)
        if len(data) > settings.snapshot_max_bytes:
            raise HTTPException(
                status.HTTP_413_CONTENT_TOO_LARGE,
                detail=f"Snapshot is larger than {settings.snapshot_max_bytes} bytes",
            )
    read = service.PlateRead(
        plate_text=plate_text,
        confidence=confidence,
        captured_at=captured_at or datetime.now(UTC),
        snapshot=data,
    )
    result = await service.ingest_read(db, redis, storage, settings, device, read)
    if result.status != "created":
        response.status_code = status.HTTP_200_OK
    event = GateEventRead.model_validate(result.event) if result.event else None
    return GateEventIngestResponse(status=result.status, event=event)


@router.get("", response_model=Page[GateEventRead])
async def list_gate_events(
    staff: StaffUser,
    db: DbSession,
    page: Pagination,
    direction: LaneDirection | None = None,
    match_result: MatchResult | None = None,
    needs_review: bool | None = None,
    gate_id: uuid.UUID | None = None,
    q: Annotated[str | None, Query(description="Part of a plate")] = None,
    since: Annotated[datetime | None, Query(description="Captured at or after")] = None,
    until: Annotated[datetime | None, Query(description="Captured before")] = None,
) -> Page[GateEventRead]:
    """Gate events, newest first."""
    result = await service.list_events(
        db,
        staff,
        page,
        direction=direction,
        match_result=match_result,
        needs_review=needs_review,
        gate_id=gate_id,
        q=q,
        since=since,
        until=until,
    )
    return Page[GateEventRead].model_validate(result, from_attributes=True)


# Declared before "/{event_id}" so "review-queue" isn't read as an event id.
@router.get("/review-queue", response_model=Page[GateEventRead])
async def review_queue(staff: StaffUser, db: DbSession, page: Pagination) -> Page[GateEventRead]:
    """Reads that need a guard: unsure, unreadable or ambiguous. Newest first."""
    result = await service.review_queue(db, staff, page)
    return Page[GateEventRead].model_validate(result, from_attributes=True)


@router.get("/{event_id}", response_model=GateEventRead)
async def get_gate_event(event_id: uuid.UUID, staff: StaffUser, db: DbSession) -> GateEventRead:
    return GateEventRead.model_validate(await service.get_event(db, staff, event_id))


@router.get(
    "/{event_id}/snapshot",
    response_class=Response,
    responses={200: {"content": {"image/jpeg": {}, "image/png": {}, "image/webp": {}}}},
)
async def get_snapshot(
    event_id: uuid.UUID, staff: StaffUser, db: DbSession, storage: SnapshotStore
) -> Response:
    """The plate snapshot image of an event."""
    event = await service.get_event(db, staff, event_id)
    if event.snapshot_path is None:
        raise NotFoundError("This event has no snapshot")
    data = await storage.load(event.snapshot_path)
    return Response(
        content=data,
        media_type=content_type_for(event.snapshot_path),
        headers={"Cache-Control": "private, max-age=3600"},
    )


@router.post("/{event_id}/review", response_model=GateEventRead)
async def review_gate_event(
    event_id: uuid.UUID,
    body: ReviewDecision,
    staff: StaffUser,
    db: DbSession,
    settings: AppSettings,
) -> GateEventRead:
    """Resolve a review item. `correct` re-runs matching with the given plate (resident
    entry/exit, visitor entry/exit, watchlist) and saves it as labelled OCR data."""
    plate = body.plate if body.action == "correct" else None
    event = await service.review_event(db, settings, staff, event_id, plate)
    return GateEventRead.model_validate(event)
