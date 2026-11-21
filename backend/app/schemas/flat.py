import uuid
from datetime import datetime
from typing import Annotated

from pydantic import Field, StringConstraints

from app.schemas.common import ReadModel, UpdateModel, WriteModel

Block = Annotated[str, StringConstraints(min_length=1, max_length=8, to_upper=True)]
FlatNumber = Annotated[str, StringConstraints(min_length=1, max_length=8, to_upper=True)]


class FlatSummary(ReadModel):
    id: uuid.UUID
    label: str


class FlatCreate(WriteModel):
    block: Block = Field(examples=["B"])
    number: FlatNumber = Field(examples=["402"])
    floor: int | None = Field(default=None, ge=0, le=200)
    parking_slots: int = Field(default=1, ge=0, le=20)


class FlatUpdate(UpdateModel):
    nullable_fields = frozenset({"floor"})

    block: Block | None = None
    number: FlatNumber | None = None
    floor: int | None = Field(default=None, ge=0, le=200)
    parking_slots: int | None = Field(default=None, ge=0, le=20)


class FlatRead(ReadModel):
    id: uuid.UUID
    block: str
    number: str
    label: str
    floor: int | None
    parking_slots: int
    created_at: datetime
