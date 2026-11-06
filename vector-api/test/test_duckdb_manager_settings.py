"""Unit tests for DuckDBManager's cache and query-slot settings."""

from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from vector_api.duckdb_manager import (
    DEFAULT_MAX_DUCKDB_QUERIES,
    DEFAULT_MAX_OPEN_DUCKDB,
    DuckDBConfigError,
    DuckDBManager,
)
from vector_api.parquet_router import router as parquet_router

pytestmark = pytest.mark.unit

SETTINGS: list[tuple[str, str]] = [
    ("max_open", "VECTOR_API_MAX_OPEN_DUCKDB"),
    ("max_queries", "VECTOR_API_MAX_DUCKDB_QUERIES"),
]


@pytest.fixture(autouse=True)
def _clear_settings_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for _, env_name in SETTINGS:
        monkeypatch.delenv(env_name, raising=False)


def test_settings_default_without_argument_or_env(tmp_path: Path) -> None:
    manager = DuckDBManager(data_dir=str(tmp_path))
    try:
        assert manager.max_open == DEFAULT_MAX_OPEN_DUCKDB == 2
        assert manager.max_queries == DEFAULT_MAX_DUCKDB_QUERIES == 1
    finally:
        manager.close()


@pytest.mark.parametrize(("attribute", "env_name"), SETTINGS)
def test_setting_read_from_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, attribute: str, env_name: str
) -> None:
    monkeypatch.setenv(env_name, "5")
    manager = DuckDBManager(data_dir=str(tmp_path))
    try:
        assert getattr(manager, attribute) == 5
    finally:
        manager.close()


@pytest.mark.parametrize(("attribute", "env_name"), SETTINGS)
def test_empty_env_setting_falls_back_to_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, attribute: str, env_name: str
) -> None:
    monkeypatch.setenv(env_name, "")
    manager = DuckDBManager(data_dir=str(tmp_path))
    try:
        assert getattr(manager, attribute) == {
            "max_open": DEFAULT_MAX_OPEN_DUCKDB,
            "max_queries": DEFAULT_MAX_DUCKDB_QUERIES,
        }[attribute]
    finally:
        manager.close()


@pytest.mark.parametrize(("attribute", "env_name"), SETTINGS)
def test_setting_argument_wins_over_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, attribute: str, env_name: str
) -> None:
    monkeypatch.setenv(env_name, "5")
    manager = DuckDBManager(data_dir=str(tmp_path), **{attribute: 3})
    try:
        assert getattr(manager, attribute) == 3
    finally:
        manager.close()


@pytest.mark.parametrize(("attribute", "env_name"), SETTINGS)
@pytest.mark.parametrize("raw", ["0", "-1", "abc", "2.5"])
def test_invalid_env_setting_names_the_variable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    attribute: str,
    env_name: str,
    raw: str,
) -> None:
    monkeypatch.setenv(env_name, raw)
    with pytest.raises(DuckDBConfigError, match=env_name):
        DuckDBManager(data_dir=str(tmp_path))


@pytest.mark.parametrize(("attribute", "env_name"), SETTINGS)
def test_invalid_argument_setting_names_the_variable(
    tmp_path: Path, attribute: str, env_name: str
) -> None:
    with pytest.raises(DuckDBConfigError, match=env_name):
        DuckDBManager(data_dir=str(tmp_path), **{attribute: 0})


def test_invalid_setting_is_a_server_error_not_a_bad_collection_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A ValueError would be reported as 400 "Invalid collection ID"."""
    monkeypatch.setenv("VECTOR_API_MAX_OPEN_DUCKDB", "0")
    app = FastAPI()
    app.include_router(parquet_router)
    with patch(
        "vector_api.parquet_router.get_shared_manager",
        side_effect=lambda: DuckDBManager(data_dir=str(tmp_path)),
    ):
        with TestClient(app) as client:
            resp = client.get("/parquet/collections/any_collection/items")

    assert resp.status_code == 500
    assert "VECTOR_API_MAX_OPEN_DUCKDB" not in resp.text
