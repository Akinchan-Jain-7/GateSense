"""Light plate-text cleanup on the edge.

The backend is the single authority on plate repair (backend/app/services/plates.py:
Indian layouts, look-alike fixes, state codes). The worker only needs enough to *group*
reads of the same car and throw away obvious junk, so the two can never disagree about
what a plate "really" is.
"""

import re

MIN_LENGTH, MAX_LENGTH = 6, 13  # shortest/longest Indian plate, with an "IND" prefix


def clean(text: str) -> str:
    """'dl 01-ab 1234' -> 'DL01AB1234'."""
    return re.sub(r"[^A-Z0-9]", "", text.upper())


def looks_like_plate(text: str) -> bool:
    """Junk filter: right length and both letters and digits (OCR also reads stickers)."""
    return (
        MIN_LENGTH <= len(text) <= MAX_LENGTH
        and any(c.isdigit() for c in text)
        and any(c.isalpha() for c in text)
    )


def edit_distance(a: str, b: str) -> int:
    previous = list(range(len(b) + 1))
    for i, char_a in enumerate(a, start=1):
        current = [i]
        for j, char_b in enumerate(b, start=1):
            current.append(
                min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (char_a != char_b))
            )
        previous = current
    return previous[-1]
