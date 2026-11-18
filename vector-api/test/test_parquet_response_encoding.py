"""Characterization tests for the exact bytes of the /parquet responses.

Pinned before the Parquet routes moved off the event loop (#280), so that
rendering the responses in a worker thread provably changes nothing: dates,
timestamps and decimals keep their encoding, and translated errors keep the
request's locale.
"""

import datetime as dt
import json
from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import geopandas as gpd
import pytest
from fastapi.testclient import TestClient
from shapely.geometry import Point
from vector_api.app import app
from vector_api.duckdb_manager import DuckDBManager

COLLECTION: str = "typed_collection"
BASE: str = "http://testserver/vector-api/parquet/collections"
CRS84: str = "http://www.opengis.net/def/crs/OGC/1.3/CRS84"

FEATURES: list[dict[str, Any]] = [
    {
        "type": "Feature",
        "id": 1,
        "geometry": {"type": "Point", "coordinates": [-73.5, 45.5]},
        "properties": {
            "gid": 1,
            "observed_on": "2024-05-17",
            "measured_at": "2024-05-17T13:45:30",
            "amount": "12.50",
            "label": "Érable",
        },
    },
    {
        "type": "Feature",
        "id": 2,
        "geometry": {"type": "Point", "coordinates": [-72.95, 45.62]},
        "properties": {
            "gid": 2,
            "observed_on": "2025-01-02",
            "measured_at": "2025-01-02T08:00:00",
            "amount": "-3.75",
            "label": "Saint-Hyacinthe",
        },
    },
]
COLLECTION_LINKS: list[dict[str, str]] = [
    {
        "href": f"{BASE}/{COLLECTION}",
        "rel": "self",
        "type": "application/json",
        "title": "This collection",
    },
    {
        "href": f"{BASE}/{COLLECTION}/items",
        "rel": "items",
        "type": "application/geo+json",
        "title": "Items",
    },
    {
        "href": BASE,
        "rel": "parent",
        "type": "application/json",
        "title": "Collections",
    },
]
EXTENT: dict[str, Any] = {
    "spatial": {"bbox": [[-73.5, 45.5, -72.95, 45.62]], "crs": CRS84}
}


def _rendered(body: dict[str, Any]) -> bytes:
    """Encode body the way Starlette's JSONResponse renders it."""
    return json.dumps(
        body, ensure_ascii=False, allow_nan=False, indent=None, separators=(",", ":")
    ).encode("utf-8")


@pytest.fixture
def typed_client(tmp_path: Path) -> Iterator[TestClient]:
    """Full vector_api app over a collection with DATE, TIMESTAMP and DECIMAL."""
    gpd.GeoDataFrame(
        {
            "gid": [1, 2],
            "observed_on": [dt.date(2024, 5, 17), dt.date(2025, 1, 2)],
            "measured_at": [
                dt.datetime(2024, 5, 17, 13, 45, 30),
                dt.datetime(2025, 1, 2, 8, 0, 0),
            ],
            "amount": [Decimal("12.50"), Decimal("-3.75")],
            "label": ["Érable", "Saint-Hyacinthe"],
            "geometry": [Point(-73.5, 45.5), Point(-72.95, 45.62)],
        },
        crs="EPSG:4326",
    ).to_parquet(tmp_path / f"{COLLECTION}.parquet")
    manager = DuckDBManager(data_dir=str(tmp_path))
    with (
        patch("vector_api.app.connect_to_db", new=AsyncMock()),
        patch("vector_api.app.register_collection_catalog", new=AsyncMock()),
        patch("vector_api.app.close_db_connection", new=AsyncMock()),
        patch("vector_api.parquet_router.get_shared_manager", return_value=manager),
        patch("vector_api.config.EXTERNAL_ROOT", "/vector-api"),
    ):
        with TestClient(app) as client:
            yield client
    manager.close()


