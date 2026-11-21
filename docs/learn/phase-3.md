# Phase 3 study guide: ANPR ML pipeline

## What we built and why

The `anpr` package is the program that runs at the gate. It reads frames from a webcam, an
IP camera (RTSP), a video file or a folder of photos. It finds number plates with a YOLOv8
detector exported to ONNX, crops each plate, reads it with OCR (EasyOCR or PaddleOCR), and
groups the many reads of one car into a single, voted read. It then posts that read, with
a snapshot, to the Phase 2 API, retrying if the network fails. Training happens in Google
Colab, using two notebooks the owner runs on a free GPU, because datasets and GPUs aren't
reachable from the build machine. Evaluation scripts write real measurements to
`anpr/eval/results/`. CPU latency is already measured; accuracy waits for the Colab runs.

## Key concepts, explained simply

**Object detection vs OCR.** Detection answers "where is the plate?" (a box). OCR answers
"what does it say?" (text). Two specialised models in a row beat one model doing both.

**YOLO (You Only Look Once).** A detector that looks at the whole image once and predicts
many candidate boxes at the same time, each with a score. YOLOv8n ("nano", 3M parameters)
is small and fast; YOLOv8s ("small", 11M) is more accurate but about 3x slower.

**Fine-tuning.** Start from a model pre-trained on COCO (80 everyday object classes), then
train a little more on plate photos. It learns plates from a few hundred images because it
already knows edges, shapes and text-like patterns.

**mAP (mean Average Precision).** The standard detection score. mAP50 counts a box as
correct if it overlaps the true box by ≥ 50% (IoU); mAP50-95 averages over stricter
overlaps (50% to 95%) and rewards tight boxes, which matters because OCR needs the whole plate.

**IoU (Intersection over Union).** Overlap area ÷ combined area of two boxes. 1 = identical.

**NMS (non-maximum suppression).** YOLO proposes several boxes on the same plate. NMS keeps
the best one and drops the others that overlap it by more than a threshold.

**Letterbox.** Fitting a 1280x720 frame into the model's 640x640 input without stretching:
shrink it, then pad the empty bands with grey. Afterwards, boxes are mapped back by undoing
the padding and the scale.

**ONNX and ONNX Runtime.** ONNX is a standard file format for trained models. ONNX Runtime
runs it fast on CPU without PyTorch. Train in PyTorch (Colab), deploy as ONNX (gate).

**Quantisation (FP32 → INT8).** Store and compute with 8-bit integers instead of 32-bit
floats: 4x smaller and often faster. *Dynamic* quantisation converts weights only and is
built for transformer-style matrix multiplies. *Static* quantisation also converts the
activations, using a few sample images to "calibrate" their ranges, and suits CNNs like
YOLO. We measured it: static 32 ms vs FP32 65 ms, and dynamic was *slower* (88 ms).

**Character accuracy vs plate accuracy.** Plate accuracy = the whole plate exactly right
(what the gate needs). Character accuracy = 1 − edit distance ÷ length. It shows whether
misses are "one O/0 slip" (fixable) or garbage.

**Tracking/voting across frames.** A car is in view for ~15 analysed frames. Reads differ
a little; we group reads within one character of each other, sum confidences per distinct
text, and the top text wins. We send as soon as 3 reads agree, so the barrier doesn't wait.

**Exponential backoff.** After a failed request, wait 0.5 s, then 1 s, 2 s, 4 s… so a
struggling server isn't hammered. Safe because the API is idempotent (Phase 2).

## Files to read, in order

