import os
import uuid

import psycopg
import pytest
from fastapi.testclient import TestClient
from stac_fastapi.pgstac.app import app as stac_app


def _admin_delete_collection(collection_id: str) -> None:
    """Remove a test collection as the pgstac admin.

    The app role holds only DML grants, and pgstac's collection delete trigger
    drops a partition table, which requires ownership -- so the API's DELETE
    returns InsufficientPrivilegeError. Tests clean up out-of-band instead.

    If a future change unsets PGSTAC_ADMIN_PASS in the stac-api container
    (a hardening step recommended elsewhere), this becomes a no-op and test
    collections will start accumulating. Adjust it then rather than silently
    losing cleanup.
    """
    admin_user = os.getenv("PGSTAC_ADMIN_USER")
    admin_pass = os.getenv("PGSTAC_ADMIN_PASS")
    if not (admin_user and admin_pass):
        return

    dsn = (
        f"host={os.getenv('PGHOST', 'database')} "
        f"dbname={os.getenv('PGDATABASE', 'agri_sdss')} "
        f"user={admin_user} password={admin_pass}"
    )
    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute(
            "DELETE FROM pgstac.items WHERE collection = %s", (collection_id,)
        )
        conn.execute(
            "DELETE FROM pgstac.collections WHERE id = %s", (collection_id,)
        )


@pytest.fixture(scope="session")
def unique_suffix() -> str:
    """Short random suffix so concurrent or repeated runs never collide."""
    return uuid.uuid4().hex[:8]


@pytest.fixture(scope="session")
def stac_integration_client():
    """Session-scoped TestClient against real stac-fastapi/pgstac.

    Skips automatically if PostgreSQL or pgstac schema is unavailable
    (e.g. unit-test runs without Docker Compose). Safe to run in CI.
    """
    try:
        with TestClient(stac_app, raise_server_exceptions=False) as client:
            yield client
    except Exception as exc:
        pytest.skip(
            f"pgstac database unavailable — skipping STAC integration tests: {exc}"
        )


@pytest.fixture(scope="session")
def sample_stac_collection(unique_suffix):
    """Minimal valid STAC Collection for integration tests."""
    return {
        "type": "Collection",
        "id": f"test-integration-collection-{unique_suffix}",
        "stac_version": "1.0.0",
        "description": "Integration test collection — created and deleted by test suite",
        "links": [],
        "title": "Test Integration Collection",
        "extent": {
            "spatial": {"bbox": [[-180, -90, 180, 90]]},
            "temporal": {"interval": [["2020-01-01T00:00:00Z", None]]},
        },
        "license": "proprietary",
    }


@pytest.fixture(scope="session")
def sample_stac_item(unique_suffix):
    """Minimal valid STAC Item for integration tests (polygon near Montreal)."""
    return {
        "type": "Feature",
        "stac_version": "1.0.0",
        "stac_extensions": [],
        "id": f"test-integration-item-{unique_suffix}",
        "geometry": {
            "type": "Polygon",
            "coordinates": [
                [
                    [-73.5, 45.5],
                    [-73.4, 45.5],
                    [-73.4, 45.6],
                    [-73.5, 45.6],
                    [-73.5, 45.5],
                ]
            ],
        },
        "bbox": [-73.5, 45.5, -73.4, 45.6],
        "properties": {"datetime": "2024-06-15T12:00:00Z"},
        "links": [],
        "assets": {},
    }
