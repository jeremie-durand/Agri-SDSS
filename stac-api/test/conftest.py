import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient
from stac_api.app import app as stac_app


@pytest.fixture(scope="session")
def unique_suffix() -> str:
    """Short random suffix so concurrent or repeated runs never collide."""
    return uuid.uuid4().hex[:8]


@pytest.fixture(scope="session")
def stac_integration_client():
    """Session-scoped TestClient against real stac-fastapi/pgstac.

    Skips only when the database is unreachable. Any other failure — a broken
    migration, a bad credential, an app-startup bug — propagates, because a
    reachable-but-failing stack is a bug rather than an absent environment.
    """
    try:
        with TestClient(stac_app, raise_server_exceptions=False) as client:
            yield client
    except OSError as exc:
        pytest.skip(
            f"pgstac database unavailable — skipping STAC integration tests: {exc}"
        )


@pytest.fixture(scope="session")
def sample_stac_collection(unique_suffix: str) -> dict[str, Any]:
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
def sample_stac_item(unique_suffix: str) -> dict[str, Any]:
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
