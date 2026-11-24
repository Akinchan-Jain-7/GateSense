"""Live preview: watch what the camera sees and what the server decided, in a browser tab.

    gatesense-anpr --source 0 --preview        # laptop webcam, page opens by itself

Made for demos and for setting a camera up. Three threads share one `LiveState`:

    camera thread    reads frames as fast as the camera gives them (keeps the latest only)
    analysis thread  every 1/sample_fps s: detect -> OCR -> track -> send (the normal
                     pipeline), and remembers the boxes it found for drawing
    web server       http://127.0.0.1:8765: the page, an MJPEG video with the boxes drawn
                     in, the state as JSON, and buttons (entry/exit lane, scan again)

The analysis thread is the only one that touches the pipeline and the senders, so button
presses are passed to it as requests instead of changing the tracker directly.

One webcam, two lanes: with `ANPR_EXIT_DEVICE_KEY` set, the page can switch the camera
between the entry and the exit lane. Each lane sends with its own device key (the server
knows a lane by its device) and keeps its own offline buffer, so a read queued while the
API was down is always replayed on the lane it was seen on.

The page binds to this computer only (127.0.0.1) and checks the Host header, so another
website can't read it through DNS tricks. Buttons need a custom header, which a page on
another origin can't send without a CORS preflight this server never approves.
"""

import json
import logging
import signal
import threading
import time
import webbrowser
from collections import deque
from collections.abc import Callable, Iterator
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from typing import Any, Literal

import cv2
import numpy as np

from gatesense_anpr.models import Frame, Image, PlateRead
from gatesense_anpr.pipeline import Pipeline, Sighting
from gatesense_anpr.samples import CONDITIONS, SampleError, SampleStore

logger = logging.getLogger(__name__)

type Mode = Literal["entry", "exit"]
type Tone = Literal["ok", "warn", "bad", "info"]

PREVIEW_MAX_WIDTH = 960
PREVIEW_JPEG_QUALITY = 75
SIGHTING_TTL_SECONDS = 1.5  # boxes older than this aren't drawn (the car has moved)
POLL_EVERY_SECONDS = 5.0  # retry buffered reads this often while the camera is quiet
BUTTON_HEADER = "X-GateSense-Preview"

GREEN = (94, 197, 34)  # BGR
AMBER = (11, 158, 245)
WHITE = (255, 255, 255)
DARK = (23, 19, 17)


@dataclass
class Decision:
    """One plate the camera sent, and what the server made of it."""

    plate: str  # what the camera read (after its own clean-up)
    mode: Mode
    captured_at: str
    confidence: float
    outcome: str = "sending"  # sending / sent / buffered / rejected / printed / error
    status: str | None = None  # API: created / duplicate / debounced
    match_result: str | None = None  # API: resident / guest_pass / visitor / ...
    plate_normalized: str | None = None
    event_id: str | None = None
    needs_review: bool = False
    rejected_status: int | None = None  # HTTP status when the API refused the read
    rejected_detail: str | None = None
    tone: Tone = "info"
    title: str = "Sending to the server..."
    detail: str = ""


