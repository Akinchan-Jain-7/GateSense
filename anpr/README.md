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
uv run python -m gatesense_anpr.download_model  # plate_detector.onnx from GitHub Releases, hash-checked
uv run gatesense-anpr --source path/to/gate.mp4  # or 0 (webcam), rtsp://…, or a folder
```

### Live preview (demos, camera setup)

```bash
uv run gatesense-anpr --source 0 --preview    # opens http://127.0.0.1:8765
```

A local page with the camera picture, a box around each plate, the text read, and the
server's decision for each car (*Resident car: entry logged*, *New car: register the
visitor*...). With `ANPR_EXIT_DEVICE_KEY` set, **Entry / Exit** buttons switch one camera
between two lanes (each with its own key and offline buffer). For a laptop webcam demo,
`cd backend && uv run python -m app.webcam_devices` writes both keys into `anpr/.env`;
on Windows `scripts/webcam-demo.ps1` does everything. Guide: [docs/webcam-demo.md](../docs/webcam-demo.md).

Optional reading settings, off by default because on the webcam bench neither beat the
defaults beyond noise ([eval/results/README.md](eval/results/README.md)):
`ANPR_OCR_CONTRAST=true` (grey + CLAHE on each crop) and `ANPR_TRACK_VOTING=chars`
(per-character votes across frames). Try them on your own photos first:
`eval/evaluate_pipeline.py --contrast`.

All settings are `ANPR_*` environment variables (or `anpr/.env`); see
`gatesense_anpr/config.py`: API URL, device key, model path, OCR engine, detector
thresholds, frames per second to analyse, tracker timings, retries.

## Offline mode

If the API can't be reached (internet down, server restarting), reads aren't lost. They
wait in a SQLite file (`ANPR_BUFFER_PATH`, default `anpr/data/offline-buffer.sqlite3`,
`/data/offline-buffer.sqlite3` in Docker; mount a volume there) and are sent in the
order they happened once the API is back. New reads queue behind older ones, so the
server never sees an exit before its entry. Retries back off from 5 seconds to 5 minutes.
Sending twice is safe: the server stores each read once. A read the server rejects for
good (invalid data) is moved to a `rejected` table so it can't block the queue. Set
`ANPR_BUFFER_PATH=` (empty) to turn the buffer off. Details: `gatesense_anpr/buffer.py`.

## Models and data

- Weights and datasets **never go in git** (`anpr/models/`, `anpr/data/` are ignored).
- Train the detector: `notebooks/01_train_plate_detector.ipynb` (Kaggle or Colab GPU).
- Compare OCR engines: `notebooks/02_evaluate_ocr.ipynb`.
- Your own photos: folder layout and labelling guide in [DATASET.md](DATASET.md).
- The trained model is published as a GitHub Release asset (`models-v1/plate_detector.onnx`,
  SHA-256 `63e5d3e1…6a977`, checked by `download_model`). Scores: [eval/results/detector_comparison.md](eval/results/detector_comparison.md).

## Evaluation

| Script | Measures | Output |
|---|---|---|
| `eval/benchmark_detector.py` | CPU latency, FP32 vs INT8 dynamic vs INT8 static | `eval/results/detector_latency.md` |
| `eval/evaluate_pipeline.py` | plate / character accuracy per condition | `eval/results/e2e_<ocr>.md`, `ocr_<ocr>.md` |
| `eval/make_demo_video.py` | builds a synthetic gate video + stand-in detector to test the wiring | — |
| `eval/webcam_benchmark.py` | reading settings (crop, upscale, contrast, voting) on webcam-like rendered frames, 7 conditions | `eval/results/webcam_benchmark.md` |

Current results and what is still pending: [eval/results/README.md](eval/results/README.md).

## Tests

```bash
uv run pytest      # no model, camera or OCR engine needed
```
