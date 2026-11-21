import uuid
from datetime import datetime
from typing import Annotated

from pydantic import Field, StringConstraints

from app.models.enums import VehicleType
from app.schemas.common import ReadModel, UpdateModel, WriteModel
from app.schemas.flat import FlatSummary

PlateText = Annotated[str, StringConstraints(min_length=4, max_length=20)]
OptionalText = Annotated[str, StringConstraints(min_length=1, max_length=60)]


class VehicleCreate(WriteModel):
    flat_id: uuid.UUID
    plate: PlateText = Field(examples=["UP16 AB 1234"])
    vehicle_type: VehicleType
    make_model: OptionalText | None = Field(default=None, examples=["Maruti Swift"])
    colour: OptionalText | None = Field(default=None, examples=["White"])


class VehicleUpdate(UpdateModel):
    nullable_fields = frozenset({"make_model", "colour"})

    flat_id: uuid.UUID | None = None
    plate: PlateText | None = None
    vehicle_type: VehicleType | None = None
    make_model: OptionalText | None = None
    colour: OptionalText | None = None
    is_active: bool | None = None


class VehicleRead(ReadModel):
    id: uuid.UUID
    flat: FlatSummary
    plate_raw: str
    plate_normalized: str
    vehicle_type: VehicleType
    make_model: str | None
    colour: str | None
    is_active: bool
    created_at: datetime


# --- Watchlist ----------------------------------------------------------------


class WatchlistCreate(WriteModel):
    plate: PlateText = Field(examples=["HR26 DK 8337"])
    reason: Annotated[str, StringConstraints(min_length=3, max_length=255)]


class WatchlistUpdate(UpdateModel):
    reason: Annotated[str, StringConstraints(min_length=3, max_length=255)] | None = None
    is_active: bool | None = None


class WatchlistRead(ReadModel):
    id: uuid.UUID
    plate_normalized: str
    reason: str
    is_active: bool
    added_by_id: uuid.UUID | None
    created_at: datetime
