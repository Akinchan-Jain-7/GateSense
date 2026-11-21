import uuid
from datetime import datetime
from typing import Annotated

from pydantic import Field, StringConstraints

from app.models.enums import LaneDirection
from app.schemas.common import ReadModel, ShortText, UpdateModel, WriteModel

Location = Annotated[str, StringConstraints(min_length=1, max_length=255)]


class GateCreate(WriteModel):
    name: ShortText = Field(examples=["Main Gate"])
    location: Location | None = None


class GateUpdate(UpdateModel):
    nullable_fields = frozenset({"location"})

    name: ShortText | None = None
    location: Location | None = None
    is_active: bool | None = None


class GateRead(ReadModel):
    id: uuid.UUID
    name: str
    location: str | None
    is_active: bool
    created_at: datetime


class DeviceCreate(WriteModel):
    gate_id: uuid.UUID
    name: ShortText = Field(examples=["Main Gate - entry camera"])
    direction: LaneDirection


class DeviceUpdate(UpdateModel):
    name: ShortText | None = None
    direction: LaneDirection | None = None
    is_active: bool | None = None


class DeviceRead(ReadModel):
    id: uuid.UUID
    gate_id: uuid.UUID
    name: str
    direction: LaneDirection
    api_key_prefix: str = Field(description="First characters of the key, to tell keys apart")
    is_active: bool
    last_seen_at: datetime | None
    created_at: datetime


class DeviceWithKey(DeviceRead):
    api_key: str = Field(
        description="Shown only once. Store it on the device; GateSense keeps only a hash."
    )
