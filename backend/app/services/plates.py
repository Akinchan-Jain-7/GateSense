"""Number-plate cleaning, validation, OCR repair and fuzzy matching.

Two kinds of input reach this module:

1. **Typed plates** (admin, residents, guards): we trust the characters, so we only strip
   spaces/dashes, upper-case and check the format (`normalize_typed_plate`).
2. **OCR reads** from cameras: characters that look alike get swapped (O/0, I/1, B/8, S/5,
   Z/2…). An Indian plate has a fixed grammar — letters here, digits there — so we can tell
   which one was meant *from its position* (`read_ocr_plate`). Whatever OCR still gets
   wrong, `closest_plates` catches by comparing against plates we already know.
"""

import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from itertools import product
from typing import Literal

from app.services.errors import InvalidInputError

# Standard plate: state (2 letters) + RTO district (1-2 digits) + series (0-3 letters)
# + number (1-4 digits). Examples: DL01AB1234, UP16Z5678, DL3CAB1234, KA05MN0042.
STANDARD_PLATE = re.compile(r"^(?P<state>[A-Z]{2})\d{1,2}[A-Z]{0,3}\d{1,4}$")

# Bharat (BH) series, for people who move states often: year (2 digits) + "BH"
# + number (4 digits) + 1-2 letters. Example: 22BH1234AA.
BH_PLATE = re.compile(r"^\d{2}BH\d{4}[A-Z]{1,2}$")

MAX_PLATE_LENGTH = 12

# Registration codes of every state and union territory, including older codes still on
# the road (OR → OD for Odisha, UA → UK for Uttarakhand, TS → TG for Telangana, DN/DD).
STATE_CODES = frozenset({
    "AN", "AP", "AR", "AS", "BR", "CG", "CH", "DD", "DL", "DN", "GA", "GJ", "HP", "HR",
    "JH", "JK", "KA", "KL", "LA", "LD", "MH", "ML", "MN", "MP", "MZ", "NL", "OD", "OR",
    "PB", "PY", "RJ", "SK", "TG", "TN", "TR", "TS", "UA", "UK", "UP", "WB",
})  # fmt: skip


def clean_plate(text: str) -> str:
    """'dl 01-ab 1234' -> 'DL01AB1234'. Keeps only letters and digits."""
    return re.sub(r"[^A-Z0-9]", "", text.upper())


def is_valid_plate(normalized: str) -> bool:
    if len(normalized) > MAX_PLATE_LENGTH:
        return False
    if BH_PLATE.match(normalized):
        return True
    standard = STANDARD_PLATE.match(normalized)
    return bool(standard and standard["state"] in STATE_CODES)


def normalize_typed_plate(text: str) -> str:
    """Clean a typed plate and reject it if it isn't a valid Indian format."""
    normalized = clean_plate(text)
    if not is_valid_plate(normalized):
        raise InvalidInputError(
            f"'{text}' is not a valid Indian number plate (e.g. DL01AB1234 or 22BH1234AA)"
        )
    return normalized


# --- OCR repair -----------------------------------------------------------------------

# What a wrongly-typed character most likely was. A letter in a digit slot is mapped with
# TO_DIGIT; a digit in a letter slot with TO_LETTER (some digits have two candidates).
TO_DIGIT = {
    "O": "0", "D": "0", "Q": "0",
    "I": "1", "L": "1",
    "Z": "2", "A": "4", "S": "5", "G": "6", "T": "7", "B": "8",
}  # fmt: skip
TO_LETTER = {
    "0": "OD", "1": "I", "2": "Z", "4": "A", "5": "S", "6": "G", "7": "T", "8": "B",
}  # fmt: skip

# More look-alike fixes than this and the read is too unreliable to trust.
MAX_FIXES = 3

# "IND" printed on high-security registration plates (HSRP); OCR sometimes includes it.
HSRP_PREFIX = "IND"

# Small penalties for plate shapes that are legal but uncommon. They only break ties
# between readings that need a similar number of fixes, e.g. "KAO5MNOO42" could be
# KA05MN0042 (3 fixes, normal shape) or KA05MNO042 (2 fixes, 3-letter series + 3-digit
# number). Modern plates almost always have a 4-digit number, so the first one wins.
_DISTRICT_PENALTY = {2: 0.0, 1: 0.25}
_SERIES_PENALTY = {2: 0.0, 1: 0.5, 3: 0.5, 0: 1.0}
_NUMBER_PENALTY = {4: 0.0, 3: 1.25, 2: 1.5, 1: 2.0}
_BH_SUFFIX_PENALTY = {2: 0.0, 1: 0.25}
# RTOs skip I, O and Q in series letters because they look like 1 and 0.
_RARE_SERIES_LETTERS = frozenset("IOQ")
_RARE_SERIES_PENALTY = 0.5

# A layout is a list of slots: "L" = letter, "D" = digit, or a literal character.
type Slot = Literal["L", "D"] | str


@dataclass(frozen=True)
class _Layout:
    slots: tuple[Slot, ...]
    kind: Literal["standard", "bh"]
    shape_penalty: float
    # Which positions hold series letters (for the rare-letter penalty).
    series_positions: frozenset[int]


def _standard_layouts() -> Iterator[_Layout]:
    for district, series, number in product((1, 2), (0, 1, 2, 3), (1, 2, 3, 4)):
        start = 2 + district
        yield _Layout(
            slots=("L", "L") + ("D",) * district + ("L",) * series + ("D",) * number,
            kind="standard",
            shape_penalty=_DISTRICT_PENALTY[district]
            + _SERIES_PENALTY[series]
            + _NUMBER_PENALTY[number],
            series_positions=frozenset(range(start, start + series)),
        )


