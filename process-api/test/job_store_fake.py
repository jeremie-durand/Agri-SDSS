"""A file-backed stand-in for ``JobStore`` in the worker tests.

The worker hands its store to a ``spawn`` child, so the fake keeps its jobs in
a JSON file both processes can read and write, and is picklable by its dotted
path.
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any


class FakeConnection:
    """The few connection calls the worker makes."""

    broken: bool = False

    def __enter__(self) -> FakeConnection:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def execute(self, query: str) -> None:
        return None

    def notifies(self, timeout: float, stop_after: int) -> Iterator[Any]:
        time.sleep(min(timeout, 0.05))
        return iter(())


class FileJobStore:
    """Jobs in a JSON file, with the store's terminal-write rule."""

    table: str = "public.fake_jobs"
    conn_params: dict[str, Any] = {}

    def __init__(self, path: Path) -> None:
        self.path = path
        self._write({"jobs": [], "released": []})

    def _read(self) -> dict[str, Any]:
        return json.loads(self.path.read_text())

    def _write(self, state: dict[str, Any]) -> None:
        staging = self.path.with_suffix(f".{os.getpid()}.tmp")
        staging.write_text(json.dumps(state))
        os.replace(staging, self.path)

    def add(self, identifier: str, process_id: str, **fields: Any) -> None:
        state = self._read()
        state["jobs"].append(
            {
                "identifier": identifier,
                "process_id": process_id,
                "status": "accepted",
                "message": None,
                "locale": "fr",
                "inputs": {},
                "requested_outputs": None,
                "requested_response": "raw",
                "result": None,
                "mimetype": None,
                "worker": None,
                **fields,
            }
        )
        self._write(state)

    def get(self, identifier: str) -> dict[str, Any]:
        return next(j for j in self._read()["jobs"] if j["identifier"] == identifier)

    def released(self) -> list[str]:
        return self._read()["released"]

    def connect(self, autocommit: bool = False) -> FakeConnection:
        return FakeConnection()

    def listen(self, conn: FakeConnection) -> None:
        return None

    def claim(self, conn: FakeConnection, worker: str) -> dict[str, Any] | None:
        state = self._read()
        job = next((j for j in state["jobs"] if j["status"] == "accepted"), None)
        if job is None:
            return None
        job.update(status="running", worker=worker)
        self._write(state)
        return dict(job)

    def finish(
        self,
        identifier: str,
        status: str,
        message: str,
        result: Any = None,
        mimetype: str | None = None,
    ) -> bool:
        state = self._read()
        job = next(j for j in state["jobs"] if j["identifier"] == identifier)
        if job["status"] != "running":
            return False
        job.update(status=status, message=message, result=result, mimetype=mimetype)
        self._write(state)
        return True

    def release(self, conn: FakeConnection, identifier: str) -> None:
        state = self._read()
        state["released"].append(identifier)
        self._write(state)

    def sweep(self, message_for: Callable[[str | None], str]) -> list[str]:
        return []

    def purge(self, retention_days: int) -> int:
        return 0
