# ADR-0015: Laptop webcam demo (live preview)

- **Status:** Accepted
- **Date:** 2026-11-24
- **Phase:** after 9 (demo tooling)

## Context

The owner demos GateSense on their own laptop (evaluations, interviews) and wants the
laptop webcam to act as the gate camera: hold up a plate, see a resident's entry logged,
see a new car handed to the guard to register. The ANPR worker could already read a
webcam (`--source 0`), but it had no screen: nobody could see what it saw or what the
server decided, and one webcam could only be one lane.

## Decisions

1. **Build on the existing worker, not a new browser camera.** Options were: (a) a preview
   for the worker, (b) a "gate camera" page in the web app that sends browser webcam frames
   to the server for reading, (c) the worker streaming into the guard console. (b) would
   move ML into the API image and contradict the edge design the project explains (the
   camera reads plates, the server decides). (c) has the most moving parts for a live
   demo. (a) reuses everything and shows the architecture as two windows: camera at the
   gate, guard console.
2. **The preview is a local web page, not an OpenCV window.** The worker depends on
   `opencv-python-headless` (no GUI, so it runs in Docker and on servers). An OpenCV window
   would need the GUI build, which can't be installed next to the headless one. A page
   served by the standard library (`http.server`) needs no new dependency, looks like the
   rest of the product (same colours, plate chip) and can link to the guard console.
   Video is MJPEG (`multipart/x-mixed-replace`), which an `<img>` plays with no JavaScript.
3. **Three threads, one owner of the pipeline.** Camera thread (newest frame only),
   analysis thread (pipeline + sending), web server. Buttons set flags that the analysis
   thread acts on, so the tracker is never touched by two threads.
4. **One webcam = two devices.** The API knows a lane by its device (ADR-0005), so the
   webcam gets an entry device and an exit device, each with its own key
   (`ANPR_DEVICE_KEY`, `ANPR_EXIT_DEVICE_KEY`) and its own offline buffer file. A buffered
   read always replays on the lane it was seen on. No API change was needed.
5. **`python -m app.webcam_devices` sets the webcam up.** It creates or reuses the two
   devices on a gate, rotates their keys (keys are stored hashed, so a new key is the only
   way to hand one out), writes them to `anpr/.env` keeping the other lines, writes an
   audit entry per device, and prints plates to show (a resident's, the watchlist's, an
   unknown one) plus a page of them for a phone. Running it again is always safe.
6. **The page is for this computer only.** It binds to 127.0.0.1, answers only requests
   whose `Host` is its own address (blocks DNS rebinding), and its POST buttons need a
   custom header (a page on another site can't send one without a CORS preflight, which
   the server never approves). CSP `frame-ancestors 'none'`.
7. **New-car hand-off by link.** *Register this visitor* opens
   `/guard?register=<plate>&event=<gate event id>`; the console opens its existing form
   prefilled and linked to the car's read, then removes the parameters. The login page
   already keeps the full link through sign-in.

## Found and fixed on the way

- **A failed save left the plate debounced.** The API marked a plate "seen" (Redis) before
  saving the event; if saving the snapshot failed (500), the camera's retry was answered
  `debounced` with no event, and the car was never logged. The mark is now released when
  storing fails, only if it still names that event. Test:
  `test_a_retry_after_a_failed_save_is_a_new_read_not_debounced`.
- **`ANPR_BUFFER_PATH=` (empty) didn't turn the buffer off**: pydantic read `""` as the
  path `.`, so the worker crashed. Empty now means off, as the README says.
- **The offline buffer's SQLite connection is shared across threads** (the preview opens
  it on one and sends from another): `check_same_thread=False` plus a lock per call.

## Consequences

- A real camera install is unchanged: no `--preview`, one key, same code path.
- The preview's decisions come from the API's reply, so it shows exactly what the server
  decided, including repaired plates and debounce.
- The page can't show the resident's flat for a resident car: a device key may post reads
  but not read residents' data, and that stays so.
- The detector was trained on photos of cars; a plate alone on a phone is detected less
  reliably than a photo of a car's front. The guide says so.