def explain(d: Decision) -> tuple[Tone, str, str]:
    """Plain words for the page: (tone, title, detail)."""
    if d.outcome == "printed":
        return "info", "Read (dry run)", "Printed only; nothing was sent to the server."
    if d.outcome == "buffered":
        return (
            "warn",
            "Server not reachable",
            "Saved on this computer; it is sent by itself when the server is back.",
        )
    if d.outcome == "rejected":
        if d.rejected_status in (401, 403):
            return (
                "bad",
                "The server doesn't know this camera",
                "Its key was replaced (demo data reset?). In backend, run "
                "`uv run python -m app.webcam_devices`, then restart the camera.",
            )
        reason = f" ({d.rejected_detail})" if d.rejected_detail else ""
        return "bad", "The server refused this read", f"HTTP {d.rejected_status}{reason}."
    if d.outcome == "error":
        return "bad", "Something went wrong", "See the terminal for the details."
    if d.outcome == "sending":
        return "info", "Sending to the server...", ""
    if d.status == "debounced":
        return (
            "info",
            "Same car, seen a moment ago",
            "Ignored: one car in front of the camera is one event. Press Scan again "
            "after 30 seconds, or switch lanes.",
        )
    if d.status == "duplicate":
        return "info", "Already logged", "The server had this exact read already."
    entry = d.mode == "entry"
    match d.match_result:
        case "resident":
            if entry:
                return "ok", "Resident car: entry logged", "The barrier would open by itself."
            return "ok", "Resident car: exit logged", "The open entry for this car is closed."
        case "guest_pass":
            return "ok", "Guest pass: let in", "Matched a resident's guest pass by plate."
        case "visitor":
            if entry:
                return "ok", "Expected visitor: let in", "The visit timer has started."
            return "ok", "Visitor left", "The visit is closed."
        case "watchlist":
            return "bad", "Watchlist plate", "A red alert is on the guard console."
        case "unknown":
            if entry:
                return (
                    "warn",
                    "New car: register the visitor",
                    "Not a resident and no guest pass. Take the visitor's name, phone, "
                    "email and flat on the guard console; the resident then approves.",
                )
            return "warn", "Unknown car leaving", "Logged; no open visit for this plate."
        case "low_confidence":
            return (
                "warn",
                "Not sure of the plate",
                "Sent to the guard's review queue to check the number by eye.",
            )
    return "info", "Logged", ""


