"""Mocked unit tests for the SOM field-match endpoint."""

from unittest.mock import AsyncMock, MagicMock, patch

import asyncpg
import pytest
from agri_i18n.middleware import LocaleASGIMiddleware
from fastapi import FastAPI
from fastapi.testclient import TestClient
from vector_api.som_router import router


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(router)
    app.add_middleware(LocaleASGIMiddleware)
    return TestClient(app)


def _make_pool(rows):
    """Build a minimal asyncpg pool mock that returns ``rows`` from fetch().

    asyncpg's pool.acquire() is a sync call that returns an async context
    manager — it is NOT awaited itself before the ``async with`` block.
    """
    conn = AsyncMock()
    conn.fetch = AsyncMock(return_value=rows)

    acquire_ctx = AsyncMock()
    acquire_ctx.__aenter__ = AsyncMock(return_value=conn)
    acquire_ctx.__aexit__ = AsyncMock(return_value=False)

    pool = MagicMock()
    pool.acquire = MagicMock(return_value=acquire_ctx)
    return pool


def _make_row(gid: int, has_gee_data: bool, dist: float = 0.0):
    """Build a minimal asyncpg Record mock with gid, has_gee_data, dist columns."""
    row = MagicMock()
    row.__getitem__ = lambda self, k: {
        "gid": gid,
        "has_gee_data": has_gee_data,
        "dist": dist,
    }[k]
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
class TestSomFieldMatch:
    def test_single_gee_match(self, client):
        pool = _make_pool([_make_row(966, True, 0.0)])
        with patch("vector_api.som_router.get_pool", new=AsyncMock(return_value=pool)):
            resp = client.post("/som-field-match", json={"geometry": _POLYGON_GEOM})
        assert resp.status_code == 200
        data = resp.json()
        assert "matches" in data
        assert data["matches"][0]["gid"] == 966
        assert data["matches"][0]["has_gee_data"] is True
        assert data["matches"][0]["dist_m"] == 0.0

    def test_multiple_matches(self, client):
        rows = [
            _make_row(966, True, 0.0),
            _make_row(967, False, 21.2),
            _make_row(968, True, 79.1),
        ]
        pool = _make_pool(rows)
        with patch("vector_api.som_router.get_pool", new=AsyncMock(return_value=pool)):
            resp = client.post("/som-field-match", json={"geometry": _POLYGON_GEOM})
        assert resp.status_code == 200
        assert len(resp.json()["matches"]) == 3

    def test_no_intersecting_fields(self, client):
        pool = _make_pool([])
        with patch("vector_api.som_router.get_pool", new=AsyncMock(return_value=pool)):
            resp = client.post("/som-field-match", json={"geometry": _POLYGON_GEOM})
        assert resp.status_code == 200
        assert resp.json() == {"matches": []}

    def test_missing_geometry_returns_422(self, client):
        resp = client.post("/som-field-match", json={"other_field": "value"})
        assert resp.status_code == 422

    def test_point_geometry_accepted(self, client):
        point_geom = {"type": "Point", "coordinates": [-72.347, 45.798]}
        pool = _make_pool([])
        with patch("vector_api.som_router.get_pool", new=AsyncMock(return_value=pool)):
            resp = client.post("/som-field-match", json={"geometry": point_geom})
        assert resp.status_code == 200

    def test_nearby_field_within_tolerance(self, client):
        """A field 80 m away (not intersecting) should still be returned."""
        pool = _make_pool([_make_row(965, True, 80.0)])
        with patch("vector_api.som_router.get_pool", new=AsyncMock(return_value=pool)):
            resp = client.post("/som-field-match", json={"geometry": _POLYGON_GEOM})
        assert resp.status_code == 200
        assert resp.json()["matches"][0]["dist_m"] == 80.0

    def test_db_error_returns_500(self, client):
        class _FakePostgresError(asyncpg.exceptions.PostgresError):
            pass

        conn = AsyncMock()
        conn.fetch = AsyncMock(side_effect=_FakePostgresError("simulated db error"))
        acquire_ctx = AsyncMock()
        acquire_ctx.__aenter__ = AsyncMock(return_value=conn)
        acquire_ctx.__aexit__ = AsyncMock(return_value=False)
        pool = MagicMock()
        pool.acquire = MagicMock(return_value=acquire_ctx)

        with patch("vector_api.som_router.get_pool", new=AsyncMock(return_value=pool)):
            resp = client.post(
                "/som-field-match",
                json={"geometry": _POLYGON_GEOM},
                headers={"Accept-Language": "en"},
            )
        assert resp.status_code == 500
        assert resp.json()["detail"] == "Internal database error"

    def test_db_error_message_is_localised(self, client):
        """The same failure comes back in French for a French client.

        End-to-end proof that the catalog reaches a real HTTP response, not
        just the gettext helpers.
        """

        class _FakePostgresError(asyncpg.exceptions.PostgresError):
            pass

        conn = AsyncMock()
        conn.fetch = AsyncMock(side_effect=_FakePostgresError("simulated db error"))
        acquire_ctx = AsyncMock()
        acquire_ctx.__aenter__ = AsyncMock(return_value=conn)
        acquire_ctx.__aexit__ = AsyncMock(return_value=False)
        pool = MagicMock()
        pool.acquire = MagicMock(return_value=acquire_ctx)

        with patch("vector_api.som_router.get_pool", new=AsyncMock(return_value=pool)):
            resp = client.post(
                "/som-field-match",
                json={"geometry": _POLYGON_GEOM},
                headers={"Accept-Language": "fr-CA,fr;q=0.9"},
            )
        assert resp.status_code == 500
        assert resp.json()["detail"] == "Erreur interne de la base de données"

    def test_missing_geometry_is_localised(self, client):
        """422 validation errors localise too, and default to French."""
        resp = client.post("/som-field-match", json={})
        assert resp.status_code == 422
        assert resp.json()["detail"] == "Le champ « geometry » est requis"

        resp = client.post(
            "/som-field-match", json={}, headers={"Accept-Language": "en"}
        )
        assert resp.status_code == 422
        assert resp.json()["detail"] == "'geometry' field is required"
