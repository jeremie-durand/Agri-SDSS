"""Helpers for tests that hold a DuckDB call while another request runs."""

import threading
from collections.abc import Callable
from typing import Any

import anyio

RELEASE_TIMEOUT_S: float = 5.0


class Blocker:
    """Wraps manager calls so the first one blocks until the test releases it."""

    def __init__(self) -> None:
        self.entered = threading.Event()
        self.release = threading.Event()
        self.timed_out: list[bool] = []
        self._calls = 0
        self._lock = threading.Lock()

    def wrap(self, func: Callable[..., Any]) -> Callable[..., Any]:
        def blocked(*args: Any, **kwargs: Any) -> Any:
            with self._lock:
                self._calls += 1
                first = self._calls == 1
            if first:
                self.entered.set()
                self.timed_out.append(not self.release.wait(RELEASE_TIMEOUT_S))
            return func(*args, **kwargs)

        return blocked

    async def wait_entered(self) -> None:
        assert await anyio.to_thread.run_sync(self.entered.wait, RELEASE_TIMEOUT_S)

    def wait_entered_sync(self, timeout: float = RELEASE_TIMEOUT_S) -> None:
        assert self.entered.wait(timeout)
