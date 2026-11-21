import pytest

from app.services.errors import InvalidInputError
from app.services.plates import clean_plate, is_valid_plate, normalize_typed_plate


@pytest.mark.parametrize(
    ("typed", "expected"),
    [
        ("DL01AB1234", "DL01AB1234"),
        ("dl 01 ab 1234", "DL01AB1234"),
        ("UP16-AB-1234", "UP16AB1234"),
        ("  up16 z 5678 ", "UP16Z5678"),
        ("DL 3C AB 1234", "DL3CAB1234"),  # Delhi: district + category letter
        ("KA05MN0042", "KA05MN0042"),
        ("22 BH 1234 AA", "22BH1234AA"),  # Bharat series
        ("23BH0001A", "23BH0001A"),
        ("MH12.DE.1433", "MH12DE1433"),
    ],
)
def test_valid_plates_are_normalized(typed: str, expected: str) -> None:
    assert normalize_typed_plate(typed) == expected


@pytest.mark.parametrize(
    "typed",
    [
        "",
        "1234",
        "ABCDEFGH",
        "D101AB1234",  # state must be two letters
        "DL01AB12345",  # number has at most 4 digits
        "DL01ABCD1234",  # series has at most 3 letters
        "22BH12AA",  # BH number must be 4 digits
        "BH221234AA",  # BH: year comes first
        "DL01AB1234XYZ",
        "XX01AB1234",  # XX is not a state code
    ],
)
def test_invalid_plates_are_rejected(typed: str) -> None:
    with pytest.raises(InvalidInputError):
        normalize_typed_plate(typed)


def test_clean_plate_keeps_only_letters_and_digits() -> None:
    assert clean_plate("ab-12 cd#34") == "AB12CD34"


def test_overlong_plate_is_invalid_even_if_pattern_matches() -> None:
    assert not is_valid_plate("DL01ABC12345")
