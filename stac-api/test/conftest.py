import os

import pytest
from fastapi.testclient import TestClient
from stac_fastapi.pgstac.app import app as stac_app


@pytest.fixture(scope="session")
def stac_api_url_fixture():
    return os.getenv("STAC_API_URL", "http://localhost:8081")


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
def sample_stac_collection():
    """Minimal valid STAC Collection for integration tests."""
    return {
        "type": "Collection",
        "id": "test-integration-collection",
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
def sample_stac_item():
    """Minimal valid STAC Item for integration tests (polygon near Montreal)."""
    return {
        "type": "Feature",
        "stac_version": "1.0.0",
        "stac_extensions": [],
        "id": "test-integration-item-001",
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
