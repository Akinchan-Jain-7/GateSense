"""Event loops that work with psycopg's async mode on every OS.

On Windows, Python's default event loop is the `ProactorEventLoop`, and psycopg's async
mode can't use it ("Psycopg cannot use the 'ProactorEventLoop'"). The older
`SelectorEventLoop` works everywhere, and it is already the default on Linux and macOS.

- Scripts (seed, …) start their loop with `run(...)` from this module.
- Tests get the same loop through the `pytest_asyncio_loop_factories` hook in conftest.py.
- uvicorn already uses a selector loop on Windows when started with `--reload` (the dev
  command). `check_running_loop()` stops the API with a clear message otherwise.
"""

import asyncio
import sys
from collections.abc import Callable, Coroutine
from typing import Any


def loop_factory() -> Callable[[], asyncio.AbstractEventLoop] | None:
    """The loop to use on this OS, or None for Python's default (fine off Windows)."""
    return asyncio.SelectorEventLoop if sys.platform == "win32" else None


def run[T](main: Coroutine[Any, Any, T]) -> T:
    """`asyncio.run`, with a loop psycopg can use on Windows too."""
    return asyncio.run(main, loop_factory=loop_factory())


def selector_event_loop() -> asyncio.AbstractEventLoop:
    """For uvicorn on Windows without --reload: `--loop app.core.event_loop:selector_event_loop`."""
    return asyncio.SelectorEventLoop()


class IncompatibleEventLoopError(RuntimeError):
    pass


def check_running_loop() -> None:
    """Fail at start-up, with the fix in the message, instead of on the first query."""
    if isinstance(asyncio.get_running_loop(), getattr(asyncio, "ProactorEventLoop", ())):
        raise IncompatibleEventLoopError(
            "The database driver can't run on Windows' ProactorEventLoop. Start the API with "
            "'uvicorn app.main:app --reload', or add "
            "'--loop app.core.event_loop:selector_event_loop'."
        )