@dataclass
class LiveState:
    """Everything the three threads share. Methods take the lock; fields don't."""

    modes: tuple[Mode, ...]
    console_url: str
    source: str
    mode: Mode = "entry"
    lock: threading.Lock = field(default_factory=threading.Lock)
    new_frame: threading.Condition = field(init=False)
    frame: Image | None = None
    frame_seq: int = 0
    sightings: list[Sighting] = field(default_factory=list)
    sightings_at: float = 0.0
    decisions: deque[Decision] = field(default_factory=lambda: deque(maxlen=8))
    camera_error: str | None = None
    source_ended: bool = False
    analysed_fps: float = 0.0
    reset_requested: bool = False
    stopping: threading.Event = field(default_factory=threading.Event)
    samples: SampleStore | None = None  # "Save for testing" (labelled photos)
    _jpeg: tuple[tuple[int, float], bytes] | None = None

    def __post_init__(self) -> None:
        self.new_frame = threading.Condition(self.lock)

    # --- camera thread ---
    def put_frame(self, image: Image) -> None:
        with self.new_frame:
            self.frame = image
            self.frame_seq += 1
            self.camera_error = None
            self.new_frame.notify_all()

    def set_camera_error(self, message: str | None) -> None:
        with self.lock:
            self.camera_error = message

    def end_source(self) -> None:
        with self.new_frame:
            self.source_ended = True
            self.new_frame.notify_all()

    # --- analysis thread ---
    def latest_frame(self) -> tuple[int, Image | None]:
        with self.lock:
            return self.frame_seq, self.frame

    def set_sightings(self, sightings: list[Sighting], fps: float) -> None:
        with self.lock:
            self.sightings = sightings
            self.sightings_at = time.monotonic()
            self.analysed_fps = fps

    def take_reset(self) -> bool:
        with self.lock:
            requested, self.reset_requested = self.reset_requested, False
            return requested

    def current_mode(self) -> Mode:
        with self.lock:
            return self.mode

    def add_pending(self, read: PlateRead, mode: Mode) -> Decision:
        decision = Decision(
            plate=read.plate_text,
            mode=mode,
            captured_at=read.captured_at.isoformat(),
            confidence=read.confidence,
        )
        with self.lock:
            self.decisions.appendleft(decision)
        return decision

    def record_result(self, read: PlateRead, mode: Mode, result: dict[str, Any]) -> None:
        """An API reply: for a read just sent, or one replayed from the offline buffer."""
        with self.lock:
            decision = self._find(read, mode)
            event = result.get("event")
            event = event if isinstance(event, dict) else {}
            decision.outcome = "sent"
            decision.status = _str(result.get("status"))
            decision.match_result = _str(event.get("match_result"))
            decision.plate_normalized = _str(event.get("plate_normalized"))
            decision.event_id = _str(event.get("id"))
            decision.needs_review = bool(event.get("needs_review"))
            decision.tone, decision.title, decision.detail = explain(decision)

    def record_rejection(
        self, read: PlateRead, mode: Mode, status_code: int, detail: object
    ) -> None:
        """The API refused a read for good (bad key, invalid data)."""
        with self.lock:
            decision = self._find(read, mode)
            decision.outcome = "rejected"
            decision.rejected_status = status_code
            decision.rejected_detail = str(detail)[:200] if detail else None
            decision.tone, decision.title, decision.detail = explain(decision)

    def _find(self, read: PlateRead, mode: Mode) -> Decision:
        """The decision for `read` (call with the lock held); new if it came from the
        offline buffer of an earlier run."""
        captured = read.captured_at.isoformat()
        for d in self.decisions:
            if d.plate == read.plate_text and d.captured_at == captured and d.mode == mode:
                return d
        decision = Decision(read.plate_text, mode, captured, read.confidence)
        self.decisions.appendleft(decision)
        return decision

    def set_outcome(self, decision: Decision, outcome: str) -> None:
        with self.lock:
            if decision.outcome == "sending":  # a reply may already have filled it in
                decision.outcome = outcome
            decision.tone, decision.title, decision.detail = explain(decision)

    # --- web server ---
    def request_mode(self, mode: str) -> bool:
        with self.lock:
            if mode not in self.modes:
                return False
            if mode != self.mode:
                self.mode = mode  # narrowed to a Mode by the check above
                self.reset_requested = True  # a half-seen plate belongs to the old lane
            return True

    def request_rescan(self) -> None:
        with self.lock:
            self.reset_requested = True

    def save_sample(self, plate: str, condition: str) -> str:
        """Save the current camera frame, labelled, for accuracy tests."""
        if self.samples is None:
            raise SampleError("Saving test photos is off")
        with self.lock:
            image = None if self.frame is None else self.frame.copy()
        if image is None:
            raise SampleError("No camera picture yet")
        return self.samples.save(image, plate, condition)

    def snapshot(self) -> dict[str, Any]:
        samples = (
            {
                "folder": str(self.samples.root),
                "counts": self.samples.summary(),
                "conditions": CONDITIONS,
            }
            if self.samples
            else None
        )
        with self.lock:
            return {
                "mode": self.mode,
                "modes": list(self.modes),
                "console_url": self.console_url.rstrip("/"),
                "source": self.source,
                "camera_error": self.camera_error,
                "has_frame": self.frame is not None,
                "source_ended": self.source_ended,
                "analysed_fps": round(self.analysed_fps, 1),
                "plates_in_view": [
                    s.text or "" for s in self._fresh_sightings() if s.text is not None
                ],
                "decisions": [asdict(d) for d in self.decisions],
                "samples": samples,
            }

    def jpeg(self) -> bytes | None:
        """The latest frame with boxes drawn, as JPEG (cached until something changes)."""
        with self.lock:
            if self.frame is None:
                return None
            key = (self.frame_seq, self.sightings_at)
            if self._jpeg and self._jpeg[0] == key:
                return self._jpeg[1]
            image, sightings = self.frame, self._fresh_sightings()
        data = render(image, sightings)
        with self.lock:
            self._jpeg = (key, data)
        return data

    def wait_for_frame(self, after: int, timeout: float) -> int:
        with self.new_frame:
            self.new_frame.wait_for(
                lambda: self.frame_seq != after or self.source_ended or self.stopping.is_set(),
                timeout,
            )
            return self.frame_seq

    def _fresh_sightings(self) -> list[Sighting]:
        if time.monotonic() - self.sightings_at > SIGHTING_TTL_SECONDS:
            return []
        return self.sightings