def _bh_layouts() -> Iterator[_Layout]:
    for suffix in (1, 2):
        yield _Layout(
            slots=("D", "D", "B", "H", "D", "D", "D", "D") + ("L",) * suffix,
            kind="bh",
            shape_penalty=_BH_SUFFIX_PENALTY[suffix],
            series_positions=frozenset(range(8, 8 + suffix)),
        )


LAYOUTS: tuple[_Layout, ...] = (*_standard_layouts(), *_bh_layouts())


@dataclass(frozen=True)
class PlateReading:
    """The best valid plate we could make out of an OCR string."""

    plate: str
    kind: Literal["standard", "bh"]
    fixes: int  # how many look-alike characters were swapped
    score: float  # fixes + shape penalties; lower is more believable


def _options(char: str, slot: Slot) -> list[tuple[str, int]]:
    """Characters this position could really be, each with its cost (0 = as read)."""
    if slot == "D":
        if char.isdigit():
            return [(char, 0)]
        return [(TO_DIGIT[char], 1)] if char in TO_DIGIT else []
    if slot == "L":
        if char.isalpha():
            return [(char, 0)]
        return [(letter, 1) for letter in TO_LETTER.get(char, "")]
    # A literal, e.g. the "B" and "H" of a BH plate.
    if char == slot:
        return [(char, 0)]
    return [(slot, 1)] if slot in TO_LETTER.get(char, "") else []


def _readings_for(text: str, layout: _Layout) -> Iterator[PlateReading]:
    if len(text) != len(layout.slots):
        return
    choices = [_options(char, slot) for char, slot in zip(text, layout.slots, strict=True)]
    if any(not options for options in choices):
        return
    for combination in product(*choices):
        fixes = sum(cost for _, cost in combination)
        if fixes > MAX_FIXES:
            continue
        plate = "".join(char for char, _ in combination)
        if not is_valid_plate(plate):
            continue  # e.g. an unknown state code
        if any(
            cost and char in _RARE_SERIES_LETTERS and i in layout.series_positions
            for i, (char, cost) in enumerate(combination)
        ):
            continue  # never "fix" a digit into a series letter RTOs don't issue
        rare = sum(1 for i in layout.series_positions if plate[i] in _RARE_SERIES_LETTERS)
        score = fixes + layout.shape_penalty + rare * _RARE_SERIES_PENALTY
        yield PlateReading(plate=plate, kind=layout.kind, fixes=fixes, score=score)


def read_ocr_plate(text: str) -> PlateReading | None:
    """Turn raw OCR output into the most believable valid plate, or None if impossible.

    'DLO1AB1234' -> DL01AB1234 (1 fix: the O sits where a digit must be)
    'MH12A81234' -> MH12AB1234 (1 fix: the 8 sits where a series letter must be)
    'IND DL01AB1234' -> DL01AB1234 (HSRP "IND" mark dropped)
    """
    cleaned = clean_plate(text)
    candidates = [cleaned]
    if cleaned.startswith(HSRP_PREFIX):
        candidates.append(cleaned.removeprefix(HSRP_PREFIX))

    readings = [
        reading
        for candidate in candidates
        for layout in LAYOUTS
        for reading in _readings_for(candidate, layout)
    ]
    if not readings:
        return None
    # Lowest score wins; ties go to fewer fixes, then alphabetical (deterministic).
    return min(readings, key=lambda r: (r.score, r.fixes, r.plate))


def typed_reading(plate: str) -> PlateReading:
    """A reading for a plate a person typed or confirmed (already normalised and valid)."""
    kind: Literal["standard", "bh"] = "bh" if BH_PLATE.match(plate) else "standard"
    return PlateReading(plate=plate, kind=kind, fixes=0, score=0.0)


# --- Fuzzy matching -------------------------------------------------------------------


def bounded_edit_distance(a: str, b: str, max_distance: int) -> int | None:
    """Levenshtein distance between a and b, or None if it is larger than max_distance.

    Classic dynamic programming, row by row, but we stop as soon as every value in a row
    exceeds the bound: the distance can only grow from there.
    """
    if abs(len(a) - len(b)) > max_distance:
        return None
    previous = list(range(len(b) + 1))
    for i, char_a in enumerate(a, start=1):
        current = [i]
        for j, char_b in enumerate(b, start=1):
            current.append(
                min(
                    previous[j] + 1,  # delete a character from a
                    current[j - 1] + 1,  # insert a character into a
                    previous[j - 1] + (char_a != char_b),  # substitute (free if equal)
                )
            )
        if min(current) > max_distance:
            return None
        previous = current
    distance = previous[-1]
    return distance if distance <= max_distance else None


@dataclass(frozen=True)
class ClosestPlates:
    distance: int
    plates: tuple[str, ...]  # every known plate at that distance (more than one = ambiguous)

    @property
    def unique(self) -> str | None:
        return self.plates[0] if len(self.plates) == 1 else None


def closest_plates(plate: str, known: Iterable[str], max_distance: int) -> ClosestPlates | None:
    """Known plates nearest to `plate`, if any are within `max_distance` edits."""
    best_distance: int | None = None
    best: set[str] = set()
    for candidate in known:
        distance = bounded_edit_distance(plate, candidate, max_distance)
        if distance is None:
            continue
        if best_distance is None or distance < best_distance:
            best_distance, best = distance, {candidate}
        elif distance == best_distance:
            best.add(candidate)
    if best_distance is None:
        return None
    return ClosestPlates(distance=best_distance, plates=tuple(sorted(best)))
