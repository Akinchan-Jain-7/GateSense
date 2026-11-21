# ADR-0009: ANPR pipeline design, and how the models are chosen

- **Status:** Accepted for the design; model and OCR choices are **pending the owner's Colab
  runs** (notebooks 01 and 02), with the selection rules fixed in advance below.
- **Date:** 2026-11-22

## Context

The worker runs on a modest machine at the gate (a laptop or a small PC, no GPU). It must
turn video into one gate event per car, with a snapshot, and keep working if the network
blips. The brief fixes YOLOv8 for detection, PaddleOCR or EasyOCR "picked by measured
results", ONNX Runtime for inference, and Colab for training.

## Decisions

1. **ONNX Runtime at run time, no PyTorch/Ultralytics.** The worker's dependencies are
   ONNX Runtime, OpenCV, NumPy and httpx. Letterboxing, decoding YOLOv8's `(1, 5, N)` output
   and NMS are ~80 lines of NumPy (`detector.py`), tested against hand-built tensors and a
   tiny generated ONNX model. Smaller install, faster start, and no AGPL code on the edge.
2. **The backend is the only plate "brain".** The worker cleans text and filters junk;
   look-alike repair, layouts and state codes stay in `backend/app/services/plates.py`.
   One implementation means the two can never disagree.
3. **Group frames per car before sending** (`tracker.py`): reads within one edit of each
   other join a track; texts are voted by summed OCR confidence; send early after 3
   agreeing reads (low latency at the barrier), otherwise when the plate has been out of
   view for 2 s. This complements the server's exact-match debounce (ADR-0006).
4. **Send OCR confidence**, not detector confidence: the server's review threshold is about
   whether the *text* can be trusted.
5. **Video-time timestamps for recordings**, wall-clock for live cameras, so replaying a
   recording gives the same gaps the server debounce would have seen.
6. **Static INT8 quantisation**, not dynamic. Measured on the build machine (YOLOv8n plate
   architecture, full `detect()` on 1280x720): FP32 65 ms, dynamic INT8 88 ms (*slower*),
   static INT8 32 ms. Dynamic quantisation targets MatMul-heavy models; YOLO is convolutions.
   Accuracy after static INT8 must be checked with real calibration photos before using it
   (`--calibration-images`); until then FP32 is the default.
7. **Weights never in git**: published as a GitHub Release asset, fetched with
   `python -m gatesense_anpr.download_model` (SHA-256 checked).

## Selection rules (decided before seeing the numbers)

- **Detector:** YOLOv8s only if it beats YOLOv8n by **≥ 0.02 mAP50-95** on the held-out
  test split; otherwise YOLOv8n (~3x faster on CPU: 65 vs 194 ms FP32, measured).
- **OCR:** the slower engine only if it beats the faster one by **≥ 2 points of exact-plate
  accuracy** on the owner's labelled photos (not the synthetic set); otherwise the faster.
- Results land in `anpr/eval/results/`; this ADR gets an update with the chosen pair.

Fixing the rules first stops "picking the winner, then finding a reason".

## Alternatives considered

- **Ultralytics at run time** (`YOLO("best.pt")`): the simplest code, but pulls PyTorch
  (~2 GB) onto the gate machine and AGPL code into the deployed worker. Rejected.
- **OpenCV DNN for inference**: no extra package, but slower than ONNX Runtime on CPU and
  weaker operator coverage. Rejected.
- **A plate-specific OCR model** (e.g. a small CRNN trained on Indian plates): likely the
  most accurate, but needs a large text-labelled dataset; the `plate_corrections` table
  collects exactly that data for a later retrain. Future work.
- **Running ANPR in the cloud**: no edge hardware, but uploads video continuously and stops
  working when the internet does. Rejected (and see Phase 7 offline mode).

## Licence note (owner should read)

Ultralytics YOLOv8 is **AGPL-3.0**, and Ultralytics states that models trained with it are
covered too. This repo's code stays MIT: the worker doesn't import Ultralytics, and the
training notebook only installs it in Colab. The **trained weights we publish carry AGPL
terms**, which is fine for a portfolio/open-source project. For commercial use you would
need an Ultralytics Enterprise licence or a permissively licensed detector (e.g. YOLOX,
Apache-2.0). Swapping detectors only means a different `decode_*` function.

## Consequences

- The worker can be installed on a laptop in a minute and runs without a GPU.
- Detection/OCR accuracy numbers stay "pending" until the owner runs two notebooks.
- If a model with a different output format is used later, `decode_yolov8` needs a sibling.
