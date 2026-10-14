"""Out-of-band database helpers for the stac-api test suite."""

import os
import warnings

import psycopg


def admin_credentials_available() -> bool:
    """Whether out-of-band cleanup can run."""
    return bool(os.getenv("PGSTAC_ADMIN_USER") and os.getenv("PGSTAC_ADMIN_PASS"))


def admin_delete_collection(collection_id: str) -> None:
    """Remove a test collection as the pgstac admin.

    The app role holds only DML grants, and pgstac's collection delete trigger
    drops a partition table, which requires ownership -- so the API's DELETE
    returns InsufficientPrivilegeError. Tests clean up out-of-band instead.
    """
    if not admin_credentials_available():
        warnings.warn(
            f"PGSTAC admin credentials unset; leaking test collection "
            f"{collection_id!r}. Clean up manually or restore cleanup.",
            stacklevel=2,
        )
        return

    with psycopg.connect(
        host=os.getenv("PGHOST", "database"),
        port=os.getenv("PGPORT", "5432"),
        dbname=os.getenv("PGDATABASE", "agri_sdss"),
        user=os.getenv("PGSTAC_ADMIN_USER"),
        password=os.getenv("PGSTAC_ADMIN_PASS"),
        connect_timeout=10,
    ) as conn:
        conn.execute(
            "DELETE FROM pgstac.items WHERE collection = %s", (collection_id,)
        )
        conn.execute(
            "DELETE FROM pgstac.collections WHERE id = %s", (collection_id,)
        )
