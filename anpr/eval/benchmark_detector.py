"""CPU latency of plate detector models, FP32 vs INT8.

    uv run python eval/benchmark_detector.py models/yolov8n_plate.onnx models/yolov8s_plate.onnx

For each model: time the full `PlateDetector.detect` call (letterbox + model + decode/NMS)
on a 1280x720 frame, then quantise the model to INT8 with ONNX Runtime (dynamic and/or
static) and time each copy. Writes eval/results/detector_latency.md and .json.

Latency depends on the architecture, not on what the weights learned, so this can be run
before training (on an untrained model of the same architecture); accuracy can't.
"""

import argparse
import json
import os
import platform
import time
from datetime import UTC, datetime
from pathlib import Path

import cv2
import numpy as np

from gatesense_anpr.detector import PlateDetector, letterbox
from gatesense_anpr.metrics import latency_stats, markdown_table

RESULTS = Path(__file__).resolve().parent / "results"


class _CalibrationFrames:
    """Feeds letterboxed frames to ONNX Runtime's static quantiser.

    Real gate photos give the best INT8 accuracy (pass --calibration-images); random frames
    are enough when only measuring speed, which is what the default run does.
    """

    def __init__(self, input_name: str, images: list[np.ndarray]) -> None:
        self.input_name = input_name
        self.items = iter([letterbox(image, 640)[0] for image in images])

    def get_next(self) -> dict[str, np.ndarray] | None:
        tensor = next(self.items, None)
        return None if tensor is None else {self.input_name: tensor}


def calibration_images(folder: Path | None, count: int = 16) -> list[np.ndarray]:
    if folder is not None:
        paths = sorted(
            p for p in folder.rglob("*") if p.suffix.lower() in {".jpg", ".jpeg", ".png"}
        )
        images = [cv2.imread(str(p)) for p in paths[:count]]
        return [np.asarray(i, dtype=np.uint8) for i in images if i is not None]
    rng = np.random.default_rng(1)
    return [rng.integers(0, 255, size=(720, 1280, 3), dtype=np.uint8) for _ in range(count)]


def quantize_int8(model: Path, method: str, calibration: Path | None = None) -> Path:
    """INT8 copy of the model. 'dynamic': weights only, no data needed (made for
    transformer MatMuls). 'static': weights and activations, calibrated on sample frames
    (the usual choice for convolutional networks like YOLO)."""
    import onnxruntime as ort
    from onnxruntime.quantization import QuantFormat, QuantType, quantize_dynamic, quantize_static

    target = model.with_name(f"{model.stem}_int8_{method}.onnx")
    if method == "dynamic":
        quantize_dynamic(str(model), str(target), weight_type=QuantType.QUInt8)
    else:
        input_name = ort.InferenceSession(str(model)).get_inputs()[0].name
        quantize_static(
            str(model),
            str(target),
            _CalibrationFrames(input_name, calibration_images(calibration)),
            quant_format=QuantFormat.QDQ,
            activation_type=QuantType.QUInt8,
            weight_type=QuantType.QInt8,
        )
    return target


def time_model(model: Path, runs: int, warmup: int = 5) -> dict[str, float]:
    detector = PlateDetector(model, confidence=0.25)
    rng = np.random.default_rng(0)
    frame = rng.integers(0, 255, size=(720, 1280, 3), dtype=np.uint8)
    for _ in range(warmup):
        detector.detect(frame)
    timings = []
    for _ in range(runs):
        start = time.perf_counter()
        detector.detect(frame)
        timings.append((time.perf_counter() - start) * 1000)
    return latency_stats(timings)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("models", nargs="+", type=Path)
    parser.add_argument("--runs", type=int, default=50)
    parser.add_argument("--note", default="", help="added to the report, e.g. 'untrained'")
    parser.add_argument(
        "--quantize", nargs="*", default=["dynamic", "static"], choices=["dynamic", "static"]
    )
    parser.add_argument("--calibration-images", type=Path, help="folder of real gate photos")
    parser.add_argument("--out", type=Path, default=RESULTS)
    args = parser.parse_args(argv)

    rows = []
    for model in args.models:
        variants = [("FP32", model)] + [
            (f"INT8 {method}", quantize_int8(model, method, args.calibration_images))
            for method in args.quantize
        ]
        for variant, path in variants:
            stats = time_model(path, args.runs)
            rows.append(
                {
                    "model": model.stem,
                    "precision": variant,
                    "size_mb": round(path.stat().st_size / 1e6, 1),
                    **stats,
                }  # fmt: skip
            )
            print(rows[-1], flush=True)

    machine = {
        "cpu": platform.processor() or platform.machine(),
        "cores": os.cpu_count(),
        "os": platform.platform(),
        "python": platform.python_version(),
        "measured_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "detector_latency.json").write_text(
        json.dumps(
            {"machine": machine, "note": args.note, "runs": args.runs, "results": rows}, indent=2
        )
        + "\n"
    )
    table = markdown_table(
        ["Model", "Precision", "Size (MB)", "Mean (ms)", "p50 (ms)", "p95 (ms)", "FPS"],
        [
            [
                r["model"],
                r["precision"],
                r["size_mb"],
                r["mean_ms"],
                r["p50_ms"],
                r["p95_ms"],
                r["fps"],
            ]
            for r in rows
        ],  # fmt: skip
    )
    (args.out / "detector_latency.md").write_text(
        "# Plate detector latency on CPU\n\n"
        f"Full `detect()` call on a 1280x720 frame (letterbox + model + NMS), {args.runs} runs "
        "after 5 warm-up runs, one thread pool per process (ONNX Runtime defaults).\n\n"
        f"{table}\n\n"
        f"Machine: {machine['cpu']}, {machine['cores']} cores, {machine['os']}, "
        f"Python {machine['python']}. Measured {machine['measured_at']}.\n"
        + (f"\nNote: {args.note}\n" if args.note else "")
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
