"""OCR plate repair and fuzzy matching: table-driven cases, including the tricky ones."""

import pytest

from app.services.plates import (
    bounded_edit_distance,
    closest_plates,
    is_valid_plate,
    read_ocr_plate,
)

# (what OCR returned, plate we expect, look-alike fixes needed)
READABLE = [
    # --- Clean reads: nothing to fix ----------------------------------------------
    ("DL01AB1234", "DL01AB1234", 0),
    ("UP16Z5678", "UP16Z5678", 0),  # 1-letter series
    ("DL3CAB1234", "DL3CAB1234", 0),  # Delhi: 1-digit district + category letter
    ("DL12CAB1234", "DL12CAB1234", 0),  # Delhi: 2-digit district + 3-letter series
    ("KA05MN0042", "KA05MN0042", 0),  # leading zeros in the number
    ("MH12AB123", "MH12AB123", 0),  # old 3-digit number stays 3 digits
    ("HR26DK8337", "HR26DK8337", 0),
    ("RJ14C1", "RJ14C1", 0),  # very short old plate
    ("22BH1234AA", "22BH1234AA", 0),  # Bharat series
    ("23BH0001A", "23BH0001A", 0),  # Bharat series, 1 suffix letter
    # --- Spacing, punctuation and case from OCR -----------------------------------
    ("dl 01 ab 1234", "DL01AB1234", 0),
    ("UP-16-AB-1234", "UP16AB1234", 0),
    ("MH.12.DE.1433", "MH12DE1433", 0),
    ("  ka05  mn 0042\n", "KA05MN0042", 0),
    # --- HSRP "IND" mark read as part of the plate --------------------------------
    ("IND DL01AB1234", "DL01AB1234", 0),
    # Real laptop-webcam reads (2026-11-24): the mark sits below the number, so OCR
    # read it last, often with its D as O.
    ("HR76AOOO5IND", "HR76A0005", 3),
    ("HR76A0OO5IND", "HR76A0005", 2),
    ("HR6ZA9100IND", "HR6ZA9100", 0),
    ("DL01AB1234INO", "DL01AB1234", 0),
    ("1NDUP16BK2834", "UP16BK2834", 0),
    ("INDUP16Z5678", "UP16Z5678", 0),
    # --- Letters where digits must be (district or number) ------------------------
    ("DLO1AB1234", "DL01AB1234", 1),  # O -> 0 in the district
    ("DL0IAB1234", "DL01AB1234", 1),  # I -> 1 in the district
    ("DL8CAFO921", "DL8CAF0921", 1),  # O -> 0 inside the number
    ("MH12AB1Z34", "MH12AB1234", 1),  # Z -> 2 in the number
    ("MH12AB12S4", "MH12AB1254", 1),  # S -> 5 in the number
    ("HR26DKB337", "HR26DK8337", 1),  # B -> 8 at the start of the number
    ("UP16ABI234", "UP16AB1234", 1),  # I -> 1 at the start of the number
    ("UP16AB12G4", "UP16AB1264", 1),  # G -> 6
    ("UP16AB1T34", "UP16AB1734", 1),  # T -> 7
    ("UP16AB123A", "UP16AB1234", 1),  # A -> 4 at the end
    ("UP16ABL234", "UP16AB1234", 1),  # lower-case l comes out as L -> 1
    ("UP16ABQ234", "UP16AB0234", 1),  # Q -> 0
    # --- Digits where letters must be (state or series) ---------------------------
    ("0L01AB1234", "DL01AB1234", 1),  # 0 -> D: "OL" isn't a state, "DL" is
    ("MH12A81234", "MH12AB1234", 1),  # 8 -> B in the series
    ("MH125B1234", "MH12SB1234", 1),  # 5 -> S in the series
    ("UP162X1234", "UP16ZX1234", 1),  # 2 -> Z in the series
    ("K405MN0042", "KA05MN0042", 1),  # 4 -> A in the state code
    ("UP16A01234", "UP16AD1234", 1),  # 0 -> D, not O: RTOs skip O in series letters
    # --- Several fixes in one read ------------------------------------------------
    ("DLO1A81234", "DL01AB1234", 2),
    ("KAO5MNOO42", "KA05MN0042", 3),  # beats KA05MNO042 (2 fixes but an odd shape)
    # Real EasyOCR output (Phase 3 video run): S for 5 as well. Not KA0SMN0042: only Delhi
    # writes 1-digit districts.
    ("KAOSMNO042", "KA05MN0042", 3),
    ("DL3CASO042", "DL3CAS0042", 1),  # ...while Delhi's 1-digit districts still work
    ("0LO1A8IZ34", None, None),  # needs 4+ fixes: too unreliable
    # --- BH series with look-alikes -----------------------------------------------
    ("228H1234AA", "22BH1234AA", 1),  # 8 -> B in the fixed "BH"
    ("ZZBH1234AA", "22BH1234AA", 2),  # Z -> 2 in the year
    ("24BHOO42C", "24BH0042C", 2),  # O -> 0 twice in the BH number
    ("22BHI234A4", "22BH1234AA", 2),  # I -> 1 in the number, 4 -> A in the suffix
]

