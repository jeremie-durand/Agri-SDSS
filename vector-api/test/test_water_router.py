"""Mocked unit tests for the water-distance endpoint."""

from unittest.mock import AsyncMock, MagicMock, patch

import asyncpg
import pytest
from agri_i18n.middleware import LocaleASGIMiddleware
from fastapi import FastAPI
from fastapi.testclient import TestClient
from vector_api.water_router import router


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(router)
    app.add_middleware(LocaleASGIMiddleware)
    return TestClient(app)


def _make_pool(value):
    """Build a minimal asyncpg pool mock that returns ``value`` from fetchval().

    asyncpg's pool.acquire() is a sync call that returns an async context
    manager — it is NOT awaited itself before the ``async with`` block.
    """
    conn = AsyncMock()
    conn.fetchval = AsyncMock(return_value=value)

    acquire_ctx = AsyncMock()
    acquire_ctx.__aenter__ = AsyncMock(return_value=conn)
    acquire_ctx.__aexit__ = AsyncMock(return_value=False)

    pool = MagicMock()
    pool.acquire = MagicMock(return_value=acquire_ctx)
    return pool


_POLYGON_GEOM = {
    "type": "Polygon",
    "coordinates": [
        [
            [-72.35, 45.79],
            [-72.34, 45.79],
            [-72.34, 45.80],
            [-72.35, 45.80],
            [-72.35, 45.79],
        ]
    ],
}


@pytest.mark.unit
class TestWaterDistance:
    def test_distance_returned(self, client):
        pool = _make_pool(45.3)
        with patch(
            "vector_api.water_router.get_pool", new=AsyncMock(return_value=pool)
        ):
            resp = client.post("/water-distance", json={"geometry": _POLYGON_GEOM})
        assert resp.status_code == 200
        assert resp.json() == {"distance_m": 45.3}

    def test_no_water_features_returns_null(self, client):
        pool = _make_pool(None)
        with patch(
            "vector_api.water_router.get_pool", new=AsyncMock(return_value=pool)
        ):
            resp = client.post("/water-distance", json={"geometry": _POLYGON_GEOM})
        assert resp.status_code == 200
        assert resp.json() == {"distance_m": None}

    def test_beyond_100km_returns_null(self, client):
        """Distances beyond 100 km are outside GRHQ coverage — return null."""
        pool = _make_pool(150_000.0)
        with patch(
            "vector_api.water_router.get_pool", new=AsyncMock(return_value=pool)
        ):
            resp = client.post("/water-distance", json={"geometry": _POLYGON_GEOM})
        assert resp.status_code == 200
        assert resp.json() == {"distance_m": None}

    def test_missing_geometry_returns_422(self, client):
        resp = client.post("/water-distance", json={"other_field": "value"})
        assert resp.status_code == 422

    def test_db_error_returns_500(self, client):
        class _FakePostgresError(asyncpg.exceptions.PostgresError):
            pass

        conn = AsyncMock()
        conn.fetchval = AsyncMock(side_effect=_FakePostgresError("simulated db error"))
        acquire_ctx = AsyncMock()
        acquire_ctx.__aenter__ = AsyncMock(return_value=conn)
        acquire_ctx.__aexit__ = AsyncMock(return_value=False)
        pool = MagicMock()
        pool.acquire = MagicMock(return_value=acquire_ctx)

        with patch(
            "vector_api.water_router.get_pool", new=AsyncMock(return_value=pool)
        ):
            resp = client.post(
                "/water-distance",
                json={"geometry": _POLYGON_GEOM},
                headers={"Accept-Language": "en"},
            )
        assert resp.status_code == 500
        assert resp.json()["detail"] == "Internal database error"
