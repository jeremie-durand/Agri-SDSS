"""Out-of-band database helpers for the stac-api test suite."""

import os
import warnings

import psycopg


def admin_delete_collection(collection_id: str) -> None:
    """Remove a test collection as the pgstac admin.

    The app role holds only DML grants, and pgstac's collection delete trigger
    drops a partition table, which requires ownership -- so the API's DELETE
    returns InsufficientPrivilegeError. Tests clean up out-of-band instead.
    """
    admin_user = os.getenv("PGSTAC_ADMIN_USER")
    admin_pass = os.getenv("PGSTAC_ADMIN_PASS")
    if not (admin_user and admin_pass):
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
        user=admin_user,
        password=admin_pass,
        connect_timeout=10,
    ) as conn:
        conn.execute(
            "DELETE FROM pgstac.items WHERE collection = %s", (collection_id,)
        )
        conn.execute(
            "DELETE FROM pgstac.collections WHERE id = %s", (collection_id,)
        )
