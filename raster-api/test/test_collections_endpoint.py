"""Tests for the raster-api /collections listing endpoint."""
import pytest
from fastapi.testclient import TestClient

from raster_api.collections_router import list_cog_files
from raster_api.main import app


# ------------------------------------------
# list_cog_files() — pure directory-scanning logic
# ------------------------------------------


@pytest.mark.unit
def test_list_cog_files_finds_tif_and_tiff(tmp_path):
    """Both .tif and .tiff extensions are picked up."""
    (tmp_path / "a_cog.tif").touch()
    (tmp_path / "b_cog.tiff").touch()
    (tmp_path / "notes.txt").touch()

    result = list_cog_files(data_dir=str(tmp_path))

    ids = sorted(r["id"] for r in result)
    assert ids == ["a_cog", "b_cog"]


@pytest.mark.unit
def test_list_cog_files_id_strips_extension(tmp_path):
    """The id is the filename with the extension removed."""
    (tmp_path / "corg_fr_siigsol_cog.tif").touch()

    result = list_cog_files(data_dir=str(tmp_path))

    assert result == [
        {"id": "corg_fr_siigsol_cog", "title": "Corg Fr Siigsol Cog"}
    ]


@pytest.mark.unit
def test_list_cog_files_missing_directory_returns_empty(tmp_path):
    """A directory that doesn't exist returns an empty list, not an error."""
    missing = tmp_path / "does-not-exist"

    result = list_cog_files(data_dir=str(missing))

    assert result == []


@pytest.mark.unit
def test_list_cog_files_empty_directory_returns_empty(tmp_path):
    """An existing but empty directory returns an empty list."""
    result = list_cog_files(data_dir=str(tmp_path))

    assert result == []


# ------------------------------------------
# GET /collections — real TestClient against the wrapped TiTiler app
# ------------------------------------------


@pytest.fixture
def raster_client():
    with TestClient(app) as client:
        yield client


@pytest.mark.integration
def test_collections_endpoint_returns_cog_ids(tmp_path, monkeypatch, raster_client):
    """The endpoint reflects RASTER_COG_DIR's contents at request time."""
    (tmp_path / "ph_fr_siigsol_cog.tif").touch()
    (tmp_path / "cec_fr_siigsol_cog.tif").touch()
    monkeypatch.setenv("RASTER_COG_DIR", str(tmp_path))

    resp = raster_client.get("/collections")

    assert resp.status_code == 200
    ids = sorted(c["id"] for c in resp.json()["collections"])
    assert ids == ["cec_fr_siigsol_cog", "ph_fr_siigsol_cog"]


@pytest.mark.integration
def test_collections_endpoint_empty_when_dir_missing(monkeypatch, raster_client):
    """No crash, just an empty list, when RASTER_COG_DIR doesn't exist."""
    monkeypatch.setenv("RASTER_COG_DIR", "/nonexistent-dir")

    resp = raster_client.get("/collections")

    assert resp.status_code == 200
    assert resp.json() == {"collections": []}


@pytest.mark.integration
def test_existing_titiler_routes_still_work(raster_client):
    """Wrapping the app with our router doesn't break stock TiTiler routes."""
    resp = raster_client.get("/healthz")
    assert resp.status_code == 200
