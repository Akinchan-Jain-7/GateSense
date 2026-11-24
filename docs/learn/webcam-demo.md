# Study guide: the laptop webcam demo

## What we built and why

The laptop webcam can now act as the gate camera, with a live page showing what the
camera sees and what the server decided. A resident's car is logged automatically. A new
car gets a **Register this visitor** button that opens the guard console's form with the
plate filled in. One command (`scripts/webcam-demo.ps1`) sets it all up. Walkthrough:
[docs/webcam-demo.md](../webcam-demo.md). Decisions: [ADR-0015](../adr/0015-laptop-webcam-demo.md).

## Files to read, in this order

1. `anpr/gatesense_anpr/live.py`: the preview. Start at `run_preview` (bottom), then
   `camera_loop`, `analysis_loop`, `LiveState`, `PreviewHandler`.
2. `anpr/gatesense_anpr/cli.py`: `preview()` builds the two lanes and starts it.
3. `anpr/gatesense_anpr/preview.html`: the page (plain HTML, CSS and a little JavaScript).
4. `backend/app/webcam_devices.py`: the setup command.
5. `frontend/src/features/guard/GuardConsole.tsx`: `registerLink` and the effect below it.
6. `backend/app/services/gate_events.py` + `debounce.py`: the `release` fix.

## Key concepts, simply

**Threads sharing state.** Three workers run at once: one reads the camera, one reads
plates, one serves the page. They share one `LiveState` object. Every method that touches
it takes a **lock** first, so two threads never change it at the same moment. Only the
analysis thread uses the pipeline; the page's buttons just leave a note (a flag) that the
analysis thread reads on its next loop. That is why there are no race conditions on the
tracker.

**Newest frame only.** The webcam gives ~30 frames a second; reading plates takes longer.
If we queued every frame, the preview would fall further and further behind. Instead the
camera thread overwrites one slot, and the analysis thread always takes the newest.

**Condition variable.** The video stream waits for a new frame with `Condition.wait_for`
instead of checking in a busy loop. The camera thread calls `notify_all()` when a frame
arrives.

**MJPEG.** A "video" that is just JPEG images one after another in one HTTP response
(`multipart/x-mixed-replace`). An `<img>` tag shows it as moving video. No video codec,
no JavaScript.

**One webcam, two lanes.** The server knows entry from exit by *which device* sent the
read. So the webcam is registered as two devices with two keys, and the Entry/Exit
buttons choose which key to send with. Each lane has its own offline buffer so a saved
read replays on the right lane.

**Why a web page and not a window?** The camera program uses the "headless" OpenCV build
(no windows) so it runs in Docker and on servers. A window needs the other build, and the
two can't be installed together. A small web page needs nothing extra.

**Local-only page security.** Three layers: listen on 127.0.0.1 (other computers can't
connect); check the `Host` header (stops *DNS rebinding*, where a malicious site makes
your browser treat its domain as 127.0.0.1); require a custom header on buttons (a page on
another site can't add one without asking permission first, and we never give it).

**Keys are stored hashed.** Like passwords, the server keeps only a SHA-256 of each
device key. So the setup command can't "show the key again": it makes a new one each run.

**The debounce bug we fixed.** Debounce marks a plate "seen" in Redis *before* the event
is saved. If saving then failed, the camera retried, and the retry was "seen just now":
ignored. The car vanished. Now, if saving fails, we remove our own mark (only if it is
still ours, checked inside one Redis script so nothing can change in between).

## Questions you might be asked

- *Why not do it all in the browser with the webcam API?* Then the server would run the
  ML model, and every gate's video would travel over the internet. Reading plates at the
  gate sends only small text reads and one snapshot per car, and keeps working offline.
- *How do you stop the preview from lagging?* Keep only the newest frame; analyse ~5 per
  second; send the video at most 15 frames a second; re-encode only when the picture or
  the boxes change.
- *What happens if the API is down during the demo?* The read is saved in SQLite and the
  page says *Server not reachable*; it is sent by itself when the API is back, and the
  page updates.
- *How did you find the debounce bug?* By running the whole chain for real (camera
  program → API) instead of only unit tests: object storage wasn't running, the save
  failed, and the retry came back "debounced" with no event. Then a test reproduced it
  before the fix.

## Try it

```bash
cd anpr && uv run pytest tests/test_live.py -q          # 46 tests, no camera needed
cd backend && uv run pytest tests/test_webcam_devices.py -q
```