UNREADABLE = [
    "",
    "1234",
    "ABCDEFGH",
    "DL01AB12345",  # number longer than 4 digits
    "XX01AB1234",  # not a state code
    "DL01ABCD1234",  # series longer than 3 letters
    "DLO1AB12E4",  # E has no digit look-alike
    "BH221234AA",  # BH plate with the year in the wrong place
    "##@@!!",
]


@pytest.mark.parametrize(("ocr_text", "plate", "fixes"), READABLE)
def test_ocr_reads_are_repaired(ocr_text: str, plate: str | None, fixes: int | None) -> None:
    reading = read_ocr_plate(ocr_text)
    if plate is None:
        assert reading is None
        return
    assert reading is not None
    assert (reading.plate, reading.fixes) == (plate, fixes)
    assert is_valid_plate(reading.plate)


@pytest.mark.parametrize("ocr_text", UNREADABLE)
def test_unreadable_text_gives_none(ocr_text: str) -> None:
    assert read_ocr_plate(ocr_text) is None


def test_suite_has_at_least_forty_plate_cases() -> None:
    # The brief asks for >= 40 table-driven cases; keep the table from shrinking.
    assert len(READABLE) + len(UNREADABLE) >= 40


def test_bh_reading_reports_its_kind() -> None:
    reading = read_ocr_plate("22BH1234AA")
    assert reading is not None
    assert reading.kind == "bh"


@pytest.mark.parametrize(
    ("a", "b", "max_distance", "expected"),
    [
        ("DL01AB1234", "DL01AB1234", 1, 0),
        ("DL01AB1234", "DL01AB1235", 1, 1),  # one substitution
        ("DL01AB1234", "DL01AB123", 1, 1),  # one deletion
        ("DL01AB123", "DL01AB1234", 1, 1),  # one insertion
        ("DL01AB1234", "DL01AC1235", 1, None),  # two edits, bound is 1
        ("DL01AB1234", "DL01AC1235", 2, 2),
        ("UP16AB1234", "DL3CAB1234", 1, None),  # length differs by 0 but many edits
        ("UP16Z5678", "UP16ZX5678", 1, 1),
        ("AB", "ABCD", 1, None),  # length gap alone exceeds the bound
    ],
)
def test_bounded_edit_distance(a: str, b: str, max_distance: int, expected: int | None) -> None:
    assert bounded_edit_distance(a, b, max_distance) == expected


def test_closest_plate_prefers_exact_match() -> None:
    result = closest_plates("DL01AB1234", ["DL01AB1234", "DL01AB1235"], max_distance=1)
    assert result is not None
    assert (result.distance, result.unique) == (0, "DL01AB1234")


def test_closest_plate_within_one_edit() -> None:
    result = closest_plates("DL01AB1Z34", ["DL01AB1234", "UP16Z5678"], max_distance=1)
    assert result is not None
    assert (result.distance, result.unique) == (1, "DL01AB1234")


def test_two_equally_close_plates_are_ambiguous() -> None:
    result = closest_plates("DL01AB1234", ["DL01AB1235", "DL01AB1236"], max_distance=1)
    assert result is not None
    assert result.distance == 1
    assert result.unique is None
    assert result.plates == ("DL01AB1235", "DL01AB1236")


def test_no_plate_close_enough() -> None:
    assert closest_plates("DL01AB1234", ["UP16Z5678", "HR26DK8337"], max_distance=1) is None
    assert closest_plates("DL01AB1234", [], max_distance=1) is None
