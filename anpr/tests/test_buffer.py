"""Offline mode: reads survive an outage and reach the server in the order they happened."""

from datetime import timedelta
from pathlib import Path

import httpx
import pytest

from gatesense_anpr import cli
from gatesense_anpr.buffer import BufferedSender, OfflineBuffer
from gatesense_anpr.client import GateEventClient
from gatesense_anpr.models import PlateRead
from tests.conftest import T0


def read(plate: str, seconds: int) -> PlateRead:
    return PlateRead(
        plate_text=plate,
        confidence=0.9,
        captured_at=T0 + timedelta(seconds=seconds),
        snapshot_jpeg=b"\xff\xd8\xff" + plate.encode(),
        votes=3,
        raw_texts=(plate, plate),
    )


class FakeApi:
    """Stands in for the API: can go offline, and stores each read once (like the server)."""

    def __init__(self) -> None:
        self.online = True
        self.reject: set[str] = set()
        self.stored: list[str] = []
        self.keys: set[tuple[str, str]] = set()
        self.calls = 0

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.calls += 1
        if not self.online:
            raise httpx.ConnectError("gate router is rebooting")
        body = request.content.decode(errors="replace")
        plate = body.split('name="plate_text"\r\n\r\n')[1].split("\r\n")[0]
        captured = body.split('name="captured_at"\r\n\r\n')[1].split("\r\n")[0]
        if plate in self.reject:
            return httpx.Response(422, json={"detail": "plate_text: not a plate"})
        if (plate, captured) in self.keys:
            return httpx.Response(200, json={"status": "duplicate", "event": {}})
        self.keys.add((plate, captured))
        self.stored.append(plate)
        return httpx.Response(201, json={"status": "created", "event": {}})


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def api() -> FakeApi:
    return FakeApi()


def sender_for(api: FakeApi, path: Path, clock: Clock | None = None) -> BufferedSender:
    client = GateEventClient(
        "http://api.test",
        "gsd_key",
        transport=httpx.MockTransport(api.handler),
        max_retries=1,
        sleep=lambda _: None,
    )
    return BufferedSender(client, OfflineBuffer(path), clock=clock or Clock())


def test_reads_go_straight_through_when_online(api: FakeApi, tmp_path: Path) -> None:
    sender = sender_for(api, tmp_path / "b.sqlite3")
    assert sender.send(read("DL01AB1234", 0)) == "sent"
    assert api.stored == ["DL01AB1234"]
    assert len(sender.buffer) == 0


def test_an_outage_is_buffered_and_replayed_in_capture_order(api: FakeApi, tmp_path: Path) -> None:
    clock = Clock()
    sender = sender_for(api, tmp_path / "b.sqlite3", clock)
    sender.send(read("UP16AB0001", 0))
    api.online = False
    for i, plate in enumerate(["UP16AB0002", "UP16AB0003", "UP16AB0004"], start=1):
        assert sender.send(read(plate, i)) == "buffered"
    assert len(sender.buffer) == 3

    api.online = True
    sender.send(read("UP16AB0005", 10))  # still waiting before the next attempt: queues
    assert api.stored == ["UP16AB0001"]
    clock.now += 60
    result = sender.flush()

    assert result.sent == 4 and result.remaining == 0
    assert api.stored == ["UP16AB0001", "UP16AB0002", "UP16AB0003", "UP16AB0004", "UP16AB0005"]


def test_waits_longer_after_each_failed_attempt(api: FakeApi, tmp_path: Path) -> None:
    clock = Clock()
    sender = sender_for(api, tmp_path / "b.sqlite3", clock)
    api.online = False
    sender.send(read("UP16AB0001", 0))  # fails: next attempt in 5 s
    calls = api.calls
    assert sender.flush().skipped
    assert api.calls == calls  # didn't hit the network while waiting
    clock.now += 5
    assert sender.flush().remaining == 1  # fails again: next in 10 s
    clock.now += 6
    assert sender.flush().skipped
    clock.now += 5
    api.online = True
    assert sender.flush().sent == 1


