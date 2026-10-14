"""Tests for the pedo-properties endpoint.

PostGIS is mocked; the DuckDB joins run for real against small Parquet
fixtures shaped like the IRDA 2026_01 tables.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import asyncpg
import pandas as pd
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from vector_api.duckdb_manager import DuckDBManager
from vector_api.pedo_properties_router import router

from agri_i18n.middleware import LocaleASGIMiddleware

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

_PREFIX = "couverture_pedologique_2026_01_"


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(router)
    app.add_middleware(LocaleASGIMiddleware)
    return TestClient(app)


@pytest.fixture
def pedo_manager(tmp_path):
    """DuckDBManager over Parquet fixtures for the four IRDA tables."""
    tables = {
        "couverture_pps": pd.DataFrame(
            {
                "code_polygone": ["P1", "P1", "P2", "P3"],
                "composante": ["21Cw", "21All", "21Cw", "21Xx"],
                "pourcentage": [60, 40, 100, 100],
                "numero_composante": [1, 2, 1, 1],
            }
        ),
        "bdhp_2026": pd.DataFrame(
            {
                "composante": ["21Cw", "21All", "21Xx"],
                "code_sol": ["CWA", "ALL", "XXX"],
                "groupe_hydrologique": ["C", "B", "NA"],
            }
        ),
        "ppc_eessaq": pd.DataFrame(
            {
                "codesiscan": ["CWA", "CWA", "CWA"],
                "hzn": ["B", "Ap1", "Ap2"],
                "profondeurlimiteinf": [None, 15.0, 30.0],
                "mva3": [1.45, 1.1667, 1.33],
            }
        ),
        "ppc_inventaire_1990": pd.DataFrame(
            {
                "code_sol": ["ALL", "ALL", "CWA"],
                "horizon": ["1", "2", "1"],
                "densite": [1.2, None, 9.99],
            }
        ),
    }
    for name, frame in tables.items():
        frame.to_parquet(tmp_path / f"{_PREFIX}{name}.parquet")
    return DuckDBManager(data_dir=str(tmp_path))


def _pool(rows=None, error=None):
    """asyncpg pool mock whose connection's fetch() returns rows or raises."""
    conn = AsyncMock()
    conn.fetch = AsyncMock(return_value=rows or [], side_effect=error)
    acquire_ctx = AsyncMock()
    acquire_ctx.__aenter__ = AsyncMock(return_value=conn)
    acquire_ctx.__aexit__ = AsyncMock(return_value=False)
    pool = MagicMock()
    pool.acquire = MagicMock(return_value=acquire_ctx)
    return pool


def _post(client, manager, rows=None, error=None, **kwargs):
    with patch(
        "vector_api.pedo_properties_router.get_pool",
        new=AsyncMock(return_value=_pool(rows, error)),
    ), patch(
        "vector_api.pedo_properties_router.get_shared_manager",
        return_value=manager,
    ):
        return client.post(
            "/pedo-properties", json={"geometry": _POLYGON_GEOM}, **kwargs
        )


@pytest.mark.integration
class TestPedoProperties:
    def test_components_weighted_by_parcel_area(self, client, pedo_manager):
        rows = [
            {"code_polygone": "P1", "fraction": 0.5},
            {"code_polygone": "P2", "fraction": 0.25},
        ]
        data = _post(client, pedo_manager, rows).json()

        shares = {c["composante"]: c["share_pct"] for c in data["components"]}
        assert shares == {"21Cw": 55.0, "21All": 20.0}
        assert data["components"][0]["composante"] == "21Cw"
        assert data["described_pct"] == 75.0
        assert data["dominant_hydrologic_group"] == "C"

    def test_bulk_density_by_depth_from_eessaq(self, client, pedo_manager):
        rows = [{"code_polygone": "P2", "fraction": 1.0}]
        component = _post(client, pedo_manager, rows).json()["components"][0]

        assert component["bulk_density"] == {
            "source": "eessaq",
            "horizons": [
                {
                    "horizon": "Ap1",
                    "depth_top_cm": 0.0,
                    "depth_bottom_cm": 15.0,
                    "g_cm3": 1.167,
                },
                {
                    "horizon": "Ap2",
                    "depth_top_cm": 15.0,
                    "depth_bottom_cm": 30.0,
                    "g_cm3": 1.33,
                },
                {
                    "horizon": "B",
                    "depth_top_cm": 30.0,
                    "depth_bottom_cm": None,
                    "g_cm3": 1.45,
                },
            ],
        }

    def test_bulk_density_falls_back_to_1990_inventory(self, client, pedo_manager):
        rows = [{"code_polygone": "P1", "fraction": 1.0}]
        components = _post(client, pedo_manager, rows).json()["components"]
        all_soil = next(c for c in components if c["composante"] == "21All")

        assert all_soil["bulk_density"] == {
            "source": "inventaire_1990",
            "horizons": [
                {
                    "horizon": "1",
                    "depth_top_cm": None,
                    "depth_bottom_cm": None,
                    "g_cm3": 1.2,
                }
            ],
        }

    def test_na_group_is_null_and_ignored_for_dominant(self, client, pedo_manager):
        rows = [{"code_polygone": "P3", "fraction": 1.0}]
        data = _post(client, pedo_manager, rows).json()

        assert data["components"][0]["hydrologic_group"] is None
        assert data["components"][0]["bulk_density"] == {
            "source": None,
            "horizons": [],
        }
        assert data["dominant_hydrologic_group"] is None

    def test_no_overlap_returns_empty_result(self, client, pedo_manager):
        data = _post(client, pedo_manager, rows=[]).json()

        assert data == {
            "components": [],
            "dominant_hydrologic_group": None,
            "described_pct": 0.0,
        }

    def test_missing_table_returns_503(self, client, tmp_path):
        rows = [{"code_polygone": "P1", "fraction": 1.0}]
        resp = _post(
            client,
            DuckDBManager(data_dir=str(tmp_path)),
            rows,
            headers={"Accept-Language": "en"},
        )

        assert resp.status_code == 503
        assert resp.json()["detail"] == "Pedological property tables are unavailable."

    def test_missing_table_message_defaults_to_french(self, client, tmp_path):
        rows = [{"code_polygone": "P1", "fraction": 1.0}]
        resp = _post(client, DuckDBManager(data_dir=str(tmp_path)), rows)

        assert resp.status_code == 503
        assert resp.json()["detail"] == (
            "Les tables de propriétés pédologiques sont indisponibles."
        )


@pytest.mark.mocked
class TestPedoPropertiesErrors:
    def test_missing_geometry_returns_422(self, client):
        resp = client.post("/pedo-properties", json={"other_field": "value"})
        assert resp.status_code == 422

    def test_db_error_returns_500(self, client, pedo_manager):
        class _FakePostgresError(asyncpg.exceptions.PostgresError):
            pass

        resp = _post(
            client,
            pedo_manager,
            error=_FakePostgresError("simulated db error"),
            headers={"Accept-Language": "en"},
        )
        assert resp.status_code == 500
        assert resp.json()["detail"] == "Internal database error"
