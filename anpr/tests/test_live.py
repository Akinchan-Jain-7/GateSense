"""The live preview (--preview): shared state, threads, the local web page, CLI wiring."""

import http.client
import json
import threading
import time
from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import pytest

from gatesense_anpr import cli, live
from gatesense_anpr.client import GateEventClient, GateEventRejectedError
from gatesense_anpr.config import AnprSettings
from gatesense_anpr.live import (
    Decision,
    Lane,
    LiveState,
    PreviewServer,
    analysis_loop,
    camera_loop,
    explain,
    render,
    run_preview,
)
from gatesense_anpr.models import Box, Image, PlateRead
from gatesense_anpr.pipeline import Pipeline, Sighting
from gatesense_anpr.tracker import PlateTracker
from tests.conftest import T0
from tests.test_pipeline_and_sources import FakeDetector, ScriptedOcr

READ = PlateRead(plate_text="KAOSMN4821", confidence=0.9, captured_at=T0)


def reply(match: str, *, status: str = "created", plate: str = "KA05MN4821") -> dict[str, Any]:
    return {
        "status": status,
        "event": {
            "id": "6f3511ae-06fb-4b2a-83f8-884fff649f5f",
            "plate_normalized": plate,
            "match_result": match,
            "needs_review": match == "low_confidence",
        },
    }


def recorder(sent: list[Any], tag: str | None = None) -> Lane:
    """A lane that records what it was asked to send."""

    def send(read: PlateRead) -> str:
        sent.append((tag, read.plate_text) if tag else read.plate_text)
        return "sent"

    return Lane(send=send, poll=lambda: None)


def state(modes: tuple[live.Mode, ...] = ("entry", "exit")) -> LiveState:
    return LiveState(modes=modes, console_url="http://localhost:5173/", source="0")


def wait_until(check: Any, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while not check():
        if time.monotonic() > deadline:
            raise AssertionError("timed out")
        time.sleep(0.02)


# --- plain words ------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("mode", "outcome", "status", "match", "tone", "title"),
    [
        ("entry", "sent", "created", "resident", "ok", "Resident car: entry logged"),
        ("exit", "sent", "created", "resident", "ok", "Resident car: exit logged"),
        ("entry", "sent", "created", "guest_pass", "ok", "Guest pass: let in"),
        ("entry", "sent", "created", "visitor", "ok", "Expected visitor: let in"),
        ("exit", "sent", "created", "visitor", "ok", "Visitor left"),
        ("entry", "sent", "created", "watchlist", "bad", "Watchlist plate"),
        ("entry", "sent", "created", "unknown", "warn", "New car: register the visitor"),
        ("exit", "sent", "created", "unknown", "warn", "Unknown car leaving"),
        ("entry", "sent", "created", "low_confidence", "warn", "Not sure of the plate"),
        ("entry", "sent", "debounced", None, "info", "Same car, seen a moment ago"),
        ("entry", "sent", "duplicate", "resident", "info", "Already logged"),
        ("entry", "sent", "created", "something_new", "info", "Logged"),
        ("entry", "buffered", None, None, "warn", "Server not reachable"),
        ("entry", "printed", None, None, "info", "Read (dry run)"),
        ("entry", "error", None, None, "bad", "Something went wrong"),
        ("entry", "sending", None, None, "info", "Sending to the server..."),
    ],
)
def test_explain(
    mode: live.Mode,
    outcome: str,
    status: str | None,
    match: str | None,
    tone: str,
    title: str,
) -> None:
    decision = Decision("X", mode, T0.isoformat(), 0.9, outcome, status, match)
    assert explain(decision)[:2] == (tone, title)


def test_explain_rejections() -> None:
    bad_key = Decision("X", "entry", "t", 0.9, "rejected", rejected_status=401)
    assert "app.webcam_devices" in explain(bad_key)[2]
    invalid = Decision(
        "X", "entry", "t", 0.9, "rejected", rejected_status=422, rejected_detail="bad plate"
    )
    assert explain(invalid)[1:] == ("The server refused this read", "HTTP 422 (bad plate).")