def _str(value: object) -> str | None:
    return None if value is None else str(value)


def render(image: Image, sightings: list[Sighting]) -> bytes:
    """Draw the plate boxes and their text onto a copy of the frame; return a JPEG."""
    canvas = image.copy()
    height, width = canvas.shape[:2]
    thickness = max(2, width // 400)
    font_scale = max(0.6, width / 1400)
    for s in sightings:
        colour = GREEN if s.text else AMBER
        x1, y1, x2, y2 = (round(v) for v in (s.box.x1, s.box.y1, s.box.x2, s.box.y2))
        cv2.rectangle(canvas, (x1, y1), (x2, y2), colour, thickness)
        label = s.text or "reading..."
        (tw, th), base = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, font_scale, 2)
        top = max(0, y1 - th - base - 8)
        cv2.rectangle(canvas, (x1, top), (x1 + tw + 12, top + th + base + 8), colour, -1)
        cv2.putText(
            canvas,
            label,
            (x1 + 6, top + th + 4),
            cv2.FONT_HERSHEY_SIMPLEX,
            font_scale,
            DARK,
            2,
            cv2.LINE_AA,
        )
    if width > PREVIEW_MAX_WIDTH:
        scale = PREVIEW_MAX_WIDTH / width
        canvas = np.asarray(
            cv2.resize(canvas, (PREVIEW_MAX_WIDTH, round(height * scale))), dtype=np.uint8
        )
    ok, buffer = cv2.imencode(".jpg", canvas, [cv2.IMWRITE_JPEG_QUALITY, PREVIEW_JPEG_QUALITY])
    if not ok:
        raise ValueError("Could not encode preview frame")
    return bytes(buffer)


# --- threads ---------------------------------------------------------------------------


def camera_loop(state: LiveState, open_capture: Callable[[], Any], *, live: bool) -> None:
    """Read frames into `state` until stopped. A video file plays at its own speed and the
    last frame stays on screen when it ends; a camera that drops out is reopened."""
    capture = None
    try:
        while not state.stopping.is_set():
            if capture is None:
                try:
                    capture = open_capture()
                except OSError as error:
                    state.set_camera_error(str(error))
                    if not live:
                        state.end_source()
                        return
                    state.stopping.wait(2.0)
                    continue
                fps = capture.get(cv2.CAP_PROP_FPS) or 25.0
                delay = 0.0 if live else 1.0 / max(1.0, min(fps, 60.0))
            started = time.monotonic()
            ok, image = capture.read()
            if not ok:
                if not live:
                    state.end_source()
                    return
                state.set_camera_error("The camera stopped sending pictures; retrying...")
                capture.release()
                capture = None
                state.stopping.wait(1.0)
                continue
            state.put_frame(np.asarray(image, dtype=np.uint8))
            if delay:
                state.stopping.wait(max(0.0, delay - (time.monotonic() - started)))
    finally:
        if capture is not None:
            capture.release()


type SinkFn = Callable[[PlateRead], str]


@dataclass
class Lane:
    send: SinkFn
    poll: Callable[[], None]