1. `anpr/gatesense_anpr/models.py`: the small data types passed between stages.
2. `anpr/gatesense_anpr/detector.py`: letterbox, `decode_yolov8`, `nms`. Read the docstring first.
3. `anpr/tests/test_detector.py`: how a fake YOLO output tensor and a tiny ONNX model test it.
4. `anpr/gatesense_anpr/ocr.py`: one interface, two engines; how two-line plates are joined.
5. `anpr/gatesense_anpr/tracker.py`: tracks, voting, early send, expiry.
6. `anpr/gatesense_anpr/pipeline.py`: one frame through the whole chain (it's short).
7. `anpr/gatesense_anpr/sources.py`: camera vs video vs folder, and why timestamps differ.
8. `anpr/gatesense_anpr/client.py`: what is retried and what isn't.
9. `anpr/gatesense_anpr/cli.py`: how it all gets wired from command-line flags.
10. `anpr/eval/benchmark_detector.py` and `anpr/eval/results/detector_latency.md`: the measurement.
11. `anpr/notebooks/01_train_plate_detector.ipynb`: the training run you'll do in Colab.
12. `anpr/eval/results/e2e_synthetic_video.md`: the end-to-end run, and the bug it found.
13. `docs/adr/0009-anpr-pipeline-and-model-choice.md`: decisions and the AGPL licence note.

## Decisions made and alternatives rejected

| Decision | Rejected | Why |
|---|---|---|
| ONNX Runtime + NumPy pre/post-processing | Ultralytics at run time; OpenCV DNN | No 2 GB PyTorch or AGPL code at the gate; ORT is faster on CPU |
| Backend does plate repair; worker only cleans | Repair in both places | One source of truth, can't drift apart |
| Vote across frames, send early after 3 agreeing reads | Send every frame; send only when the car leaves | Fewer duplicates without delaying the barrier |
| Static INT8 | Dynamic INT8 | Measured: dynamic is slower for this CNN |
| Selection rules written before the results | Pick the best-looking model afterwards | Avoids fitting the story to the numbers |
| Train in Colab, weights in GitHub Releases | Train locally; commit weights | No GPU locally; git is for code, not 12–45 MB binaries |
| Synthetic video + stand-in detector to test wiring | Wait for a trained model | Proves the plumbing now; clearly labelled as not an accuracy result |

## Likely interview questions

1. **Walk me through what happens to one video frame.**
   Letterbox to 640x640 → ONNX model → decode boxes, filter by score, NMS → crop each plate
   with a small margin → OCR → clean text, drop junk → add to the tracker → if 3 reads agree
   (or the car has gone), send one read with a snapshot to the API.

2. **Why ONNX instead of running the PyTorch model?**
   The gate machine has no GPU and shouldn't need a 2 GB framework. ONNX Runtime is small
   and fast on CPU, and the pre/post-processing is simple enough to own.

3. **How did you choose between YOLOv8n and YOLOv8s?**
   With a rule fixed in advance: take the bigger model only if it gains ≥ 0.02 mAP50-95 on
   held-out test images, because it costs ~3x the CPU time (measured: 65 vs 194 ms).

4. **What is mAP50-95 and why prefer it over mAP50?**
   It averages precision over IoU thresholds 0.5–0.95, so it rewards tight boxes. A loose
   box can cut off a character and ruin the OCR even though mAP50 counts it as correct.

5. **Why was dynamic INT8 slower?**
   It quantises weights but computes activations in float, adding conversion work around
   every convolution. Static quantisation calibrates activation ranges and keeps whole
   blocks in INT8, which is where the speed-up comes from.

6. **How do you avoid sending 15 events for one car?**
   The tracker groups reads within one edit, votes by summed confidence and sends once per
   sighting. The server's debounce and idempotency catch anything left.

7. **What if OCR reads `DL01AB1Z34` on some frames?**
   It joins the same track (1 edit away); the vote picks the text with the most total
   confidence. If it still wins, the server repairs Z→2 by position anyway.

8. **What if the network is down?**
   The client retries with exponential backoff on network errors, 429 and 5xx, but not on
   other 4xx. Retries are safe because the API deduplicates by device, text and capture time.
   Buffering to disk for long outages is Phase 7.

9. **How do you know the pipeline works without a trained model?**
   Unit tests use fake tensors and tiny generated ONNX models. A synthetic gate video with a
   stand-in detector ran through real EasyOCR into the real API: 4 cars → 4 events. It even
   found a plate-repair bug. That proves the wiring, not the accuracy.

10. **What would you do to improve accuracy at a real gate?**
    Fine-tune on photos from that camera (night/rain/angle), evaluate per condition, and
    retrain OCR on the `plate_corrections` that guards create: real errors, correctly labelled.

## Exercise

1. Run `uv run gatesense-anpr --simulate 8 --dry-run --seed 2` in `anpr/`. Which reads
   have look-alike noise? Which would go to the guard's review queue (confidence < 0.80)?
2. In `tests/test_tracker.py`, write a test where OCR alternates `HR26DK8337` (0.6) and
   `HR26DKB337` (0.95) for 4 frames with `min_agreeing_reads=3`. Before running it, decide:
   is anything sent early? Which text wins when the track expires, and why?
