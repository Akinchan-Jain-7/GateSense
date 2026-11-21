# End-to-end run: synthetic gate video → real OCR → real API

What this shows: the **wiring** of the whole chain works. A video file goes through ONNX
Runtime, plate crop, **real EasyOCR**, the frame tracker and the HTTP client, into the
running backend, which stores events, matches residents and raises watchlist alerts.

What it does **not** show: detection accuracy on real cameras. The detector here is a
stand-in that always returns the box where the plates are drawn
(`eval/make_demo_video.py`). Real detector and OCR accuracy come from the Colab notebooks
and are pending (see `README.md` in this folder).

## Setup

- Video: `eval/make_demo_video.py`, 640x360 @ 25 fps, 4 cars, each stopped at the barrier
  for 3 s with camera noise, 4 s of empty lane between cars. Plates rendered with OpenCV's
  Hershey font (much cleaner than a real plate, but not the HSRP font).
- Worker: `python -m gatesense_anpr --source gate.avi`, 5 analysed frames per second,
  tracker sends early after 3 agreeing reads, EasyOCR 1.7 on CPU.
- Backend: local stack with seed data; the Main Gate entry camera's device key.
- Run: 2026-11-21, on the 2-core cloud build machine.

## Result

| Car (true plate) | Sent by the worker | Stored by the API | Match | Confidence |
|---|---|---|---|---|
| UP16ZD2011 (resident) | `UP16ZD2011` | `UP16ZD2011` | low_confidence → review queue | 0.74 |
| UP14RS0472 (resident) | `UP14RS0472` | `UP14RS0472` | resident | 0.96 |
| HR26DK8337 (watchlist) | `HR26DK8337` | `HR26DK8337` | watchlist (1 alert raised) | 0.99 |
| KA05MN0042 (unknown) | `KAOSMNO042` | `KA05MN0042` (3 look-alikes repaired) | low_confidence → review queue | 0.74 |

- **4 cars → 4 events**: about 15 analysed frames per car were grouped into one read each.
- Every event has its snapshot stored.
- All 4 plates were read correctly after the server's repair. Two reads fell under the
  0.80 confidence threshold, so they went to the guard instead of acting on a guess.

## A bug this run found

The first run stored the 4th car as `KA0SMN0042`: the plate repair accepted a 1-digit
district outside Delhi too easily. Fixed in `backend/app/services/plates.py` with a
regression case (`KAOSMNO042` → `KA05MN0042`) in `test_plate_reader.py`, then re-run (the
table above is the re-run).
