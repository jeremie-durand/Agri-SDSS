"""Async job worker: ``python -m processes.worker``.

The parent process claims one accepted job at a time from the jobs table and
holds the job's advisory lock (see ``jobs/store.py``) while a ``spawn`` child
runs the processor. The child writes the terminal status itself; the parent
fails the job when the child crashes, exceeds the time budget or is stopped by
SIGTERM, then releases the lock. ``spawn`` rather than ``fork``, because the
parent's open database socket must not be shared with the child.
"""

from __future__ import annotations

import json
import logging
import multiprocessing
import os
import signal
import socket
import sys
import time
from multiprocessing.context import SpawnContext, SpawnProcess
from pathlib import Path
from types import FrameType
from typing import Any

import psycopg
from pygeoapi.plugin import load_plugin
from pygeoapi.util import json_serial, yaml_load

from agri_i18n import _, use_locale

from .config import (
    ApiConfig,
    DatabaseConfig,
    FarmConfig,
    JobQueueConfig,
    SpatialTablesConfig,
    StorageConfig,
)
from .jobs.manager import JSON_MIMETYPE, failure_outputs, wrap_outputs
from .jobs.schema import ensure_schema, jobs_table
from .jobs.store import JobStore

logger = logging.getLogger(__name__)

HEARTBEAT_FILE: Path = Path("/tmp/process-worker.heartbeat")
JOIN_SLICE_SECONDS: float = 5.0
KILL_GRACE_SECONDS: float = 5.0
LOG_FORMAT: str = "%(asctime)s %(levelname)s %(name)s: %(message)s"


def stopped_message(locale: str | None) -> str:
    """Job message for a job whose run ended without a result."""
    with use_locale(locale):
        return _("The job stopped before it finished.")


def timeout_message(locale: str | None, seconds: int) -> str:
    """Job message for a job killed at the time budget."""
    with use_locale(locale):
        return _("The job exceeded its time budget of {seconds} seconds.").format(
            seconds=seconds
        )


def non_json_message(locale: str | None) -> str:
    """Job message for a result that cannot be stored as JSON."""
    with use_locale(locale):
        return _("The process returned a result that cannot be stored as JSON.")


def stored_result(outputs: Any, requested_response: str | None) -> Any:
    """The result as the sync answer serialises it, ready for ``jsonb``.

    Raises ``TypeError`` or ``ValueError`` for raw bytes, NaN or infinity, or
    any value pygeoapi's serialiser rejects.
    """
    if isinstance(outputs, (bytes, bytearray)):
        raise TypeError("raw bytes output")
    result = wrap_outputs(outputs, requested_response)
    return json.loads(json.dumps(result, default=json_serial, allow_nan=False))


def run_job(
    store: JobStore, processes: dict[str, dict[str, Any]], job: dict[str, Any]
) -> None:
    """Child process entry: run one claimed job and write its terminal status."""
    logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)
    identifier = job["identifier"]
    with use_locale(job["locale"]):
        try:
            processor = load_plugin(
                "process", processes[job["process_id"]]["processor"]
            )
            processor.set_job_id(identifier)
            mimetype, outputs = processor.execute(
                job["inputs"], outputs=job["requested_outputs"]
            )
        except Exception as err:
            logger.exception("Job %s (%s) failed", identifier, job["process_id"])
            store.finish(identifier, "failed", failure_outputs(err)["description"])
            return
        try:
            result = stored_result(outputs, job["requested_response"])
        except (TypeError, ValueError):
            logger.error("Job %s returned a non-JSON %s result", identifier, mimetype)
            store.finish(identifier, "failed", non_json_message(job["locale"]))
            return
        store.finish(
            identifier, "successful", "Job complete", result, mimetype or JSON_MIMETYPE
        )


