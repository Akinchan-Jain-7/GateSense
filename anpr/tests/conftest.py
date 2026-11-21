from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pytest

from gatesense_anpr.models import Image

T0 = datetime(2026, 11, 22, 9, 0, tzinfo=UTC)


@pytest.fixture
def frame_image() -> Image:
    return np.full((480, 640, 3), 100, dtype=np.uint8)


def make_constant_onnx(path: Path, output: np.ndarray, input_size: int = 640) -> Path:
    """A tiny ONNX model that ignores its image input and returns `output`.

    Lets the detector's ONNX Runtime wiring be tested without real weights.
    """
    import onnx
    from onnx import TensorProto, helper, numpy_helper

    image = helper.make_tensor_value_info(
        "images", TensorProto.FLOAT, [1, 3, input_size, input_size]
    )
    result = helper.make_tensor_value_info("output0", TensorProto.FLOAT, list(output.shape))
    constant = helper.make_node(
        "Constant", [], ["output0"], value=numpy_helper.from_array(output.astype(np.float32))
    )
    graph = helper.make_graph([constant], "constant", [image], [result])
    model = helper.make_model(graph, opset_imports=[helper.make_opsetid("", 17)])
    model.ir_version = 9
    onnx.save(model, path)
    return path
