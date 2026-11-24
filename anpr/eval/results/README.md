# ANPR results

Only numbers from real runs go here. Anything not measured yet says so.

| Result | Status | File |
|---|---|---|
| Detector latency on CPU, FP32 vs INT8 | ✅ Measured (build machine, untrained same-size model) | [detector_latency.md](detector_latency.md) |
| End-to-end wiring: video → OCR → API | ✅ Measured (synthetic video, stand-in detector, real EasyOCR) | [e2e_synthetic_video.md](e2e_synthetic_video.md) |
| Reading settings on webcam-like frames (crop, upscale, contrast, voting) | ✅ Measured (rendered plates, real EasyOCR) | [webcam_benchmark.md](webcam_benchmark.md) |
| Accuracy on the owner's webcam | ⏳ Pending: about 30 photos from the preview's *Save for testing* | `e2e_webcam.md` |
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

## Webcam reading settings (2026-11-24)

After the owner found webcam reads "slightly less accurate", five changes to the edge
reading were measured against today's settings on 140 rendered cars (7 webcam
conditions, 6 frames each, real EasyOCR; `eval/webcam_benchmark.py`):

- **None beat today's settings by more than noise** on what the guard finally sees (the
  plate after the server's repair): 78.6–81.4% vs 80.0%, a difference of 1–2 cars.
- Per-character voting made the camera's own guess exact more often (72.1% vs 68.6%), but
  those were look-alike slips (O/0, A/4) that the server's repair already fixes.
- Most remaining misses are tilted (70%) and blurry (70%) plates. A wider crop margin
  didn't help; it let more background into the crop.
- One systematic miss: **G read as 0** at the start of the plate (`0J86...` for `GJ86...`),
  which the server can't repair because it doesn't pair 0 with G. It may come from the
  bench's computer font, so the server is unchanged until real photos show it too.

So the defaults stay as they were. The contrast boost (`ANPR_OCR_CONTRAST=true`) and
per-character voting (`ANPR_TRACK_VOTING=chars`) are optional settings. Measure them on
real webcam photos (`evaluate_pipeline.py --contrast`) before switching them on.

Limits of the bench: rendered text in an OpenCV font, not the HSRP font; random district
numbers (some, like `DL80`, don't exist, which costs every setting equally); the detector
is simulated (true box with random slack), only OCR is real.