# --- shared state -----------------------------------------------------------------------


def test_a_reply_fills_in_the_pending_decision() -> None:
    s = state()
    decision = s.add_pending(READ, "entry")
    s.record_result(READ, "entry", reply("unknown"))
    s.set_outcome(decision, "sent")

    [shown] = s.snapshot()["decisions"]
    assert shown["plate_normalized"] == "KA05MN4821"
    assert shown["title"] == "New car: register the visitor"
    assert shown["event_id"] == "6f3511ae-06fb-4b2a-83f8-884fff649f5f"


def test_a_reply_for_a_buffered_read_updates_it_later() -> None:
    s = state()
    decision = s.add_pending(READ, "entry")
    s.set_outcome(decision, "buffered")
    assert s.snapshot()["decisions"][0]["title"] == "Server not reachable"

    s.record_result(READ, "entry", reply("resident"))  # replayed when the API came back
    assert s.snapshot()["decisions"][0]["title"] == "Resident car: entry logged"


def test_a_reply_from_an_earlier_run_is_added() -> None:
    s = state()
    s.record_result(READ, "exit", reply("resident"))
    assert s.snapshot()["decisions"][0]["title"] == "Resident car: exit logged"


def test_a_rejection_is_recorded_with_its_reason() -> None:
    s = state()
    decision = s.add_pending(READ, "entry")
    s.record_rejection(READ, "entry", 401, "Invalid or inactive device API key")
    s.set_outcome(decision, "rejected")
    shown = s.snapshot()["decisions"][0]
    assert shown["title"] == "The server doesn't know this camera"
    assert shown["rejected_status"] == 401


def test_lane_requests() -> None:
    s = state(("entry",))
    assert not s.request_mode("exit")  # no exit key
    assert s.request_mode("entry")
    assert not s.take_reset()  # same lane: nothing to forget

    two = state()
    assert two.request_mode("exit")
    assert two.current_mode() == "exit"
    assert two.take_reset()  # a half-seen plate belonged to the entry lane
    assert not two.take_reset()
    two.request_rescan()
    assert two.take_reset()


def test_old_decisions_drop_off() -> None:
    s = state()
    for i in range(12):
        s.add_pending(PlateRead(f"DL01AB{i:04d}", 0.9, T0), "entry")
    assert len(s.snapshot()["decisions"]) == 8


def test_jpeg_is_cached_until_the_picture_or_boxes_change(frame_image: Image) -> None:
    s = state()
    assert s.jpeg() is None
    s.put_frame(frame_image)
    first = s.jpeg()
    assert first is not None and first[:2] == b"\xff\xd8"
    assert s.jpeg() is first
    s.set_sightings([Sighting(Box(10, 10, 200, 60), 0.9, "DL01AB1234")], 4.0)
    assert s.jpeg() is not first
    assert s.snapshot()["plates_in_view"] == ["DL01AB1234"]


def test_stale_boxes_are_not_drawn(frame_image: Image, monkeypatch: pytest.MonkeyPatch) -> None:
    s = state()
    s.set_sightings([Sighting(Box(10, 10, 200, 60), 0.9, "DL01AB1234")], 4.0)
    monkeypatch.setattr(live, "SIGHTING_TTL_SECONDS", -1.0)
    assert s.snapshot()["plates_in_view"] == []


def test_render_draws_boxes_and_shrinks_wide_frames() -> None:
    wide = np.full((1080, 1920, 3), 90, dtype=np.uint8)
    data = render(
        wide,
        [
            Sighting(Box(100, 300, 900, 500), 0.9, "DL01AB1234"),
            Sighting(Box(0, 0, 50, 20), 0.5, None),
        ],
    )
    image = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    assert image is not None
    assert image.shape[1] == live.PREVIEW_MAX_WIDTH
    assert image[200, 60].tolist() != [90, 90, 90]  # the green box edge is drawn


