"""The laptop webcam setup command (python -m app.webcam_devices)."""

import argparse
from collections.abc import Callable, Coroutine
from pathlib import Path
from typing import Any

import httpx2
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import webcam_devices
from app.models import AuditLog, Device, Society
from app.models.enums import LaneDirection
from app.webcam_devices import (
    DEVICE_NAMES,
    SetupError,
    WebcamSetup,
    format_plate,
    plates_page,
    setup_webcam,
    write_env,
)
from tests import factories
from tests.api.test_gate_events import ago, post_read


@pytest.fixture
async def demo(db: AsyncSession, society: Society) -> Society:
    await factories.make_gate(db, society)
    await factories.make_gate(db, society, "Service Gate")
    theirs = await factories.make_flat(db, society, "B", "402")
    other = await factories.make_flat(db, society, "A", "101")
    await factories.make_vehicle(db, society, other, "DL01AB1234")
    await factories.make_vehicle(db, society, theirs, "UP16BK2834")
    await factories.make_watchlist_entry(db, society, "HR26DK8337")
    return society


async def test_creates_two_lanes_whose_keys_work(
    db: AsyncSession, demo: Society, client: httpx2.AsyncClient
) -> None:
    result = await setup_webcam(db)

    devices = (await db.scalars(select(Device).order_by(Device.name))).all()
    assert [(d.name, d.direction) for d in devices] == [
        ("Laptop webcam - entry", LaneDirection.ENTRY),
        ("Laptop webcam - exit", LaneDirection.EXIT),
    ]
    assert result.created == list(DEVICE_NAMES.values())

    entry = await post_read(client, result.keys[LaneDirection.ENTRY], "UP16BK2834", at=ago(10))
    assert entry.status_code == 201, entry.text
    assert entry.json()["event"]["match_result"] == "resident"
    assert entry.json()["event"]["direction"] == "entry"
    leave = await post_read(client, result.keys[LaneDirection.EXIT], "UP16BK2834", at=ago(1))
    assert leave.json()["event"]["direction"] == "exit"


async def test_running_again_rotates_the_keys(
    db: AsyncSession, demo: Society, client: httpx2.AsyncClient
) -> None:
    first = await setup_webcam(db)
    second = await setup_webcam(db)

    assert second.created == []
    assert await db.scalar(select(func.count()).select_from(Device)) == 2
    assert second.keys[LaneDirection.ENTRY] != first.keys[LaneDirection.ENTRY]
    old = await post_read(client, first.keys[LaneDirection.ENTRY], "UP16BK2834")
    assert old.status_code == 401
    actions = (await db.scalars(select(AuditLog.action).order_by(AuditLog.created_at))).all()
    assert sorted(actions) == ["device.create"] * 2 + ["device.rotate_key"] * 2


async def test_brings_back_a_switched_off_device(db: AsyncSession, demo: Society) -> None:
    await setup_webcam(db)
    device = await db.scalar(select(Device).where(Device.name == "Laptop webcam - exit"))
    assert device is not None
    device.is_active = False
    await db.commit()

    await setup_webcam(db)
    await db.refresh(device)
    assert device.is_active


async def test_demo_plates_start_with_the_demo_residents_car(
    db: AsyncSession, demo: Society
) -> None:
    result = await setup_webcam(db)

    assert [p.plate for p in result.plates] == [
        "UP16BK2834",  # flat B-402: the demo resident's own car first
        "DL01AB1234",
        "HR26DK8337",
        "KA05MN4821",  # a valid plate nobody has
    ]
    assert result.plates[0].what == "Resident car, flat B-402"
    assert result.demo_flat == "B-402"


async def test_unknown_gate_lists_the_gates(db: AsyncSession, demo: Society) -> None:
    with pytest.raises(SetupError, match="Gates: Main Gate, Service Gate"):
        await setup_webcam(db, gate_name="Back Gate")


async def test_needs_a_seeded_database(db: AsyncSession) -> None:
    with pytest.raises(SetupError, match="app.seed"):
        await setup_webcam(db)


