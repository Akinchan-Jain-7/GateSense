"""OCR engines behind one small interface, so they can be compared and swapped.

Both engines are optional installs (they pull in PyTorch or PaddlePaddle). Which one is
the default is decided by measured accuracy in notebooks/02_evaluate_ocr.ipynb (ADR-0009).
"""

from typing import Any, Protocol

import cv2
import numpy as np

from gatesense_anpr.models import Image, OcrResult

# Characters that can appear on an Indian plate; telling the engine cuts junk reads.
PLATE_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"


class OcrEngine(Protocol):
    name: str

    def read(self, plate: Image) -> OcrResult | None: ...


def prepare_crop(plate: Image, target_height: int = 64) -> Image:
    """Upscale small crops (OCR struggles below ~30 px of text height)."""
    height = plate.shape[0]
    if height == 0 or height >= target_height:
        return plate
    scale = target_height / height
    resized = cv2.resize(plate, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    return np.asarray(resized, dtype=np.uint8)


def enhance_contrast(plate: Image) -> Image:
    """Grey + CLAHE (local contrast): lifts dark text out of dim, washed-out or glary crops.

    CLAHE evens out contrast tile by tile, so a reflection on one end of the plate doesn't
    flatten the characters at the other end the way a global stretch would.
    """
    if plate.size == 0:
        return plate
    grey = cv2.cvtColor(plate, cv2.COLOR_BGR2GRAY)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(2, 8))
    return np.asarray(cv2.cvtColor(clahe.apply(grey), cv2.COLOR_GRAY2BGR), dtype=np.uint8)


def join_lines(pieces: list[tuple[str, float, float]]) -> OcrResult | None:
    """Merge text pieces (text, confidence, top y) into one plate string.

    Two-line plates (common on two-wheelers) come back as two pieces; reading them top to
    bottom gives the same string as a one-line plate. Confidence = the weakest piece.
    """
    pieces = [(t, c, y) for t, c, y in pieces if t.strip()]
    if not pieces:
        return None
    pieces.sort(key=lambda piece: piece[2])
    text = "".join(t for t, _, _ in pieces)
    return OcrResult(text=text, confidence=min(c for _, c, _ in pieces))


class EasyOcrEngine:
    name = "easyocr"

    def __init__(self, gpu: bool = False) -> None:
        import easyocr

        self.reader: Any = easyocr.Reader(["en"], gpu=gpu, verbose=False)

    def read(self, plate: Image) -> OcrResult | None:
        results = self.reader.readtext(prepare_crop(plate), allowlist=PLATE_ALPHABET)
        # Each result: (corner points, text, confidence); points[0] = top-left (x, y).
        return join_lines([(text, float(conf), float(pts[0][1])) for pts, text, conf in results])


class PaddleOcrEngine:
    name = "paddleocr"

    def __init__(self) -> None:
        from paddleocr import PaddleOCR

        self.reader: Any = PaddleOCR(
            lang="en",
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
            use_textline_orientation=False,
        )

    def read(self, plate: Image) -> OcrResult | None:
        pieces: list[tuple[str, float, float]] = []
        for page in self.reader.predict(prepare_crop(plate)):
            for text, score, poly in zip(
                page["rec_texts"], page["rec_scores"], page["rec_polys"], strict=False
            ):
                pieces.append((str(text), float(score), float(min(p[1] for p in poly))))
        return join_lines(pieces)


def build_engine(name: str) -> OcrEngine:
    engines: dict[str, type[EasyOcrEngine] | type[PaddleOcrEngine]] = {
        "easyocr": EasyOcrEngine,
        "paddleocr": PaddleOcrEngine,
    }
    if name not in engines:
        raise ValueError(f"Unknown OCR engine '{name}'; choose one of {sorted(engines)}")
    try:
        return engines[name]()
    except ImportError as exc:
        raise ImportError(
            f"OCR engine '{name}' isn't installed. Run: uv sync --extra {name}"
        ) from exc