# --- threads ----------------------------------------------------------------------------


class FakeCapture:
    def __init__(self, frames: int, *, fps: float = 0.0) -> None:
        self.left = frames
        self.fps = fps
        self.released = False

    def get(self, prop: int) -> float:
        return self.fps

    def read(self) -> tuple[bool, Image | None]:
        if self.left <= 0:
            return False, None
        self.left -= 1
        return True, np.full((90, 160, 3), 100, dtype=np.uint8)

    def release(self) -> None:
        self.released = True


def test_a_video_plays_to_the_end_and_keeps_its_last_frame() -> None:
    s = state()
    capture = FakeCapture(3, fps=500)
    camera_loop(s, lambda: capture, live=False)
    assert s.frame_seq == 3
    assert s.source_ended
    assert capture.released


def test_a_missing_video_ends_the_source() -> None:
    s = state()

    def missing() -> FakeCapture:
        raise OSError("Could not open video source 'x.mp4'")

    camera_loop(s, missing, live=False)
    assert s.source_ended
    assert s.snapshot()["camera_error"] == "Could not open video source 'x.mp4'"


def test_a_webcam_that_drops_out_is_reopened(monkeypatch: pytest.MonkeyPatch) -> None:
    s = state()
    opened: list[FakeCapture] = []
    errors: list[str | None] = []
    real_set_error = s.set_camera_error

    def record_error(message: str | None) -> None:
        errors.append(message)
        real_set_error(message)
        if len(errors) >= 2:
            s.stopping.set()

    monkeypatch.setattr(s, "set_camera_error", record_error)

    def open_camera() -> FakeCapture:
        if len(opened) == 1:
            raise OSError("Could not open video source '0' (is another app using the camera?)")
        opened.append(FakeCapture(2))
        return opened[-1]

    monkeypatch.setattr(s.stopping, "wait", lambda timeout=None: s.stopping.is_set())
    camera_loop(s, open_camera, live=True)
    assert s.frame_seq == 2
    assert errors[0] == "The camera stopped sending pictures; retrying..."
    assert "another app" in str(errors[1])
    assert opened[0].released


def plate_pipeline(texts: list[str | None]) -> Pipeline:
    return Pipeline(
        FakeDetector([Box(10, 10, 120, 40)]),
        ScriptedOcr(texts),
        PlateTracker(min_agreeing_reads=2, gap_seconds=0.5),
    )


def test_analysis_sends_each_car_once_on_the_current_lane(frame_image: Image) -> None:
    s = state()
    sent: list[tuple[str, str]] = []
    lanes = {
        "entry": recorder(sent, "entry"),
        "exit": recorder(sent, "exit"),
    }
    pipeline = plate_pipeline(["DL01AB1234"] * 3 + ["HR26DK8337"] * 2 + [None] * 50)
    clock = iter(T0 + timedelta(seconds=i * 0.2) for i in range(10_000))
    thread = threading.Thread(
        target=analysis_loop,
        args=(s, pipeline, lanes),
        kwargs={"sample_fps": 200, "clock": lambda: next(clock)},
    )
    thread.start()
    try:
        for _ in range(3):
            s.put_frame(frame_image.copy())
            wait_until(lambda: s.analysed_fps >= 0 and s.latest_frame()[0] > 0)
            time.sleep(0.03)
        wait_until(lambda: sent == [("entry", "DL01AB1234")])
        s.request_mode("exit")
        for _ in range(3):
            s.put_frame(frame_image.copy())
            time.sleep(0.03)
        wait_until(lambda: ("exit", "HR26DK8337") in sent)
    finally:
        s.stopping.set()
        thread.join(timeout=5)
    titles = [d["mode"] for d in s.snapshot()["decisions"]]
    assert titles == ["exit", "entry"]


