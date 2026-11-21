# ANPR worker

Runs at the gate. Reads camera frames, finds number plates, reads them, and sends one
gate event per car to the GateSense API.

```
source (webcam / RTSP / video / folder)
  → detector: YOLOv8 exported to ONNX, run with ONNX Runtime (no PyTorch needed)
  → plate crop → OCR (EasyOCR or PaddleOCR)
  → clean + group a car's reads across frames, vote, send once
  → POST /api/v1/gate-events (device key, snapshot), retried with backoff
```

The backend does the authoritative plate repair (look-alike characters, Indian layouts,
state codes). The worker only cleans text and votes, so the two can't disagree.

## Quick start

```bash
cd anpr
uv sync                                   # core: ONNX Runtime, OpenCV, httpx
uv run gatesense-anpr --simulate 5 --dry-run   # fake reads, prints them
```

Send simulated reads to the local API (backend running, seed printed the device keys):

```bash
# PowerShell: $env:ANPR_DEVICE_KEY="gsd_..."   bash: export ANPR_DEVICE_KEY=gsd_...
uv run gatesense-anpr --simulate 10 --realtime --interval 3
```

Run on a real camera or recording (needs a trained model and an OCR engine):

```bash
uv sync --extra easyocr                         # or --extra paddleocr
uv run python -m gatesense_anpr.download_model  # plate_detector.onnx from GitHub Releases
uv run gatesense-anpr --source path/to/gate.mp4  # or 0 (webcam), rtsp://…, or a folder
```

All settings are `ANPR_*` environment variables (or `anpr/.env`); see
`gatesense_anpr/config.py`: API URL, device key, model path, OCR engine, detector
thresholds, frames per second to analyse, tracker timings, retries.

## Models and data

- Weights and datasets **never go in git** (`anpr/models/`, `anpr/data/` are ignored).
- Train the detector: `notebooks/01_train_plate_detector.ipynb` (Colab GPU).
- Compare OCR engines: `notebooks/02_evaluate_ocr.ipynb`.
- Your own photos: folder layout and labelling guide in [DATASET.md](DATASET.md).
- The trained model is published as a GitHub Release asset (`models-v1/plate_detector.onnx`).

## Evaluation

| Script | Measures | Output |
|---|---|---|
| `eval/benchmark_detector.py` | CPU latency, FP32 vs INT8 dynamic vs INT8 static | `eval/results/detector_latency.md` |
| `eval/evaluate_pipeline.py` | plate / character accuracy per condition | `eval/results/e2e_<ocr>.md`, `ocr_<ocr>.md` |
| `eval/make_demo_video.py` | builds a synthetic gate video + stand-in detector to test the wiring | — |

Current results and what is still pending: [eval/results/README.md](eval/results/README.md).

## Tests

```bash
uv run pytest      # no model, camera or OCR engine needed
```
