# ANPR results

Only numbers from real runs go here. Anything not measured yet says so.

| Result | Status | File |
|---|---|---|
| Detector latency on CPU, FP32 vs INT8 | ✅ Measured (build machine, untrained same-size model) | [detector_latency.md](detector_latency.md) |
| End-to-end wiring: video → OCR → API | ✅ Measured (synthetic video, stand-in detector, real EasyOCR) | [e2e_synthetic_video.md](e2e_synthetic_video.md) |
| Detection mAP, YOLOv8n vs YOLOv8s | ⏳ Pending owner Colab run (notebook 01) | `detector_comparison.md` |
| OCR accuracy per condition, EasyOCR vs PaddleOCR | ⏳ Pending owner Colab run (notebook 02) + labelled photos | `ocr_comparison.md` |
| End-to-end plate accuracy per condition (trained detector + chosen OCR) | ⏳ Pending the two runs above | `e2e_<ocr>.md` |
| Latency on the owner's laptop / gate hardware | ⏳ Pending: `uv run python eval/benchmark_detector.py models/plate_detector.onnx` | `detector_latency.md` |

## Headline so far

On the 2-core build machine, the YOLOv8n plate architecture runs the full `detect()`
call on a 1280x720 frame in **65 ms (15 FPS) in FP32** and **32 ms (31 FPS) with static
INT8 quantisation**. Dynamic INT8 is *slower* (88 ms) for this convolutional model.
YOLOv8s is about 3x slower than YOLOv8n in each precision. The worker analyses 5 frames
per second by default, so either model keeps up, with room to spare for OCR.
