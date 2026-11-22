"""Random but valid Indian plates, OCR-style misreads, and a rendered plate snapshot."""

import io
import random

from PIL import Image, ImageDraw, ImageFont

STATES = ["UP", "DL", "HR", "MH", "KA", "RJ", "PB", "TN", "GJ", "WB"]
SERIES_LETTERS = "ABCDEFGHJKLMNPRSTUVWXYZ"  # no I, O or Q: they're avoided on real plates
LOOK_ALIKES = {"0": "O", "1": "I", "8": "B", "5": "S", "2": "Z"}


def random_plate(rng: random.Random) -> str:
    state = rng.choice(STATES)
    district = f"{rng.randint(1, 99):02d}"
    series = "".join(rng.choices(SERIES_LETTERS, k=rng.choice([1, 2])))
    return f"{state}{district}{series}{rng.randint(1, 9999):04d}"


def misread(plate: str, rng: random.Random) -> str:
    """Swap one digit for its look-alike letter, like a camera on a dusty plate."""
    spots = [i for i, ch in enumerate(plate) if ch in LOOK_ALIKES and i >= 4]
    if not spots:
        return plate
    i = rng.choice(spots)
    return plate[:i] + LOOK_ALIKES[plate[i]] + plate[i + 1 :]


def snapshot_jpeg(plate: str) -> bytes:
    """A 320x96 picture of an Indian HSRP plate (white, black text, blue IND strip)."""
    image = Image.new("RGB", (320, 96), (238, 240, 236))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((8, 14, 312, 82), radius=6, fill="white", outline="black", width=3)
    draw.rectangle((11, 17, 36, 79), fill=(31, 69, 194))
    small = ImageFont.load_default(size=11)
    draw.text((14, 62), "IND", font=small, fill="white")
    font = ImageFont.load_default(size=34)
    draw.text((46, 28), plate, font=font, fill="black")
    out = io.BytesIO()
    image.save(out, format="JPEG", quality=80)
    return out.getvalue()
