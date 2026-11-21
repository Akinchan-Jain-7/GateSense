"""Number-plate cleaning and validation for plates typed by people (admin, residents).

Phase 1 handles typed input: strip spaces and dashes, upper-case, check the format.
Phase 2 adds what OCR output needs on top: position-aware fixes for look-alike
characters (O/0, I/1, B/8…) and fuzzy matching against known plates.
"""

import re

from app.services.errors import InvalidInputError

# Standard plate: state (2 letters) + RTO district (1-2 digits) + series (0-3 letters)
# + number (1-4 digits). Examples: DL01AB1234, UP16Z5678, DL3CAB1234, KA05MN0042.
STANDARD_PLATE = re.compile(r"^[A-Z]{2}\d{1,2}[A-Z]{0,3}\d{1,4}$")

# Bharat (BH) series, for people who move states often: year (2 digits) + "BH"
# + number (4 digits) + 1-2 letters. Example: 22BH1234AA.
BH_PLATE = re.compile(r"^\d{2}BH\d{4}[A-Z]{1,2}$")

MAX_PLATE_LENGTH = 12


def clean_plate(text: str) -> str:
    """'dl 01-ab 1234' -> 'DL01AB1234'. Keeps only letters and digits."""
    return re.sub(r"[^A-Z0-9]", "", text.upper())


def is_valid_plate(normalized: str) -> bool:
    if len(normalized) > MAX_PLATE_LENGTH:
        return False
    return bool(STANDARD_PLATE.match(normalized) or BH_PLATE.match(normalized))


def normalize_typed_plate(text: str) -> str:
    """Clean a typed plate and reject it if it isn't a valid Indian format."""
    normalized = clean_plate(text)
    if not is_valid_plate(normalized):
        raise InvalidInputError(
            f"'{text}' is not a valid Indian number plate (e.g. DL01AB1234 or 22BH1234AA)"
        )
    return normalized
