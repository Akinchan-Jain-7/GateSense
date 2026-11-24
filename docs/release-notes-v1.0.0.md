# GateSense v1.0.0

The first complete version of GateSense: number-plate entry for residents,
resident-approved visitors, and automatic follow-up of overstaying vehicles.

The numbers below are the ones in the README, all measured. The trained plate detector
is published separately as the `models-v1` release (`plate_detector.onnx`, SHA-256
`63e5d3e1…6a977`); `uv run python -m gatesense_anpr.download_model` installs and checks it.

## What's in it

**Gate and plates**
- Cameras post plate reads with confidence, lane and a snapshot (device API keys, stored hashed)
- Indian plate normaliser: format check (state series, BH series), look-alike fixes by
  position (O/0, I/1, B/8, S/5, Z/2), bounded fuzzy match against known plates
- Debounce per plate per lane (Redis) and idempotency by event hash
- Residents logged in and out automatically; watchlist alerts; low-confidence reads go to
  a guard review queue, and the guard's corrections are kept as labelled data

**Visits**
- A visit state machine (`PENDING_APPROVAL → APPROVED → INSIDE → OVERSTAYED → ESCALATED →
  EXITED`, plus `DENIED` and `EXPIRED`) where every transition is checked and logged
- Visit categories with time limits the admin can change (guest, delivery, cab, service)
- Real-time approval on the web (WebSocket) and Telegram, with a 3-minute guard fallback
- Guest passes by plate or one-time code (hashed), with a time window and a usage limit

**Follow-up and housekeeping (Celery Beat)**
- Escalation ladder: emails at the limit, a reminder at +30 min, a guard call task at +60 min
- Signed, expiring visitor links that show the time left
- Notification outbox for email and Telegram with retries and backoff
- Nightly reconciliation of unmatched entries and exits; daily privacy purge (90 days)

**ANPR worker**
- YOLOv8n plate detector on ONNX Runtime (INT8 option), OCR, a frame tracker that votes
  across frames, and the API client
- Inputs: webcam / RTSP, video file, image folder, simulated reads
- Offline mode: reads buffered in SQLite and replayed in order when the API is back

**Laptop webcam demo**
- `gatesense-anpr --source 0 --preview`: a local page with the camera picture, plate boxes
  and the server's decision for each car; one webcam covers the entry and exit lanes
- `python -m app.webcam_devices` sets the webcam up as two cameras; `scripts/webcam-demo.ps1`
  starts everything on Windows in one command
- *Register this visitor* opens the guard console's form prefilled for a new car
- *Save for testing* collects labelled webcam photos for real accuracy measurements

**Web app**
- Guard console (dark by default, Hindi and English), Resident PWA, Admin dashboard with
  analytics, management tables, watchlist, audit log and settings; a landing page
- Light and dark themes; automated WCAG 2.1 AA checks on 18 screens
- Demo mode with one-click logins and a "Reset demo" action

**Hardening and operations**
- JWT access and refresh tokens, role-based access on every route
- Rate limits, security headers, CORS locked down, input size limits, audit log
- Request ids in structured JSON logs, Prometheus metrics
- Production Docker images (non-root, healthchecks) for amd64 and arm64 on GHCR,
  `docker-compose.prod.yml` with Caddy and automatic HTTPS, a nightly demo reset,
  and a vehicle simulator that keeps the demo alive

## Measured results

| What | Result |
|---|---|
| Plate detector (YOLOv8n), 354 test photos from a different dataset | mAP@0.5 0.745, mAP@0.5:0.95 0.384, recall 0.87 |
| Detector speed on CPU, 1280×720, 2 cores | 65 ms FP32, 32 ms INT8 static |
| Gate-event ingestion, one API process | 159 req/s, p95 410 ms; first bottleneck fixed (+30% / +58%) |
| Reading settings on 140 rendered webcam-like cars (7 conditions) | 80.0% right after the server's repair; five tweaks measured, none better beyond noise |
| Tests | backend 528 (96%), ANPR 124 (92%), web 55 (81% lines), simulator 17, 3 Playwright journeys, 42 accessibility checks |

## Not in this release

- OCR accuracy per condition on real photos (the webcam's *Save for testing* collects them)
- A live public demo (waits for the hosting decision in ADR-0014)
- Multi-society tenancy, SMS and voice calls, native apps, tailgating detection

See the README's "Known limitations" for details.