def analysis_loop(
    state: LiveState,
    pipeline: Pipeline,
    lanes: dict[Mode, Lane],
    *,
    sample_fps: float,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> None:
    """Run the pipeline on the newest frame, `sample_fps` times a second at most."""
    interval = 1.0 / sample_fps
    last_seq = -1
    last_poll = time.monotonic()
    times: deque[float] = deque(maxlen=10)
    while not state.stopping.is_set():
        started = time.monotonic()
        if state.take_reset():
            pipeline.tracker.reset()
            state.set_sightings([], state.analysed_fps)
        seq, image = state.latest_frame()
        if image is not None and seq != last_seq:
            last_seq = seq
            mode = state.current_mode()
            try:
                reads = pipeline.process(Frame(image=image, captured_at=clock()))
            except Exception:  # keep the preview alive; the terminal shows the error
                logger.exception("analysing a frame failed")
                reads = []
            times.append(time.monotonic())
            fps = (len(times) - 1) / (times[-1] - times[0]) if len(times) > 1 else 0.0
            state.set_sightings(pipeline.last_sightings, fps)
            for read in reads:
                deliver(state, lanes[mode], read, mode)
        elif state.source_ended and image is not None:
            for read in pipeline.finish():
                deliver(state, lanes[state.current_mode()], read, state.current_mode())
        if time.monotonic() - last_poll > POLL_EVERY_SECONDS:
            last_poll = time.monotonic()
            for lane in lanes.values():
                try:
                    lane.poll()
                except Exception:
                    logger.exception("retrying buffered reads failed")
        state.stopping.wait(max(0.0, interval - (time.monotonic() - started)))


def deliver(state: LiveState, lane: Lane, read: PlateRead, mode: Mode) -> None:
    decision = state.add_pending(read, mode)
    try:
        outcome = lane.send(read)
    except Exception:
        logger.exception("sending %s failed", read.plate_text)
        outcome = "error"
    state.set_outcome(decision, outcome)


# --- web server ------------------------------------------------------------------------


def page_html() -> bytes:
    return resources.files("gatesense_anpr").joinpath("preview.html").read_bytes()


class PreviewServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address: tuple[str, int], state: LiveState) -> None:
        self.state = state
        super().__init__(address, PreviewHandler)

    def _host_port(self) -> tuple[str, int]:
        host, port = self.server_address[:2]
        return (host.decode() if isinstance(host, bytes) else str(host)), int(port)

    @property
    def url(self) -> str:
        host, port = self._host_port()
        shown = "127.0.0.1" if host in ("0.0.0.0", "") else host  # noqa: S104
        return f"http://{shown}:{port}/"

    def allowed_hosts(self) -> set[str]:
        host, port = self._host_port()
        return {f"127.0.0.1:{port}", f"localhost:{port}", f"[::1]:{port}", f"{host}:{port}"}


class PreviewHandler(BaseHTTPRequestHandler):
    server: PreviewServer
    protocol_version = "HTTP/1.1"

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002 - stdlib name
        logger.debug("preview: " + format, *args)

    def do_GET(self) -> None:
        if not self._host_ok():
            return
        path = self.path.split("?", 1)[0]
        if path == "/":
            self._send(HTTPStatus.OK, page_html(), "text/html; charset=utf-8", csp=True)
        elif path == "/state":
            self._json(HTTPStatus.OK, self.server.state.snapshot())
        elif path == "/frame.jpg":
            data = self.server.state.jpeg()
            if data is None:
                self._json(HTTPStatus.SERVICE_UNAVAILABLE, {"detail": "no picture yet"})
            else:
                self._send(HTTPStatus.OK, data, "image/jpeg")
        elif path == "/stream.mjpg":
            self._stream()
        else:
            self._json(HTTPStatus.NOT_FOUND, {"detail": "not found"})

    def do_POST(self) -> None:
        if not self._host_ok():
            return
        if self.headers.get(BUTTON_HEADER) != "1":
            self._json(HTTPStatus.FORBIDDEN, {"detail": f"missing {BUTTON_HEADER} header"})
            return
        length = min(int(self.headers.get("Content-Length") or 0), 1024)
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except ValueError:
            body = None
        state = self.server.state
        if self.path == "/mode" and isinstance(body, dict):
            if state.request_mode(str(body.get("mode"))):
                self._json(HTTPStatus.OK, state.snapshot())
            else:
                self._json(HTTPStatus.BAD_REQUEST, {"detail": f"mode must be one of {state.modes}"})
        elif self.path == "/rescan":
            state.request_rescan()
            self._json(HTTPStatus.OK, state.snapshot())
        elif self.path == "/samples" and isinstance(body, dict):
            try:
                saved = state.save_sample(str(body.get("plate", "")), str(body.get("condition")))
            except SampleError as error:
                self._json(HTTPStatus.BAD_REQUEST, {"detail": str(error)})
            else:
                self._json(HTTPStatus.OK, {"saved": saved, **state.snapshot()})
        else:
            self._json(HTTPStatus.NOT_FOUND, {"detail": "not found"})

    def _host_ok(self) -> bool:
        if self.headers.get("Host") in self.server.allowed_hosts():
            return True
        self._json(HTTPStatus.MISDIRECTED_REQUEST, {"detail": "unexpected Host header"})
        return False

    def _stream(self) -> None:
        state = self.server.state
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True
        try:
            for data in frames(state):
                self.wfile.write(
                    b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: "
                    + str(len(data)).encode()
                    + b"\r\n\r\n"
                    + data
                    + b"\r\n"
                )
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass  # the tab was closed

    def _json(self, status: HTTPStatus, body: object) -> None:
        self._send(status, json.dumps(body).encode(), "application/json")

    def _send(
        self, status: HTTPStatus, data: bytes, content_type: str, *, csp: bool = False
    ) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        if csp:
            self.send_header(
                "Content-Security-Policy",
                "default-src 'self'; img-src 'self'; style-src 'unsafe-inline'; "
                "script-src 'unsafe-inline'; connect-src 'self'; frame-ancestors 'none'",
            )
        self.end_headers()
        self.wfile.write(data)


