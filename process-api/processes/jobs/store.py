"""Every SQL statement on the process jobs table.

The table is both pygeoapi's job store and the async queue. Liveness rule:
whoever runs a job (the web request for sync, the worker parent for async)
holds a session advisory lock keyed on the job id, taken in the same
transaction that makes the row ``running``. A ``running`` row whose lock can
be taken has lost its owner, so the sweeper fails it.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import psycopg
from psycopg import sql
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from pygeoapi.util import DATETIME_FORMAT

from ..config import DatabaseConfig
from .schema import DEFAULT_TABLE, LOCK_CLASS_ID, split_table, table_identifier

TIMESTAMP_COLUMNS: tuple[str, ...] = ("created", "started", "updated", "finished")
FINISHED_STATUSES: tuple[str, ...] = ("successful", "failed", "dismissed")


@dataclass(frozen=True)
class NewJob:
    """A job about to be recorded."""

    identifier: str
    process_id: str
    locale: str
    inputs: dict[str, Any] | None = None
    requested_outputs: dict[str, Any] | None = None
    requested_response: str | None = None


def _format_timestamp(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(timezone.utc).strftime(DATETIME_FORMAT)


def _to_job(row: dict[str, Any]) -> dict[str, Any]:
    job = dict(row)
    for column in TIMESTAMP_COLUMNS:
        job[column] = _format_timestamp(job[column])
    return job


class JobStore:
    """SQL access to one jobs table, given as ``schema.name``."""

    def __init__(
        self, table: str = DEFAULT_TABLE, conn_params: dict[str, Any] | None = None
    ) -> None:
        self.table = table
        self._conn_params = conn_params
        self._ident = table_identifier(table)
        schema, name = split_table(table)
        self.channel = f"{schema}_{name}"

    @property
    def conn_params(self) -> dict[str, Any]:
        if self._conn_params is None:
            self._conn_params = DatabaseConfig().to_conn_params()
        return self._conn_params

    def connect(self, autocommit: bool = False) -> psycopg.Connection:
        """Open a connection returning rows as dicts."""
        return psycopg.connect(
            **self.conn_params, autocommit=autocommit, row_factory=dict_row
        )

    def _sql(self, query: str) -> sql.Composed:
        return sql.SQL(query).format(table=self._ident)

    def _lock(self, conn: psycopg.Connection, identifier: str) -> None:
        conn.execute(
            "SELECT pg_advisory_lock(hashtextextended(%s, %s))",
            (identifier, LOCK_CLASS_ID),
        )

    def release(self, conn: psycopg.Connection, identifier: str) -> None:
        """Release the job's advisory lock held by ``conn``'s session."""
        conn.execute(
            "SELECT pg_advisory_unlock(hashtextextended(%s, %s))",
            (identifier, LOCK_CLASS_ID),
        )
        conn.commit()

    def insert_running(self, conn: psycopg.Connection, job: NewJob) -> None:
        """Record a sync job as running, owned by ``conn``'s session."""
        self._lock(conn, job.identifier)
        conn.execute(
            self._sql(
                "INSERT INTO {table} (identifier, process_id, status, message, "
                "progress, started, execution_mode, locale) VALUES "
                "(%s, %s, 'running', 'Job running', 10, now(), 'sync', %s)"
            ),
            (job.identifier, job.process_id, job.locale),
        )
        conn.commit()

    def insert_accepted(self, job: NewJob) -> None:
        """Queue an async job and wake the workers."""
        with self.connect() as conn:
            conn.execute(
                self._sql(
                    "INSERT INTO {table} (identifier, process_id, status, message, "
                    "progress, execution_mode, inputs, requested_outputs, "
                    "requested_response, locale) VALUES "
                    "(%s, %s, 'accepted', 'Job accepted and ready for execution', "
                    "0, 'async', %s, %s, %s, %s)"
                ),
                (
                    job.identifier,
                    job.process_id,
                    Jsonb(job.inputs),
                    Jsonb(job.requested_outputs),
                    job.requested_response,
                    job.locale,
                ),
            )
            conn.execute("SELECT pg_notify(%s, %s)", (self.channel, job.identifier))

    def listen(self, conn: psycopg.Connection) -> None:
        """Subscribe ``conn`` to new-job notifications."""
        conn.execute(sql.SQL("LISTEN {}").format(sql.Identifier(self.channel)))
        conn.commit()

    def claim(self, conn: psycopg.Connection, worker: str) -> dict[str, Any] | None:
        """Take the oldest accepted async job, owned by ``conn``'s session."""
        row = conn.execute(
            self._sql(
                "UPDATE {table} SET status = 'running', message = 'Job running', "
                "progress = 10, started = now(), updated = now(), worker = %s "
                "WHERE identifier = (SELECT identifier FROM {table} "
                "WHERE status = 'accepted' AND execution_mode = 'async' "
                "ORDER BY created FOR UPDATE SKIP LOCKED LIMIT 1) RETURNING *"
            ),
            (worker,),
        ).fetchone()
        if row is not None:
            self._lock(conn, row["identifier"])
        conn.commit()
        return _to_job(row) if row is not None else None

    def finish(
        self,
        identifier: str,
        status: str,
        message: str,
        result: Any = None,
        mimetype: str | None = None,
        conn: psycopg.Connection | None = None,
    ) -> bool:
        """Write a terminal status if the job is still running."""
        query = self._sql(
            "UPDATE {table} SET status = %s, message = %s, result = %s, "
            "mimetype = %s, progress = 100, finished = now(), updated = now() "
            "WHERE identifier = %s AND status = 'running'"
        )
        params = (
            status,
            message,
            Jsonb(result) if result is not None else None,
            mimetype,
            identifier,
        )
        if conn is not None:
            updated = conn.execute(query, params).rowcount == 1
            conn.commit()
            return updated
        with self.connect() as own_conn:
            return own_conn.execute(query, params).rowcount == 1

    def sweep(self, message_for: Callable[[str | None], str]) -> list[str]:
        """Fail running jobs whose owner session is gone; return their ids."""
        failed: list[str] = []
        with self.connect() as conn:
            rows = conn.execute(
                self._sql(
                    "SELECT identifier, locale FROM {table} "
                    "WHERE status = 'running' FOR UPDATE SKIP LOCKED"
                )
            ).fetchall()
            for row in rows:
                orphaned = conn.execute(
                    "SELECT pg_try_advisory_xact_lock(hashtextextended(%s, %s)) AS free",
                    (row["identifier"], LOCK_CLASS_ID),
                ).fetchone()["free"]
                if not orphaned:
                    continue
                conn.execute(
                    self._sql(
                        "UPDATE {table} SET status = 'failed', message = %s, "
                        "progress = 100, finished = now(), updated = now() "
                        "WHERE identifier = %s"
                    ),
                    (message_for(row["locale"]), row["identifier"]),
                )
                failed.append(row["identifier"])
        return failed

    def purge(self, retention_days: int) -> int:
        """Delete jobs that finished more than ``retention_days`` ago."""
        with self.connect() as conn:
            return conn.execute(
                self._sql(
                    "DELETE FROM {table} WHERE status = ANY(%s) "
                    "AND finished < now() - make_interval(days => %s)"
                ),
                (list(FINISHED_STATUSES), retention_days),
            ).rowcount

    def page(
        self, limit: int | None, offset: int | None
    ) -> tuple[list[dict[str, Any]], int]:
        """Return a page of jobs, newest first, and the total count."""
        with self.connect() as conn:
            total = conn.execute(
                self._sql("SELECT count(*) AS n FROM {table}")
            ).fetchone()["n"]
            rows = conn.execute(
                self._sql(
                    "SELECT * FROM {table} ORDER BY created DESC, identifier "
                    "LIMIT %s OFFSET %s"
                ),
                (limit, offset or 0),
            ).fetchall()
        return [_to_job(row) for row in rows], total

    def get(self, identifier: str) -> dict[str, Any] | None:
        """Return one job, or ``None``."""
        with self.connect() as conn:
            row = conn.execute(
                self._sql("SELECT * FROM {table} WHERE identifier = %s"),
                (identifier,),
            ).fetchone()
        return _to_job(row) if row is not None else None

    def delete(self, identifier: str) -> bool:
        """Delete one job; ``True`` when it existed."""
        with self.connect() as conn:
            return (
                conn.execute(
                    self._sql("DELETE FROM {table} WHERE identifier = %s"),
                    (identifier,),
                ).rowcount
                == 1
            )
