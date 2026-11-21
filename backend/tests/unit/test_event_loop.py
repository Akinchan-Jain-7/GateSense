"""Windows compatibility: psycopg's async mode needs a selector event loop.

The bug these tests guard against only shows up on Windows (ProactorEventLoop), so
Windows is simulated by patching `sys.platform` and asyncio's Proactor class.
"""

import asyncio
import sys

import pytest

from app.core import event_loop
from app.core.event_loop import IncompatibleEventLoopError, check_running_loop


def test_windows_gets_a_selector_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "win32")
    assert event_loop.loop_factory() is asyncio.SelectorEventLoop


def test_other_systems_keep_the_default_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "linux")
    assert event_loop.loop_factory() is None


def test_run_uses_the_selector_loop_on_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "win32")

    async def loop_type() -> type[asyncio.AbstractEventLoop]:
        return type(asyncio.get_running_loop())

    assert issubclass(event_loop.run(loop_type()), asyncio.SelectorEventLoop)


def test_uvicorn_loop_factory_makes_a_selector_loop() -> None:
    loop = event_loop.selector_event_loop()
    try:
        assert isinstance(loop, asyncio.SelectorEventLoop)
    finally:
        loop.close()


async def test_api_refuses_to_start_on_a_proactor_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    running = asyncio.get_running_loop()
    # Pretend the running loop's class is Windows' ProactorEventLoop.
    monkeypatch.setattr(asyncio, "ProactorEventLoop", type(running), raising=False)
    with pytest.raises(IncompatibleEventLoopError, match="--reload"):
        check_running_loop()


async def test_api_starts_on_a_selector_loop() -> None:
    check_running_loop()  # no error


async def test_async_tests_run_on_a_selector_loop() -> None:
    """The conftest hook: tests use the same loop on Windows as on Linux CI."""
    assert isinstance(asyncio.get_running_loop(), asyncio.SelectorEventLoop)
