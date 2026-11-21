import json
import random
from datetime import timedelta
from pathlib import Path

import httpx
import pytest

from gatesense_anpr import cli, download_model
from gatesense_anpr.client import GateEventClient, GateEventRejectedError
from gatesense_anpr.models import PlateRead
from gatesense_anpr.simulate import add_ocr_noise, simulated_reads
from tests.conftest import T0

READ = PlateRead(
    plate_text="DL01AB1234", confidence=0.93, captured_at=T0, snapshot_jpeg=b"\xff\xd8\xffx"
)


def client_with(
    responses: list[httpx.Response | Exception],
) -> tuple[GateEventClient, list[httpx.Request], list[float]]:
    seen: list[httpx.Request] = []
    waits: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        reply = responses.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply

    client = GateEventClient(
        "http://api.test/", "gsd_key", transport=httpx.MockTransport(handler), sleep=waits.append
    )
    return client, seen, waits


def created() -> httpx.Response:
    return httpx.Response(201, json={"status": "created", "event": {"match_result": "resident"}})


def test_send_posts_multipart_with_the_device_key() -> None:
    client, seen, _ = client_with([created()])
    assert client.send(READ)["status"] == "created"
    request = seen[0]
    assert request.url == "http://api.test/api/v1/gate-events"
    assert request.headers["X-Device-Key"] == "gsd_key"
    body = request.content
    assert b'name="plate_text"' in body and b"DL01AB1234" in body
    assert b'name="captured_at"' in body and T0.isoformat().encode() in body
    assert b'filename="snapshot.jpg"' in body


def test_network_errors_and_5xx_are_retried_with_backoff() -> None:
    client, seen, waits = client_with(
        [httpx.ConnectError("down"), httpx.Response(503), httpx.Response(429), created()]
    )
    assert client.send(READ)["status"] == "created"
    assert len(seen) == 4
    assert waits == [0.5, 1.0, 2.0]


def test_client_errors_are_not_retried() -> None:
    client, seen, _ = client_with(
        [httpx.Response(422, json={"detail": "captured_at is in the future"})]
    )
    with pytest.raises(GateEventRejectedError, match="future") as error:
        client.send(READ)
    assert error.value.status_code == 422
    assert len(seen) == 1


def test_gives_up_after_max_retries() -> None:
    client, seen, _ = client_with([httpx.Response(503)] * 5)
    with pytest.raises(GateEventRejectedError):
        client.send(READ)
    assert len(seen) == 5
    client2, _, _ = client_with([httpx.ConnectError("down")] * 5)
    with pytest.raises(httpx.ConnectError):
        client2.send(READ)


def test_simulated_reads_are_realistic() -> None:
    reads = list(simulated_reads(40, seed=7, start=T0, interval_seconds=3))
    assert len(reads) == 40
    assert reads[1].captured_at - reads[0].captured_at == timedelta(seconds=3)
    assert all(0.45 <= r.confidence <= 0.99 for r in reads)
    assert any(r.confidence < 0.8 for r in reads)  # some go to the review queue
    assert all(r.snapshot_jpeg and r.snapshot_jpeg[:2] == b"\xff\xd8" for r in reads)


def test_ocr_noise_swaps_one_look_alike() -> None:
    rng = random.Random(1)  # noqa: S311 - test data
    noisy = {add_ocr_noise("DL01AB1234", rng, probability=1.0) for _ in range(30)}
    assert all(sum(a != b for a, b in zip(n, "DL01AB1234", strict=True)) == 1 for n in noisy)
    assert add_ocr_noise("DL01AB1234", rng, probability=0.0) == "DL01AB1234"


def test_cli_simulate_dry_run(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["--simulate", "3", "--dry-run", "--seed", "1", "--plates", "DL01AB1234"]) == 0
    lines = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert len(lines) == 3
    assert {"plate_text", "confidence", "captured_at", "snapshot_bytes"} <= lines[0].keys()


def test_cli_needs_a_device_key_to_send(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)  # no .env here
    monkeypatch.delenv("ANPR_DEVICE_KEY", raising=False)
    with pytest.raises(SystemExit, match="ANPR_DEVICE_KEY"):
        cli.main(["--simulate", "1"])


def test_cli_sends_simulated_reads(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    sent: list[PlateRead] = []

    def fake_send(self: GateEventClient, read: PlateRead) -> dict[str, object]:
        sent.append(read)
        return {
            "status": "created",
            "event": {"plate_normalized": read.plate_text, "match_result": "unknown"},
        }

    monkeypatch.setenv("ANPR_DEVICE_KEY", "gsd_test")
    monkeypatch.setattr(GateEventClient, "send", fake_send)
    assert cli.main(["--simulate", "2", "--seed", "3"]) == 0
    assert len(sent) == 2
    assert "created" in capsys.readouterr().out


def test_model_download_checks_the_hash(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    def fake_stream(method: str, url: str, **kwargs: object) -> object:
        class Response:
            def __enter__(self) -> "Response":
                return self

            def __exit__(self, *args: object) -> None:
                return None

            def raise_for_status(self) -> None:
                return None

            def iter_bytes(self) -> list[bytes]:
                return [b"onnx-bytes"]

        return Response()

    monkeypatch.setattr(httpx, "stream", fake_stream)
    target = tmp_path / "models" / "plate_detector.onnx"
    download_model.download("https://example.test/m.onnx", target)
    assert target.read_bytes() == b"onnx-bytes"
    good = download_model.sha256_of(target)
    with pytest.raises(ValueError, match="SHA-256"):
        download_model.download("https://example.test/m.onnx", target, expected_sha256="0" * 64)
    assert download_model.sha256_of(target) == good  # the old file is untouched
    assert download_model.release_url("models-v1").endswith(
        "/releases/download/models-v1/plate_detector.onnx"
    )