def test_analysis_survives_errors_and_retries_buffers(
    frame_image: Image, monkeypatch: pytest.MonkeyPatch
) -> None:
    s = state(("entry",))
    polls: list[int] = []

    class Broken:
        def detect(self, image: Image) -> list[Any]:
            raise RuntimeError("model crashed")

    def poll() -> None:
        polls.append(1)
        raise OSError("disk full")

    monkeypatch.setattr(live, "POLL_EVERY_SECONDS", 0.0)
    pipeline = Pipeline(Broken(), ScriptedOcr([]), PlateTracker())
    thread = threading.Thread(
        target=analysis_loop,
        args=(s, pipeline, {"entry": Lane(send=lambda r: "sent", poll=poll)}),
        kwargs={"sample_fps": 200},
    )
    thread.start()
    try:
        s.put_frame(frame_image)
        wait_until(lambda: len(polls) >= 2 and s.analysed_fps >= 0)
        assert thread.is_alive()
    finally:
        s.stopping.set()
        thread.join(timeout=5)


def test_a_failed_send_shows_as_an_error(frame_image: Image) -> None:
    s = state(("entry",))

    def explode(read: PlateRead) -> str:
        raise RuntimeError("boom")

    live.deliver(s, Lane(send=explode, poll=lambda: None), READ, "entry")
    assert s.snapshot()["decisions"][0]["title"] == "Something went wrong"


def test_the_end_of_a_video_sends_what_is_still_pending(frame_image: Image) -> None:
    s = state(("entry",))
    sent: list[str] = []
    pipeline = plate_pipeline(["DL01AB1234"])  # one read: below min_agreeing_reads
    thread = threading.Thread(
        target=analysis_loop,
        args=(
            s,
            pipeline,
            {"entry": recorder(sent)},
        ),
        kwargs={"sample_fps": 200},
    )
    thread.start()
    try:
        s.put_frame(frame_image)
        wait_until(lambda: s.analysed_fps >= 0 and pipeline.tracker.tracks)
        s.end_source()
        wait_until(lambda: sent == ["DL01AB1234"])
    finally:
        s.stopping.set()
        thread.join(timeout=5)


# --- the web page -----------------------------------------------------------------------


@pytest.fixture
def server(frame_image: Image) -> Iterator[PreviewServer]:
    s = state()
    srv = PreviewServer(("127.0.0.1", 0), s)
    thread = threading.Thread(target=srv.serve_forever, kwargs={"poll_interval": 0.05})
    thread.start()
    yield srv
    s.stopping.set()
    with s.new_frame:
        s.new_frame.notify_all()
    srv.shutdown()
    srv.server_close()
    thread.join(timeout=5)


def call(
    srv: PreviewServer,
    method: str,
    path: str,
    *,
    body: object | None = None,
    headers: dict[str, str] | None = None,
) -> tuple[int, dict[str, str], bytes]:
    host, port = srv._host_port()
    connection = http.client.HTTPConnection(host, port, timeout=5)
    data = json.dumps(body).encode() if body is not None else None
    connection.request(method, path, body=data, headers=headers or {})
    response = connection.getresponse()
    result = response.status, dict(response.getheaders()), response.read()
    connection.close()
    return result


BUTTON = {live.BUTTON_HEADER: "1", "Content-Type": "application/json"}


def test_page_and_state(server: PreviewServer) -> None:
    status, headers, page = call(server, "GET", "/")
    assert status == 200
    assert b"Gate camera" in page
    assert "frame-ancestors 'none'" in headers["Content-Security-Policy"]

    status, _, body = call(server, "GET", "/state?t=1")
    snapshot = json.loads(body)
    assert status == 200
    assert snapshot["modes"] == ["entry", "exit"]
    assert snapshot["console_url"] == "http://localhost:5173"
    assert server.url.startswith("http://127.0.0.1:")