class Worker:
    """Claims and supervises async jobs, one at a time."""

    def __init__(
        self,
        store: JobStore,
        processes: dict[str, dict[str, Any]],
        config: JobQueueConfig,
        name: str,
        heartbeat: Path = HEARTBEAT_FILE,
        join_slice: float = JOIN_SLICE_SECONDS,
        kill_grace: float = KILL_GRACE_SECONDS,
    ) -> None:
        self.store = store
        self.processes = processes
        self.config = config
        self.name = name
        self.heartbeat = heartbeat
        self.join_slice = join_slice
        self.kill_grace = kill_grace
        self.stopping = False
        self._context: SpawnContext = multiprocessing.get_context("spawn")
        self._next_maintenance = 0.0

    def stop(self, signum: int | None = None, frame: FrameType | None = None) -> None:
        """Stop claiming and stop the running job; usable as a signal handler."""
        self.stopping = True

    def touch(self) -> None:
        self.heartbeat.touch()

    def maintain(self) -> None:
        """Fail jobs whose owner is gone and purge expired ones."""
        failed = self.store.sweep(stopped_message)
        purged = self.store.purge(self.config.PROCESS_JOB_RETENTION_DAYS)
        if failed:
            logger.warning("Failed %s orphaned job(s): %s", len(failed), failed)
        if purged:
            logger.info("Purged %s finished job(s)", purged)
        self._next_maintenance = (
            time.monotonic() + self.config.PROCESS_WORKER_SWEEP_SECONDS
        )

    def run_once(self, conn: psycopg.Connection) -> bool:
        """Claim and run one job on ``conn``'s session; ``False`` when idle."""
        job = self.store.claim(conn, self.name)
        if job is None:
            return False
        identifier = job["identifier"]
        logger.info("Claimed job %s (%s)", identifier, job["process_id"])
        try:
            self._supervise(conn, job)
        finally:
            if not conn.broken:
                self.store.release(conn, identifier)
        logger.info("Finished job %s", identifier)
        return True

    def _supervise(self, conn: psycopg.Connection, job: dict[str, Any]) -> None:
        child = self._context.Process(
            target=run_job,
            args=(self.store, self.processes, job),
            name=f"job-{job['identifier']}",
        )
        child.start()
        deadline = time.monotonic() + self.config.PROCESS_JOB_TIMEOUT_SECONDS
        while True:
            child.join(self.join_slice)
            self.touch()
            if not child.is_alive():
                break
            if self.stopping:
                logger.warning("Stopping job %s on shutdown", job["identifier"])
                self._end(child, job, stopped_message(job["locale"]))
                return
            if time.monotonic() >= deadline:
                seconds = self.config.PROCESS_JOB_TIMEOUT_SECONDS
                logger.warning(
                    "Job %s exceeded its %s s budget", job["identifier"], seconds
                )
                self._end(child, job, timeout_message(job["locale"], seconds))
                return
            try:
                conn.execute("SELECT 1")
            except psycopg.Error:
                logger.error("Lost the database session; stopping the running job")
                self._kill(child)
                raise
        if child.exitcode != 0:
            logger.error(
                "Job %s child exited with code %s", job["identifier"], child.exitcode
            )
        self.store.finish(job["identifier"], "failed", stopped_message(job["locale"]))

    def _end(self, child: SpawnProcess, job: dict[str, Any], message: str) -> None:
        self._kill(child)
        self.store.finish(job["identifier"], "failed", message)

    def _kill(self, child: SpawnProcess) -> None:
        child.terminate()
        child.join(self.kill_grace)
        if child.is_alive():
            child.kill()
            child.join()

    def serve(self) -> None:
        """Boot, then claim jobs until stopped."""
        ensure_schema(self.store.table, self.store.conn_params)
        self.maintain()
        with self.store.connect(autocommit=True) as conn:
            self.store.listen(conn)
            self.touch()
            logger.info("Worker %s ready on %s", self.name, self.store.table)
            while not self.stopping:
                ran = self.run_once(conn)
                if time.monotonic() >= self._next_maintenance:
                    self.maintain()
                if not ran and not self.stopping:
                    self.touch()
                    for _notify in conn.notifies(
                        timeout=self.config.PROCESS_WORKER_POLL_SECONDS, stop_after=1
                    ):
                        pass
        logger.info("Worker %s stopped", self.name)


def load_processes(config: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """The process resources of a pygeoapi config."""
    return {
        process_id: resource
        for process_id, resource in config["resources"].items()
        if resource.get("type") == "process"
    }


def main() -> int:
    logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)
    queue_config = JobQueueConfig()
    for settings in (ApiConfig, FarmConfig, SpatialTablesConfig, StorageConfig):
        settings()
    with Path(os.environ["PYGEOAPI_CONFIG"]).open() as fh:
        config = yaml_load(fh)
    store = JobStore(jobs_table(config), DatabaseConfig().to_conn_params())
    worker = Worker(
        store,
        load_processes(config),
        queue_config,
        f"{socket.gethostname()}-{os.getpid()}",
    )
    signal.signal(signal.SIGTERM, worker.stop)
    signal.signal(signal.SIGINT, worker.stop)
    worker.serve()
    return 0


if __name__ == "__main__":
    sys.exit(main())
