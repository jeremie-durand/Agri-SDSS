"""Unit tests for the POST /parquet/collections/{id}/invalidate endpoint."""

import pytest
from vector_api.materialize import materialize_collection

pytestmark = pytest.mark.unit


def test_invalidate_returns_true_when_connection_was_cached(
    parquet_app_client, temp_parquet_dir, sample_geoparquet
):
    materialize_collection(
        sample_geoparquet, temp_parquet_dir / "test_collection.duckdb"
    )
    parquet_app_client.get("/parquet/collections/test_collection/items")

    response = parquet_app_client.post(
        "/parquet/collections/test_collection/invalidate"
    )

    assert response.status_code == 200
    assert response.json() == {
        "collection_id": "test_collection",
        "invalidated": True,
    }


def test_invalidate_returns_false_when_nothing_was_cached(parquet_app_client):
    response = parquet_app_client.post(
        "/parquet/collections/never_queried/invalidate"
    )

    assert response.status_code == 200
    assert response.json() == {
        "collection_id": "never_queried",
        "invalidated": False,
    }
