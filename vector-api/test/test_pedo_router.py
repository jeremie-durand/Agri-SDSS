"""Mocked unit tests for the pedo-coverage endpoint."""

from unittest.mock import AsyncMock, MagicMock, patch

import asyncpg
import pytest
from agri_i18n.middleware import LocaleASGIMiddleware
from fastapi import FastAPI
from fastapi.testclient import TestClient
from vector_api.pedo_router import router


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(router)
    app.add_middleware(LocaleASGIMiddleware)
    return TestClient(app)


def _make_pool(row):
    """Build a minimal asyncpg pool mock that returns ``row`` from fetchrow().

    asyncpg's pool.acquire() is a sync call that returns an async context
    manager — it is NOT awaited itself before the ``async with`` block.
    """
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value=row)

    acquire_ctx = AsyncMock()
    acquire_ctx.__aenter__ = AsyncMock(return_value=conn)
    acquire_ctx.__aexit__ = AsyncMock(return_value=False)

    pool = MagicMock()
    pool.acquire = MagicMock(return_value=acquire_ctx)
    return pool


def _make_row(symbole: str, total: int):
    """Build a minimal asyncpg Record mock with symbole and total columns."""
    row = MagicMock()
    row.__getitem__ = lambda self, k: {"symbole": symbole, "total": total}[k]
    return row


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
class TestPedoCoverage:
    def test_dominant_class_returned(self, client):
        pool = _make_pool(_make_row("GL", 3))
        with patch("vector_api.pedo_router.get_pool", new=AsyncMock(return_value=pool)):
            resp = client.post("/pedo-coverage", json={"geometry": _POLYGON_GEOM})
        assert resp.status_code == 200
        data = resp.json()
        assert data["description"] == "GL"
        assert data["count"] == 3

    def test_no_coverage_returns_null(self, client):
        pool = _make_pool(None)
        with patch("vector_api.pedo_router.get_pool", new=AsyncMock(return_value=pool)):
            resp = client.post("/pedo-coverage", json={"geometry": _POLYGON_GEOM})
        assert resp.status_code == 200
        assert resp.json() == {"description": None, "count": 0}

    def test_missing_geometry_returns_422(self, client):
        resp = client.post("/pedo-coverage", json={"other_field": "value"})
        assert resp.status_code == 422

    def test_db_error_returns_500(self, client):
        class _FakePostgresError(asyncpg.exceptions.PostgresError):
            pass

        conn = AsyncMock()
        conn.fetchrow = AsyncMock(side_effect=_FakePostgresError("simulated db error"))
        acquire_ctx = AsyncMock()
        acquire_ctx.__aenter__ = AsyncMock(return_value=conn)
        acquire_ctx.__aexit__ = AsyncMock(return_value=False)
        pool = MagicMock()
        pool.acquire = MagicMock(return_value=acquire_ctx)

        with patch("vector_api.pedo_router.get_pool", new=AsyncMock(return_value=pool)):
            resp = client.post(
                "/pedo-coverage",
                json={"geometry": _POLYGON_GEOM},
                headers={"Accept-Language": "en"},
            )
        assert resp.status_code == 500
        assert resp.json()["detail"] == "Internal database error"