def frames(state: LiveState, max_fps: float = 15.0) -> Iterator[bytes]:
    """JPEGs for the MJPEG stream: a new one when the camera or the boxes change."""
    gap = 1.0 / max_fps
    last_sent = 0.0
    last_key: tuple[int, float] | None = None
    while not state.stopping.is_set():
        state.wait_for_frame(last_key[0] if last_key else -1, timeout=1.0)
        if state.stopping.is_set():
            return
        key = (state.frame_seq, state.sightings_at)
        if key == last_key and not state.source_ended:
            continue
        wait = gap - (time.monotonic() - last_sent)
        if wait > 0:
            state.stopping.wait(wait)
        data = state.jpeg()
        if data is None:
            continue
        last_key, last_sent = key, time.monotonic()
        yield data
        if state.source_ended:
            # A finished video: keep the last picture, refresh slowly for new boxes.
            state.stopping.wait(0.5)


# --- entry point -----------------------------------------------------------------------


def run_preview(
    state: LiveState,
    *,
    pipeline: Pipeline,
    lanes: dict[Mode, Lane],
    open_capture: Callable[[], Any],
    live: bool,
    sample_fps: float,
    host: str,
    port: int,
    open_browser: bool = True,
) -> None:
    """Start everything and block until Ctrl+C (or `state.stopping` is set)."""
    server = PreviewServer((host, port), state)
    threads = [
        threading.Thread(
            target=camera_loop, args=(state, open_capture), kwargs={"live": live}, daemon=True
        ),
        threading.Thread(
            target=analysis_loop,
            args=(state, pipeline, lanes),
            kwargs={"sample_fps": sample_fps},
            daemon=True,
        ),
        threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.2}, daemon=True),
    ]
    for thread in threads:
        thread.start()
    lanes_text = " and ".join(lanes)
    print(f"\nLive preview: {server.url}  (lanes: {lanes_text}; Ctrl+C to stop)\n", flush=True)
    if open_browser:
        webbrowser.open(server.url)
    try:
        while not state.stopping.is_set():
            state.stopping.wait(0.5)
    except KeyboardInterrupt:
        print("Stopping...", flush=True)
    finally:
        # Ctrl+C often arrives twice (once through `uv run`); a second one mustn't break
        # the clean-up, which waits for the threads and drains the offline buffers.
        main = threading.current_thread() is threading.main_thread()
        if main:
            signal.signal(signal.SIGINT, signal.SIG_IGN)
        state.stopping.set()
        with state.new_frame:
            state.new_frame.notify_all()
        server.shutdown()
        server.server_close()
        for thread in threads[:2]:
            thread.join(timeout=5)
        if main:  # Ctrl+C works again (e.g. while the buffers drain)
            signal.signal(signal.SIGINT, signal.default_int_handler)