async def test_needs_a_choice_between_societies(db: AsyncSession, demo: Society) -> None:
    other = await factories.make_society(db, "Second Society")
    await factories.make_gate(db, other)
    with pytest.raises(SetupError, match="--society"):
        await setup_webcam(db)
    result = await setup_webcam(db, society_name="Second Society")
    assert result.gate == "Main Gate"


def test_write_env_keeps_other_lines(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text(
        "# my settings\nANPR_API_URL=http://127.0.0.1:8000\n"
        "# ANPR_DEVICE_KEY=commented-out\nANPR_DEVICE_KEY=old\n",
        encoding="utf-8",
    )
    write_env(env, {"ANPR_DEVICE_KEY": "new", "ANPR_EXIT_DEVICE_KEY": "exit"})

    assert env.read_text(encoding="utf-8") == (
        "# my settings\nANPR_API_URL=http://127.0.0.1:8000\n"
        "# ANPR_DEVICE_KEY=commented-out\nANPR_DEVICE_KEY=new\n\n"
        "# Laptop webcam devices (python -m app.webcam_devices)\nANPR_EXIT_DEVICE_KEY=exit\n"
    )


def test_write_env_creates_the_file(tmp_path: Path) -> None:
    env = tmp_path / "anpr" / ".env"
    write_env(env, {"ANPR_DEVICE_KEY": "k"})
    assert env.read_text(encoding="utf-8").endswith("ANPR_DEVICE_KEY=k\n")


@pytest.mark.parametrize(
    ("plate", "shown"),
    [
        ("UP16BK2834", "UP16 BK 2834"),
        ("DL8CAF0921", "DL8 CAF 0921"),
        ("22BH3092JZ", "22 BH 3092 JZ"),
        ("KA051234", "KA05 1234"),
    ],
)
def test_format_plate(plate: str, shown: str) -> None:
    assert format_plate(plate) == shown


def test_plates_page_escapes_text() -> None:
    page = plates_page([webcam_devices.DemoPlate("UP16BK2834", "<b>flat</b>", "a & b")])
    assert "UP16 BK 2834" in page
    assert "&lt;b&gt;flat&lt;/b&gt;" in page
    assert "a &amp; b" in page


def _fake_main(
    result: WebcamSetup | SetupError,
) -> Callable[[argparse.Namespace], Coroutine[Any, Any, WebcamSetup]]:
    async def fake(args: argparse.Namespace) -> WebcamSetup:
        if isinstance(result, SetupError):
            raise result
        return result

    return fake


def test_main_writes_the_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    result = WebcamSetup(
        gate="Main Gate",
        keys={LaneDirection.ENTRY: "gsd_entry", LaneDirection.EXIT: "gsd_exit"},
        plates=[webcam_devices.DemoPlate("UP16BK2834", "Resident car, flat B-402", "Green.")],
        demo_flat="B-402",
    )
    monkeypatch.setattr(webcam_devices, "_main", _fake_main(result))
    env, page = tmp_path / ".env", tmp_path / "data" / "plates.html"

    code = webcam_devices.main(["--env-file", str(env), "--plates-page", str(page)])

    assert code == 0
    assert "ANPR_DEVICE_KEY=gsd_entry" in env.read_text(encoding="utf-8")
    assert "ANPR_EXIT_DEVICE_KEY=gsd_exit" in env.read_text(encoding="utf-8")
    assert "UP16 BK 2834" in page.read_text(encoding="utf-8")
    out = capsys.readouterr().out
    assert "UP16 BK 2834" in out
    assert "gsd_entry" not in out  # keys go to the file, not the terminal
    assert "flat B-402" in out


def test_main_print_only_writes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    result = WebcamSetup(gate="Main Gate", keys={LaneDirection.ENTRY: "gsd_entry"})
    monkeypatch.setattr(webcam_devices, "_main", _fake_main(result))
    env = tmp_path / ".env"

    assert webcam_devices.main(["--print-only", "--env-file", str(env)]) == 0
    assert not env.exists()
    assert "ANPR_DEVICE_KEY=gsd_entry" in capsys.readouterr().out


def test_main_reports_a_setup_error(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(webcam_devices, "_main", _fake_main(SetupError("No society found.")))
    assert webcam_devices.main(["--print-only"]) == 1
    assert "Not set up: No society found." in capsys.readouterr().out
