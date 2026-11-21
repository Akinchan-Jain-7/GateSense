import csv
import json
import sys
from pathlib import Path

import cv2
import numpy as np
import pytest

from gatesense_anpr.metrics import Sample, char_accuracy, latency_stats, markdown_table, summarise
from gatesense_anpr.models import OcrResult
from tests.conftest import make_constant_onnx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "eval"))
import benchmark_detector  # noqa: E402
import evaluate_pipeline  # noqa: E402


@pytest.mark.parametrize(
    ("predicted", "truth", "expected"),
    [
        ("DL01AB1234", "DL01AB1234", 1.0),
        ("DL01AB1Z34", "DL01AB1234", 0.9),
        ("dl 01 ab 1234", "DL01AB1234", 1.0),
        ("", "DL01AB1234", 0.0),
        ("XXXXXXXXXXXXXXXXXXXXXXXX", "DL01AB1234", 0.0),  # floored at 0
        ("", "", 1.0),
    ],
)
def test_char_accuracy(predicted: str, truth: str, expected: float) -> None:
    assert char_accuracy(predicted, truth) == pytest.approx(expected)


def test_summary_per_condition_plus_all() -> None:
    rows = summarise(
        [
            Sample("day", "DL01AB1234", "DL01AB1234", 10),
            Sample("day", "UP16Z5678", "UP16Z5G78", 20),
            Sample("night", "KA05MN0042", "", 30),
        ]
    )
    assert [r.condition for r in rows] == ["day", "night", "all"]
    day, night, total = rows
    assert (day.samples, day.plate_accuracy, day.read_rate) == (2, 0.5, 1.0)
    assert day.char_accuracy == pytest.approx((1 + 8 / 9) / 2)
    assert (night.plate_accuracy, night.read_rate) == (0.0, 0.0)
    assert total.samples == 3
    assert total.mean_latency_ms == 20


def test_latency_stats_and_table() -> None:
    # Nearest-rank p95 of 20 values is the 19th: one slow outlier doesn't move it...
    assert latency_stats([10.0] * 19 + [30.0]) == {
        "mean_ms": 11.0, "p50_ms": 10.0, "p95_ms": 10.0, "fps": 90.9
    }  # fmt: skip
    # ...but 2 slow runs in 20 (10%) do.
    assert latency_stats([10.0] * 18 + [30.0, 30.0])["p95_ms"] == 30.0
    table = markdown_table(["A", "B"], [["x", 0.5], ["y", 12]])
    assert table.splitlines() == ["| A | B |", "|---|---|", "| x | 50.0% |", "| y | 12 |"]


def test_benchmark_writes_results(tmp_path: Path) -> None:
    output = np.zeros((1, 5, 10), dtype=np.float32)
    model = make_constant_onnx(tmp_path / "tiny.onnx", output)
    out = str(tmp_path / "r")
    assert (
        benchmark_detector.main([str(model), "--runs", "3", "--quantize", "dynamic", "--out", out])
        == 0
    )
    report = json.loads((tmp_path / "r" / "detector_latency.json").read_text())
    assert [r["precision"] for r in report["results"]] == ["FP32", "INT8 dynamic"]
    assert "| tiny | FP32 |" in (tmp_path / "r" / "detector_latency.md").read_text()


def test_evaluate_ocr_on_crops(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    data = tmp_path / "crops"
    (data / "night").mkdir(parents=True)
    cv2.imwrite(str(data / "a.jpg"), np.zeros((40, 160, 3), dtype=np.uint8))
    cv2.imwrite(str(data / "night" / "b.jpg"), np.zeros((40, 160, 3), dtype=np.uint8))
    with (data / "labels.csv").open("w", newline="") as file:
        writer = csv.writer(file)
        writer.writerow(["file", "plate", "condition"])
        writer.writerow(["a.jpg", "DL01AB1234", "day"])
        writer.writerow(["night/b.jpg", "UP16Z5678", "night"])
        writer.writerow(["missing.jpg", "HR26DK8337", "day"])

    class FakeOcr:
        name = "fake"
        answers = ["DL01AB1234", "UP16Z5G78"]

        def read(self, plate: object) -> OcrResult:
            return OcrResult(text=self.answers.pop(0), confidence=0.9)

    monkeypatch.setattr(evaluate_pipeline, "build_engine", lambda name: FakeOcr())
    out = tmp_path / "results"
    assert evaluate_pipeline.main([str(data), "--crops", "--out", str(out)]) == 0
    summary = json.loads((out / "ocr_easyocr.json").read_text())["summary"]
    assert [(r["condition"], r["plate_accuracy"]) for r in summary] == [
        ("day", 1.0),
        ("night", 0.0),
        ("all", 0.5),
    ]


def test_static_quantisation_calibrates_on_frames(tmp_path: Path) -> None:
    import onnx
    from onnx import TensorProto, helper

    # A real (tiny) conv model: static quantisation needs actual activations to calibrate.
    weights = helper.make_tensor("w", TensorProto.FLOAT, [4, 3, 3, 3], [0.1] * 108)
    conv = helper.make_node("Conv", ["images", "w"], ["output0"], pads=[1, 1, 1, 1])
    graph = helper.make_graph(
        [conv],
        "tiny_conv",
        [helper.make_tensor_value_info("images", TensorProto.FLOAT, [1, 3, 640, 640])],
        [helper.make_tensor_value_info("output0", TensorProto.FLOAT, [1, 4, 640, 640])],
        initializer=[weights],
    )
    model = helper.make_model(graph, opset_imports=[helper.make_opsetid("", 17)])
    model.ir_version = 9
    onnx.save(model, tmp_path / "conv.onnx")
    folder = tmp_path / "photos"
    folder.mkdir()
    cv2.imwrite(str(folder / "a.jpg"), np.full((360, 640, 3), 128, dtype=np.uint8))

    target = benchmark_detector.quantize_int8(tmp_path / "conv.onnx", "static", folder)
    ops = {node.op_type for node in onnx.load(target).graph.node}
    assert "QuantizeLinear" in ops and "DequantizeLinear" in ops
