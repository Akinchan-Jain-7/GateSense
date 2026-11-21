"""Accuracy of the detector + OCR on labelled photos, per condition.

    uv run python eval/evaluate_pipeline.py data/eval --ocr easyocr
    uv run python eval/evaluate_pipeline.py data/plate_crops --ocr paddleocr --crops

The folder needs a `labels.csv` with columns `file,plate,condition` (see anpr/DATASET.md),
e.g. `night/0007.jpg,DL3CAS0042,night`.

- default: full photos; the detector finds the plate, OCR reads the best box.
- `--crops`: the images are already plate crops; measures OCR alone (for engine comparison).

Writes eval/results/<name>.md and .json (name = e2e_<ocr> or ocr_<ocr>).
"""

import argparse
import csv
import json
import time
from dataclasses import asdict
from pathlib import Path

import cv2
import numpy as np

from gatesense_anpr.config import AnprSettings
from gatesense_anpr.detector import PlateDetector, crop
from gatesense_anpr.metrics import Sample, markdown_table, summarise
from gatesense_anpr.normaliser import clean
from gatesense_anpr.ocr import OcrEngine, build_engine

RESULTS = Path(__file__).resolve().parent / "results"


def read_labels(folder: Path) -> list[tuple[Path, str, str]]:
    with (folder / "labels.csv").open(newline="", encoding="utf-8") as file:
        return [
            (folder / r["file"], r["plate"], r.get("condition") or "all")
            for r in csv.DictReader(file)
        ]


def predict(image: np.ndarray, ocr: OcrEngine, detector: PlateDetector | None) -> str:
    if detector is not None:
        detections = detector.detect(image)
        if not detections:
            return ""
        image = crop(image, detections[0].box)
    result = ocr.read(image)
    return clean(result.text) if result else ""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("folder", type=Path)
    parser.add_argument("--ocr", default="easyocr", choices=["easyocr", "paddleocr"])
    parser.add_argument("--crops", action="store_true", help="images are plate crops (OCR only)")
    parser.add_argument("--model", type=Path, help="detector ONNX (default: from settings)")
    parser.add_argument("--out", type=Path, default=RESULTS)
    args = parser.parse_args(argv)

    ocr = build_engine(args.ocr)
    detector = None if args.crops else PlateDetector(args.model or AnprSettings().detector_model)
    samples = []
    for path, truth, condition in read_labels(args.folder):
        image = cv2.imread(str(path))
        if image is None:
            print(f"skipping unreadable {path}")
            continue
        start = time.perf_counter()
        predicted = predict(np.asarray(image, dtype=np.uint8), ocr, detector)
        samples.append(Sample(condition, truth, predicted, (time.perf_counter() - start) * 1000))

    rows = summarise(samples)
    name = f"{'ocr' if args.crops else 'e2e'}_{args.ocr}"
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / f"{name}.json").write_text(
        json.dumps(
            {
                "dataset": str(args.folder),
                "summary": [asdict(r) for r in rows],
                "samples": [asdict(s) for s in samples],
            },
            indent=2,
        )
        + "\n"  # fmt: skip
    )
    table = markdown_table(
        ["Condition", "Images", "Plate accuracy", "Char accuracy", "Read rate", "Mean ms"],
        [
            [
                r.condition,
                r.samples,
                r.plate_accuracy,
                r.char_accuracy,
                r.read_rate,
                round(r.mean_latency_ms, 1),
            ]
            for r in rows
        ],  # fmt: skip
    )
    what = "OCR on plate crops" if args.crops else "detector + OCR on full photos"
    (args.out / f"{name}.md").write_text(
        f"# {args.ocr}: {what}\n\nDataset: `{args.folder}`\n\n{table}\n"
    )
    print(table)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
