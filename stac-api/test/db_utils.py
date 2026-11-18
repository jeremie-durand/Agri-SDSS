"""Out-of-band database helpers for the stac-api test suite."""

import os
import warnings

import psycopg


def admin_credentials_available() -> bool:
    """Whether out-of-band cleanup can run."""
    return bool(os.getenv("PGSTAC_ADMIN_USER") and os.getenv("PGSTAC_ADMIN_PASS"))


def _connect(user: str | None, password: str | None) -> psycopg.Connection:
    return psycopg.connect(
        host=os.getenv("PGHOST", "database"),
        port=os.getenv("PGPORT", "5432"),
        dbname=os.getenv("PGDATABASE", "agri_sdss"),
        user=user,
        password=password,
        connect_timeout=10,
    )


def admin_connection() -> psycopg.Connection:
    """Connect as the pgstac admin; check admin_credentials_available() first."""
    return _connect(os.getenv("PGSTAC_ADMIN_USER"), os.getenv("PGSTAC_ADMIN_PASS"))


def app_connection() -> psycopg.Connection:
    """Connect as the application role the API runs as."""
    return _connect(os.getenv("PGUSER"), os.getenv("PGPASSWORD"))


def admin_delete_collection(collection_id: str) -> None:
    """Remove a test collection and its items as the pgstac admin.

    Deletes whatever the API did not, so a failed test or a broken DELETE
    route never leaks a collection into the catalog the stack serves.
    """
    if not admin_credentials_available():
        warnings.warn(
            f"PGSTAC admin credentials unset; leaking test collection "
            f"{collection_id!r}. Clean up manually or restore cleanup.",
            stacklevel=2,
        )
        return

    with admin_connection() as conn:
        conn.execute("DELETE FROM pgstac.items WHERE collection = %s", (collection_id,))
        conn.execute("DELETE FROM pgstac.collections WHERE id = %s", (collection_id,))
