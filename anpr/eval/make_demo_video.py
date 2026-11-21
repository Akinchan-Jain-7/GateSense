"""A synthetic gate video + stand-in detector, to test the whole chain end to end.

    uv run python eval/make_demo_video.py --out /tmp/e2e --plates DL01AB1234,HR26DK8337

Writes:
- `gate.avi`: each car "stops at the barrier" for a few seconds (its plate rendered in
  the same spot, with a little camera noise), then an empty lane for a few seconds;
- `stand_in_detector.onnx`: a model that always returns the box where the plates are
  drawn.

This tests the *wiring* (video source -> ONNX Runtime -> crop -> real OCR -> tracker ->
API) before a trained detector exists. It says nothing about detection accuracy on real
cameras: that comes from notebooks/01_train_plate_detector.ipynb.
"""

import argparse
from pathlib import Path

import cv2
import numpy as np

from gatesense_anpr.simulate import render_plate

WIDTH, HEIGHT, FPS = 640, 360, 25
# Where render_plate draws the plate, in frame pixels.
PLATE_BOX = (120, 140, 520, 220)


def write_video(path: Path, plates: list[str], seconds_per_car: float, gap_seconds: float) -> None:
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter.fourcc(*"MJPG"), FPS, (WIDTH, HEIGHT))
    rng = np.random.default_rng(0)
    empty = np.full((HEIGHT, WIDTH, 3), 90, dtype=np.uint8)
    for plate in plates:
        frame = render_plate(plate)
        for _ in range(int(seconds_per_car * FPS)):
            noise = rng.normal(0, 6, frame.shape)
            writer.write(np.clip(frame + noise, 0, 255).astype(np.uint8))
        for _ in range(int(gap_seconds * FPS)):
            writer.write(empty)
    writer.release()


def write_stand_in_detector(path: Path, input_size: int = 640) -> None:
    import onnx
    from onnx import TensorProto, helper, numpy_helper

    # The frame is letterboxed into 640x640: same width, so 140 px grey bars top and bottom.
    pad_y = (input_size - HEIGHT * input_size / WIDTH) / 2
    x1, y1, x2, y2 = PLATE_BOX
    box = [(x1 + x2) / 2, (y1 + y2) / 2 + pad_y, x2 - x1, y2 - y1, 0.95]
    output = np.array(box, dtype=np.float32).reshape(1, 5, 1)
    graph = helper.make_graph(
        [helper.make_node("Constant", [], ["output0"], value=numpy_helper.from_array(output))],
        "stand_in_plate_detector",
        [
            helper.make_tensor_value_info(
                "images", TensorProto.FLOAT, [1, 3, input_size, input_size]
            )
        ],  # noqa: E501
        [helper.make_tensor_value_info("output0", TensorProto.FLOAT, [1, 5, 1])],
    )
    model = helper.make_model(graph, opset_imports=[helper.make_opsetid("", 17)])
    model.ir_version = 9
    onnx.save(model, path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--plates", default="DL01AB1234,HR26DK8337,MH12DE1433")
    parser.add_argument("--seconds-per-car", type=float, default=3.0)
    parser.add_argument("--gap", type=float, default=4.0)
    args = parser.parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)
    plates = [p.strip() for p in args.plates.split(",") if p.strip()]
    write_video(args.out / "gate.avi", plates, args.seconds_per_car, args.gap)
    write_stand_in_detector(args.out / "stand_in_detector.onnx")
    print(f"wrote {args.out / 'gate.avi'} ({len(plates)} cars) and stand_in_detector.onnx")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