def test_frame_before_and_after_the_camera_starts(
    server: PreviewServer, frame_image: Image
) -> None:
    assert call(server, "GET", "/frame.jpg")[0] == 503
    server.state.put_frame(frame_image)
    status, headers, data = call(server, "GET", "/frame.jpg")
    assert status == 200
    assert headers["Content-Type"] == "image/jpeg"
    assert data[:2] == b"\xff\xd8"


def test_buttons_need_the_preview_header(server: PreviewServer) -> None:
    assert call(server, "POST", "/mode", body={"mode": "exit"})[0] == 403
    status, _, body = call(server, "POST", "/mode", body={"mode": "exit"}, headers=BUTTON)
    assert status == 200 and json.loads(body)["mode"] == "exit"
    assert call(server, "POST", "/mode", body={"mode": "sideways"}, headers=BUTTON)[0] == 400
    assert call(server, "POST", "/rescan", headers=BUTTON)[0] == 200
    assert server.state.take_reset()
    assert call(server, "POST", "/nope", headers=BUTTON)[0] == 404
    assert call(server, "GET", "/nope")[0] == 404


def test_other_host_names_are_refused(server: PreviewServer) -> None:
    """A page on another site can't read the preview through a DNS rebinding trick."""
    assert call(server, "GET", "/state", headers={"Host": "evil.example"})[0] == 421
    assert call(server, "POST", "/rescan", headers={**BUTTON, "Host": "evil.example"})[0] == 421


def test_the_stream_sends_jpeg_parts(server: PreviewServer, frame_image: Image) -> None:
    server.state.put_frame(frame_image)
    host, port = server._host_port()
    connection = http.client.HTTPConnection(host, port, timeout=5)
    connection.request("GET", "/stream.mjpg")
    response = connection.getresponse()
    assert response.getheader("Content-Type") == "multipart/x-mixed-replace; boundary=frame"
    chunk = response.read(64)
    assert chunk.startswith(b"--frame\r\nContent-Type: image/jpeg")
    connection.close()


# --- start to finish --------------------------------------------------------------------


def test_run_preview_until_stopped(frame_image: Image) -> None:
    s = state(("entry",))
    sent: list[str] = []
    pipeline = plate_pipeline(["DL01AB1234"] * 2 + [None] * 500)
    thread = threading.Thread(
        target=run_preview,
        args=(s,),
        kwargs={
            "pipeline": pipeline,
            "lanes": {"entry": recorder(sent)},
            "open_capture": lambda: FakeCapture(400, fps=100),
            "live": False,
            "sample_fps": 50,
            "host": "127.0.0.1",
            "port": 0,
            "open_browser": False,
        },
    )
    thread.start()
    try:
        wait_until(lambda: sent == ["DL01AB1234"])
    finally:
        s.stopping.set()
        thread.join(timeout=10)
    assert not thread.is_alive()


# --- CLI wiring -------------------------------------------------------------------------


def test_preview_refuses_folders_and_missing_files(tmp_path: Path) -> None:
    with pytest.raises(SystemExit, match="not a folder"):
        cli.main(["--source", str(tmp_path), "--preview", "--dry-run"])
    with pytest.raises(SystemExit, match="No such video file"):
        cli.main(["--source", str(tmp_path / "gone.mp4"), "--preview", "--dry-run"])