def test_the_buffer_survives_a_restart(api: FakeApi, tmp_path: Path) -> None:
    path = tmp_path / "b.sqlite3"
    api.online = False
    first = sender_for(api, path)
    first.send(read("KA05MN0042", 0))
    first.send(read("KA05MN0043", 1))
    first.buffer.close()  # power cut

    api.online = True
    second = sender_for(api, path)
    pending = second.buffer.oldest()
    assert [r.plate_text for _, r in pending] == ["KA05MN0042", "KA05MN0043"]
    assert pending[0][1].snapshot_jpeg == b"\xff\xd8\xffKA05MN0042"
    assert pending[0][1].raw_texts == ("KA05MN0042", "KA05MN0042")
    assert pending[0][1].captured_at == T0
    assert second.flush(force=True).sent == 2
    assert api.stored == ["KA05MN0042", "KA05MN0043"]


def test_a_reply_lost_on_the_way_back_is_not_stored_twice(api: FakeApi, tmp_path: Path) -> None:
    sender = sender_for(api, tmp_path / "b.sqlite3")
    lost = read("MH12DE1433", 0)
    request = httpx.Request(
        "POST",
        "http://api.test/api/v1/gate-events",
        files={"snapshot": ("s.jpg", b"x")},
        data={"plate_text": lost.plate_text, "captured_at": lost.captured_at.isoformat()},
    )
    request.read()
    api.handler(request)  # the server got it once already...
    sender.buffer.push(lost)  # ...but the camera never saw the reply
    assert sender.flush(force=True).sent == 1
    assert api.stored == ["MH12DE1433"]


def test_a_rejected_read_is_set_aside_and_does_not_block_the_rest(
    api: FakeApi, tmp_path: Path
) -> None:
    sender = sender_for(api, tmp_path / "b.sqlite3")
    api.online = False
    sender.send(read("UP16AB0001", 0))
    sender.send(read("XX00ZZ0000", 1))
    sender.send(read("UP16AB0003", 2))
    api.online = True
    api.reject.add("XX00ZZ0000")

    result = sender.flush(force=True)

    assert (result.sent, result.rejected, result.remaining) == (2, 1, 0)
    assert api.stored == ["UP16AB0001", "UP16AB0003"]
    assert sender.buffer.rejected_count() == 1


def test_server_errors_count_as_offline(tmp_path: Path) -> None:
    replies = iter([httpx.Response(503), httpx.Response(503)])
    client = GateEventClient(
        "http://api.test",
        "k",
        transport=httpx.MockTransport(lambda _: next(replies)),
        max_retries=1,
        sleep=lambda _: None,
    )
    sender = BufferedSender(client, OfflineBuffer(tmp_path / "b.sqlite3"))
    assert sender.send(read("UP16AB0001", 0)) == "buffered"


def test_cli_buffers_while_offline_and_sends_on_the_next_run(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, api: FakeApi
) -> None:
    monkeypatch.setenv("ANPR_DEVICE_KEY", "gsd_test")
    monkeypatch.setenv("ANPR_MAX_RETRIES", "0")
    real_init = GateEventClient.__init__

    def init(self: GateEventClient, *args: object, **kwargs: object) -> None:
        kwargs["transport"] = httpx.MockTransport(api.handler)
        real_init(self, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(GateEventClient, "__init__", init)
    api.online = False
    assert cli.main(["--simulate", "3", "--seed", "4"]) == 0
    assert api.stored == []
    assert len(OfflineBuffer(tmp_path / "buffer.sqlite3")) == 3

    api.online = True
    assert cli.main(["--simulate", "1", "--seed", "5"]) == 0
    assert len(api.stored) == 4  # the three from the outage first, then the new one
    assert len(OfflineBuffer(tmp_path / "buffer.sqlite3")) == 0
