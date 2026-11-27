"""DDL for the process jobs table, owned by process-api.

``ensure_schema()`` is idempotent and serialised with an advisory lock, so
process-api and every worker replica can call it at boot. A later column is
added here with ``ALTER TABLE … ADD COLUMN IF NOT EXISTS``, never by a
hand-run migration. At every start the connecting role needs ``CREATE`` on
the table's schema and must own the table; owning the schema and letting
process-api create the table gives both. PostgreSQL checks both before it
sees that the table or index already exists.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import psycopg
from psycopg import sql
from pygeoapi.util import yaml_load

from ..config import DatabaseConfig, JobQueueConfig

LOCK_CLASS_ID: int = 349_001
SCHEMA_LOCK_ID: int = 0

CREATE_TABLE: str = """
CREATE TABLE IF NOT EXISTS {table} (
    identifier text PRIMARY KEY,
    type text NOT NULL DEFAULT 'process',
    process_id text NOT NULL,
    status text NOT NULL,
    message text,
    progress integer NOT NULL DEFAULT 0,
    created timestamptz NOT NULL DEFAULT now(),
    started timestamptz,
    updated timestamptz NOT NULL DEFAULT now(),
    finished timestamptz,
    mimetype text,
    location text,
    execution_mode text NOT NULL CHECK (execution_mode IN ('sync', 'async')),
    inputs jsonb,
    requested_outputs jsonb,
    requested_response text,
    locale text,
    result jsonb,
    worker text
)
"""

CREATE_ACCEPTED_INDEX: str = """
CREATE INDEX IF NOT EXISTS {index} ON {table} (created)
WHERE status = 'accepted'
"""

CREATE_FINISHED_INDEX: str = """
CREATE INDEX IF NOT EXISTS {index} ON {table} (finished)
WHERE finished IS NOT NULL
"""


def manager_table(manager_def: dict[str, Any] | None) -> str:
    """The jobs table of a pygeoapi manager definition.

    Its ``connection.table`` when the config sets one, else PROCESS_JOBS_TABLE,
    so a deployment can move the table without rebuilding the baked config.
    """
    connection = (manager_def or {}).get("connection") or {}
    return connection.get("table") or JobQueueConfig().PROCESS_JOBS_TABLE


def jobs_table(config: dict[str, Any]) -> str:
    """The jobs table of a whole pygeoapi config."""
    return manager_table(config.get("server", {}).get("manager"))


def split_table(table: str) -> tuple[str, str]:
    """Return ``(schema, name)`` for ``schema.name`` or a bare ``name``."""
    schema, _, name = table.rpartition(".")
    return schema or "public", name


def table_identifier(table: str) -> sql.Identifier:
    """Quoted, schema-qualified identifier for the jobs table."""
    return sql.Identifier(*split_table(table))


def ensure_schema(table: str, conn_params: dict[str, Any] | None = None) -> None:
    """Create the jobs table and its indexes when they do not exist."""
    params = conn_params or DatabaseConfig().to_conn_params()
    _, name = split_table(table)
    ident = table_identifier(table)
    with psycopg.connect(**params) as conn:
        conn.execute(
            "SELECT pg_advisory_xact_lock(%s, %s)", (LOCK_CLASS_ID, SCHEMA_LOCK_ID)
        )
        conn.execute(sql.SQL(CREATE_TABLE).format(table=ident))
        conn.execute(
            sql.SQL(CREATE_ACCEPTED_INDEX).format(
                index=sql.Identifier(f"{name}_accepted_idx"), table=ident
            )
        )
        conn.execute(
            sql.SQL(CREATE_FINISHED_INDEX).format(
                index=sql.Identifier(f"{name}_finished_idx"), table=ident
            )
        )


def main() -> None:
    """Ensure the jobs table of the pygeoapi config at PYGEOAPI_CONFIG."""
    with Path(os.environ["PYGEOAPI_CONFIG"]).open() as fh:
        config = yaml_load(fh)
    ensure_schema(jobs_table(config))


if __name__ == "__main__":
    main()