@pytest.mark.integration
def test_collections_bytes(typed_client: TestClient) -> None:
    """GET /parquet/collections keeps its exact body."""
    resp = typed_client.get("/parquet/collections")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/json"
    assert resp.content == _rendered(
        {
            "collections": [
                {
                    "id": COLLECTION,
                    "title": "Typed Collection",
                    "description": f"GeoParquet collection: {COLLECTION}",
                    "extent": EXTENT,
                    "itemType": "feature",
                    "crs": [CRS84],
                    "links": COLLECTION_LINKS,
                }
            ],
            "links": [
                {
                    "href": BASE,
                    "rel": "self",
                    "type": "application/json",
                    "title": "Parquet Collections",
                }
            ],
            "numberMatched": 1,
            "numberReturned": 1,
        }
    )


@pytest.mark.integration
def test_collection_bytes(typed_client: TestClient) -> None:
    """GET /parquet/collections/{id} keeps its exact body."""
    resp = typed_client.get(f"/parquet/collections/{COLLECTION}")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/json"
    assert resp.content == _rendered(
        {
            "id": COLLECTION,
            "title": "Typed Collection",
            "description": "GeoParquet collection with 2 features",
            "extent": EXTENT,
            "itemType": "feature",
            "crs": [CRS84],
            "storageCrs": CRS84,
            "links": COLLECTION_LINKS,
            "queryables": [
                {"name": "gid", "type": "BIGINT"},
                {"name": "observed_on", "type": "DATE"},
                {"name": "measured_at", "type": "TIMESTAMP"},
                {"name": "amount", "type": "DECIMAL(4,2)"},
                {"name": "label", "type": "VARCHAR"},
            ],
            "numberMatched": 2,
        }
    )


@pytest.mark.integration
def test_items_bytes(typed_client: TestClient) -> None:
    """Items encode dates, timestamps and decimals exactly as before."""
    resp = typed_client.get(f"/parquet/collections/{COLLECTION}/items?limit=10")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/json"
    assert resp.content == _rendered(
        {
            "type": "FeatureCollection",
            "features": FEATURES,
            "links": [
                {
                    "href": f"{BASE}/{COLLECTION}/items?limit=10&offset=0",
                    "rel": "self",
                    "type": "application/geo+json",
                },
                {
                    "href": f"{BASE}/{COLLECTION}",
                    "rel": "collection",
                    "type": "application/json",
                },
            ],
            "numberMatched": 2,
            "numberReturned": 2,
        }
    )


@pytest.mark.integration
def test_item_bytes(typed_client: TestClient) -> None:
    """A single item keeps its exact body, links included."""
    resp = typed_client.get(f"/parquet/collections/{COLLECTION}/items/2")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/json"
    assert resp.content == _rendered(
        {
            **FEATURES[1],
            "links": [
                {
                    "href": f"{BASE}/{COLLECTION}/items/2",
                    "rel": "self",
                    "type": "application/geo+json",
                },
                {
                    "href": f"{BASE}/{COLLECTION}",
                    "rel": "collection",
                    "type": "application/json",
                },
            ],
        }
    )


@pytest.mark.integration
def test_queryables_bytes(typed_client: TestClient) -> None:
    """Queryables keep their exact body."""
    resp = typed_client.get(f"/parquet/collections/{COLLECTION}/queryables")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/json"
    assert resp.content == _rendered(
        {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": f"{BASE}/{COLLECTION}/queryables",
            "type": "object",
            "title": f"Queryables for {COLLECTION}",
            "properties": {
                "gid": {"type": "integer"},
                "observed_on": {"type": "string"},
                "measured_at": {"type": "string"},
                "amount": {"type": "number"},
                "label": {"type": "string"},
            },
        }
    )


@pytest.mark.integration
@pytest.mark.parametrize(
    "language,detail",
    [
        ("fr", f"Entité introuvable : 99 dans la collection {COLLECTION}"),
        ("en", f"Item not found: 99 in collection {COLLECTION}"),
    ],
)
def test_missing_item_detail_follows_request_locale(
    typed_client: TestClient, language: str, detail: str
) -> None:
    """The 404 detail is translated into the locale the request asked for."""
    resp = typed_client.get(
        f"/parquet/collections/{COLLECTION}/items/99",
        headers={"Accept-Language": language},
    )
    assert resp.status_code == 404
    assert resp.headers["content-type"] == "application/json"
    assert resp.json() == {"detail": detail}
