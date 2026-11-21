import uuid
from dataclasses import dataclass
from enum import StrEnum

from app.services.audit import apply_changes, snapshot


class Colour(StrEnum):
    RED = "red"
    BLUE = "blue"


@dataclass
class Thing:
    name: str
    colour: Colour
    owner: uuid.UUID | None


def test_apply_changes_returns_only_real_changes() -> None:
    thing = Thing(name="car", colour=Colour.RED, owner=None)
    owner = uuid.uuid4()

    changes = apply_changes(thing, {"name": "car", "colour": Colour.BLUE, "owner": owner})

    assert thing.colour is Colour.BLUE
    assert changes == {"colour": ["red", "blue"], "owner": [None, str(owner)]}


def test_snapshot_makes_values_json_friendly() -> None:
    owner = uuid.uuid4()
    assert snapshot({"colour": Colour.RED, "owner": owner, "n": 3}) == {
        "colour": "red",
        "owner": str(owner),
        "n": 3,
    }