def test_build_pipeline_needs_the_model(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("ANPR_DETECTOR_MODEL", str(tmp_path / "missing.onnx"))
    with pytest.raises(SystemExit, match="download_model"):
        cli.build_pipeline(AnprSettings())


def test_exit_lane_gets_its_own_buffer() -> None:
    assert cli.exit_buffer_path(Path("data/buffer.sqlite3")) == Path("data/buffer-exit.sqlite3")
    assert cli.exit_buffer_path(None) is None


def preview_args(*extra: str) -> list[str]:
    return ["--source", "0", "--preview", "--no-browser", *extra]


def test_preview_with_two_keys_sends_each_lane_with_its_own_key(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("ANPR_DEVICE_KEY", "gsd_entry")
    monkeypatch.setenv("ANPR_EXIT_DEVICE_KEY", "gsd_exit")
    used: list[tuple[str, str]] = []

    def fake_send(self: GateEventClient, read: PlateRead) -> dict[str, Any]:
        key = self.http.headers["X-Device-Key"]
        used.append((key, read.plate_text))
        if read.plate_text == "BADPLATE":
            raise GateEventRejectedError(422, "not a plate")
        return reply("resident", plate=read.plate_text)

    captured: dict[str, Any] = {}

    def fake_run(state: LiveState, **kwargs: Any) -> None:
        captured.update(kwargs, state=state)
        lanes = kwargs["lanes"]
        assert lanes["entry"].send(PlateRead("DL01AB1234", 0.9, T0)) == "sent"
        assert lanes["exit"].send(PlateRead("DL01AB1234", 0.9, T0 + timedelta(minutes=5))) == "sent"
        assert lanes["exit"].send(PlateRead("BADPLATE", 0.9, T0)) == "rejected"
        lanes["entry"].poll()

    monkeypatch.setattr(GateEventClient, "send", fake_send)
    monkeypatch.setattr(cli, "build_pipeline", lambda settings: "pipeline")
    monkeypatch.setattr(live, "run_preview", fake_run)

    assert cli.main(preview_args()) == 0

    assert used == [
        ("gsd_entry", "DL01AB1234"),
        ("gsd_exit", "DL01AB1234"),
        ("gsd_exit", "BADPLATE"),
    ]
    state: LiveState = captured["state"]
    assert state.modes == ("entry", "exit")
    titles = [(d["mode"], d["title"]) for d in state.snapshot()["decisions"]]
    assert titles == [
        ("exit", "The server refused this read"),
        ("exit", "Resident car: exit logged"),
        ("entry", "Resident car: entry logged"),
    ]
    assert captured["live"] is True
    assert captured["open_browser"] is False
    assert (tmp_path / "buffer-exit.sqlite3").exists()


def test_preview_without_an_exit_key_is_entry_only(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setenv("ANPR_DEVICE_KEY", "gsd_entry")
    monkeypatch.delenv("ANPR_EXIT_DEVICE_KEY", raising=False)
    monkeypatch.setenv("ANPR_BUFFER_PATH", "")
    captured: dict[str, Any] = {}

    def fake_send(self: GateEventClient, read: PlateRead) -> dict[str, Any]:
        raise GateEventRejectedError(401, "Invalid or inactive device API key")

    def fake_run(state: LiveState, **kwargs: Any) -> None:
        captured.update(kwargs, state=state)
        assert kwargs["lanes"]["entry"].send(READ) == "rejected"

    monkeypatch.setattr(GateEventClient, "send", fake_send)
    monkeypatch.setattr(cli, "build_pipeline", lambda settings: "pipeline")
    monkeypatch.setattr(live, "run_preview", fake_run)
    monkeypatch.chdir(Path(__file__).parent)  # no anpr/.env with an exit key

    with caplog.at_level("INFO"):
        assert cli.main(preview_args()) == 0
    assert "entry camera only" in caplog.text
    assert captured["state"].modes == ("entry",)
    assert captured["state"].snapshot()["decisions"][0]["rejected_status"] == 401


def test_preview_dry_run_uses_one_printer_for_both_lanes(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def fake_run(state: LiveState, **kwargs: Any) -> None:
        assert kwargs["lanes"]["exit"].send(READ) == "printed"

    monkeypatch.setattr(cli, "build_pipeline", lambda settings: "pipeline")
    monkeypatch.setattr(live, "run_preview", fake_run)
    assert cli.main(preview_args("--dry-run")) == 0
    assert "KAOSMN4821" in capsys.readouterr().out


def test_an_empty_buffer_path_turns_the_buffer_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANPR_BUFFER_PATH", "")
    assert AnprSettings().buffer_path is None
