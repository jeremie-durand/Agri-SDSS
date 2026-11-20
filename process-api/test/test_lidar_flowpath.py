"""
Tests for the lidar-flowpath process.

The tile index, gdalwarp (replaced by a fake that writes a synthetic 2 m
EPSG:32198 DTM over the requested extent) and the STAC API are patched.

Markers:
  @pytest.mark.unit    — pure logic (grid, statistics, metadata)
  @pytest.mark.mocked  — execute() with external I/O patched
"""

from __future__ import annotations

import importlib
import logging
import re
import subprocess
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
import rasterio
import yaml
from processes.hydro_backend.field_grid import (
    crop_slices,
    field_summary,
    snap_outwards,
)
from processes.jobs.http import rewrite_job_control
from processes.lidar_backend.quebec_lidar_tile_index import LidarTileIndex
from processes.lidar_flowpath import LidarFlowpathProcessor
from processes.lidar_flowpath_metadata import PROCESS_METADATA
from processes.quebec_lidar_fetch import LidarFetchProcessor
from pygeoapi.process.base import ProcessorExecuteError
from rasterio.transform import from_origin
from rasterio.warp import transform, transform_geom
from shapely.geometry import shape

import agri_i18n

CONFIG_PATH = Path(__file__).parent.parent.parent / "config" / "pygeoapi-config.yaml"
SHEET_URL = (
    "https://diffusion.example/Produits_derives_LiDAR/31H/31H03SE/MNT_31H03SE.tif"
)
ASYNC_CAPABLE: list[str] = ["sync-execute", "async-execute"]

_xs, _ys = transform("EPSG:4326", "EPSG:32198", [-72.95], [45.62])
# Half a metre off the 2 m grid, so snapping is unambiguous after the
# EPSG:4326 round trip.
ORIGIN_X: float = round(_xs[0] / 2) * 2 + 0.5
ORIGIN_Y: float = round(_ys[0] / 2) * 2 + 0.5

DemFactory = Callable[[np.ndarray, np.ndarray], np.ndarray]


def _plane_dem(x: np.ndarray, y: np.ndarray) -> np.ndarray:
    return 100.0 + 0.03 * (y - ORIGIN_Y) + 0.01 * (x - ORIGIN_X)


def _polygon_4326(coords_32198: list[tuple[float, float]]) -> dict[str, Any]:
    ring = [(ORIGIN_X + x, ORIGIN_Y + y) for x, y in coords_32198]
    ring.append(ring[0])
    return transform_geom(
        "EPSG:32198", "EPSG:4326", {"type": "Polygon", "coordinates": [ring]}
    )


def _square(x0: float, y0: float, size: float) -> dict[str, Any]:
    return _polygon_4326(
        [(x0, y0), (x0 + size, y0), (x0 + size, y0 + size), (x0, y0 + size)]
    )


FIELD = _square(0, 0, 200)


def _feature(geometry: dict[str, Any], zone_id: Any = None) -> dict[str, Any]:
    properties = {} if zone_id is None else {"id": zone_id}
    return {"type": "Feature", "properties": properties, "geometry": geometry}


def _zones(*features: dict[str, Any]) -> dict[str, Any]:
    return {"type": "FeatureCollection", "features": list(features)}


def _inputs(**extra: Any) -> dict[str, Any]:
    return {"location_type": "polygon", "polygon": FIELD, **extra}


def _expected_extent(margin: float) -> list[float]:
    """The FIELD bbox snapped outwards to 2 m, then widened by ``margin``."""
    return [
        ORIGIN_X - 0.5 - margin,
        ORIGIN_Y - 0.5 - margin,
        ORIGIN_X + 201.5 + margin,
        ORIGIN_Y + 201.5 + margin,
    ]


class FakeWarp:
    """Stands in for gdalwarp: writes a synthetic DTM over the -te extent."""

    def __init__(self, dem: DemFactory = _plane_dem) -> None:
        self.dem = dem
        self.commands: list[list[str]] = []

    def __call__(self, cmd: list[str], deadline: float) -> subprocess.CompletedProcess:
        self.commands.append(cmd)
        west, south, east, north = _extent(cmd)
        cell = float(cmd[cmd.index("-tr") + 1])
        cols, rows = round((east - west) / cell), round((north - south) / cell)
        x = west + (np.arange(cols) + 0.5) * cell
        y = north - (np.arange(rows) + 0.5) * cell
        xx, yy = np.meshgrid(x, y)
        with rasterio.open(
            cmd[-1],
            "w",
            driver="GTiff",
            height=rows,
            width=cols,
            count=1,
            dtype="float32",
            crs="EPSG:32198",
            transform=from_origin(west, north, cell, cell),
            nodata=-9999,
        ) as dst:
            dst.write(self.dem(xx, yy).astype("float32"), 1)
        return subprocess.CompletedProcess(cmd, 0, "", "")


def _extent(cmd: list[str]) -> list[float]:
    te = cmd.index("-te")
    return [float(v) for v in cmd[te + 1 : te + 5]]


@pytest.fixture(autouse=True)
def _public_host(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOST_PROTOCOL", "https")
    monkeypatch.setenv("HOST_URL", "agri.example")


@pytest.fixture
def processor(tmp_path: Path) -> LidarFlowpathProcessor:
    instance = LidarFlowpathProcessor({"name": "lidar-flowpath"})
    instance.output_dir = str(tmp_path)
    return instance


@pytest.fixture
def published() -> Iterator[list[dict[str, Any]]]:
    items: list[dict[str, Any]] = []

    def capture(item: dict[str, Any]) -> bool:
        items.append(item)
        return True

    with patch.object(LidarFetchProcessor, "_post_to_stac_api", side_effect=capture):
        yield items


@pytest.fixture
def tiles() -> Iterator[MagicMock]:
    with patch.object(
        LidarTileIndex, "get_tile_urls", return_value={"dtm": [SHEET_URL]}
    ) as mock:
        yield mock


def _run(
    processor: LidarFlowpathProcessor, data: dict[str, Any], warp: FakeWarp
) -> dict[str, Any]:
    with patch.object(processor, "_run_gdal", side_effect=warp):
        _mimetype, result = processor.execute(data)
    return result


def _error(processor: LidarFlowpathProcessor, data: dict[str, Any], lang: str) -> str:
    with agri_i18n.use_locale(lang), pytest.raises(ProcessorExecuteError) as exc:
        processor.execute(data)
    return str(exc.value)


def _cog(tmp_path: Path, asset: dict[str, Any]) -> Path:
    return tmp_path / asset["href"].rsplit("/", 1)[1]


# ---------------------------------------------------------------------------
# Grid, statistics and metadata
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_snap_outwards_expands_to_cell_multiples() -> None:
    assert snap_outwards((1.0, -3.0, 5.5, 2.0), 2.0) == (0.0, -4.0, 6.0, 2.0)


@pytest.mark.unit
def test_crop_slices_locate_inner_grid_with_asymmetric_margins() -> None:
    outer = (0.0, 0.0, 20.0, 10.0)
    inner = (6.0, 2.0, 10.0, 6.0)

    rows, cols = crop_slices(outer, inner, 2.0)

    assert (rows.start, rows.stop) == (2, 4)
    assert (cols.start, cols.stop) == (3, 5)


@pytest.mark.unit
def test_one_extreme_pixel_moves_max_only() -> None:
    ls = np.ones((10, 10))
    ls[4, 4] = 40.0
    pixels = np.ones(ls.shape, dtype=bool)

    summary = field_summary(pixels, np.full(ls.shape, 5.0), ls)

    assert summary["ls"]["max"] == 40.0
    assert summary["ls"]["median"] == 1.0
    assert summary["ls"]["p90"] == 1.0
    assert summary["slope"]["mean_percent"] == 5.0


@pytest.mark.unit
def test_empty_selection_gives_null_statistics() -> None:
    summary = field_summary(
        np.zeros((3, 3), dtype=bool), np.ones((3, 3)), np.ones((3, 3))
    )

    assert summary["slope"]["mean_percent"] is None
    assert summary["ls"] == {"mean": None, "median": None, "p90": None, "max": None}


@pytest.mark.unit
def test_metadata_declares_async_execution() -> None:
    assert PROCESS_METADATA["id"] == "lidar-flowpath"
    assert PROCESS_METADATA["jobControlOptions"] == ASYNC_CAPABLE
    assert set(PROCESS_METADATA["title"]) == {"en", "fr"}


@pytest.mark.unit
def test_served_description_lists_both_job_controls() -> None:
    """The registered processor's metadata is what process-api serves."""
    config = yaml.safe_load(CONFIG_PATH.read_text())
    class_path = config["resources"]["lidar-flowpath"]["processor"]["name"]
    module_name, class_name = class_path.rsplit(".", 1)
    processor_class = getattr(importlib.import_module(module_name), class_name)
    served = processor_class({"name": "lidar-flowpath"}).metadata

    description = rewrite_job_control(
        {"id": "lidar-flowpath", "jobControlOptions": ["sync-execute"]},
        lambda process_id: list(served["jobControlOptions"]),
    )

    assert description["jobControlOptions"] == ASYNC_CAPABLE


# ---------------------------------------------------------------------------
# Validation (translated)
# ---------------------------------------------------------------------------


_LINE = {"type": "LineString", "coordinates": [[-72.95, 45.62], [-72.9, 45.6]]}
_BAD_PROPERTIES = {
    "type": "Feature",
    "properties": "not-an-object",
    "geometry": _square(0, 0, 10),
}


@pytest.mark.mocked
@pytest.mark.parametrize(
    "data",
    [
        {"location_type": "point", "point": [-72.95, 45.62]},
        {"location_type": "polygon"},
        _inputs(point=[]),
        _inputs(upstream_margin_m=5000),
        _inputs(zones=_zones(*[_feature(_square(0, 0, 10)) for _ in range(51)])),
        _inputs(zones=_zones(_feature(_LINE))),
        _inputs(zones=_zones(_BAD_PROPERTIES)),
    ],
    ids=[
        "point",
        "missing-polygon",
        "empty-point",
        "margin",
        "too-many-zones",
        "line-zone",
        "properties-not-object",
    ],
)
def test_invalid_inputs_are_translated(
    processor: LidarFlowpathProcessor, data: dict[str, Any]
) -> None:
    assert _error(processor, data, "fr").startswith("Paramètres d'entrée invalides")
    assert _error(processor, data, "en").startswith("Invalid inputs")


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------


@pytest.mark.mocked
def test_happy_path_returns_layers_parameters_source_and_summary(
    processor: LidarFlowpathProcessor,
    tiles: MagicMock,
    published: list[dict[str, Any]],
    tmp_path: Path,
) -> None:
    warp = FakeWarp()

    result = _run(processor, _inputs(upstream_margin_m=150), warp)

    assert set(result["assets"]) == {"filled_dtm", "sca", "slope", "ls"}
    assert len(result["stac_items"]) == 4
    assert all(
        re.search(r"_geom_[0-9a-f]{16}_m150_v1$", item) for item in result["stac_items"]
    )
    assert result["parameters"]["upstream_margin_m"] == 150
    assert result["parameters"]["sca_cap_m"] == 300.0
    assert result["parameters"]["resolution_m"] == 2.0
    assert result["parameters"]["crs"] == "EPSG:32198"
    assert result["parameters"]["resampling"] == "average"
    assert result["source"]["sheets"] == ["31H03SE"]
    assert set(result["summary"]["ls"]) == {"mean", "median", "p90", "max"}
    assert result["summary"]["slope"]["mean_percent"] == pytest.approx(
        100 * np.hypot(0.03, 0.01), rel=0.02
    )
    for asset in result["assets"].values():
        assert asset["href"].startswith("https://agri.example/cog/lidar_flowpath_")
        assert "tilejson.json" in asset["tilejson"]
        with rasterio.open(_cog(tmp_path, asset)) as src:
            assert src.crs.to_string() == "EPSG:32198"
            assert src.res == (2.0, 2.0)
            assert src.nodata == -9999

    [cmd] = warp.commands
    assert cmd[cmd.index("-r") + 1] == "average"
    assert cmd[cmd.index("-t_srs") + 1] == "EPSG:32198"
    assert f"/vsicurl/{SHEET_URL}" in cmd
    assert _extent(cmd) == pytest.approx(_expected_extent(150), abs=1e-6)


@pytest.mark.mocked
def test_cropped_layers_line_up_with_the_field(
    processor: LidarFlowpathProcessor,
    tiles: MagicMock,
    published: list[dict[str, Any]],
    tmp_path: Path,
) -> None:
    """Filling leaves a plane unchanged, so a misaligned crop shows here."""
    result = _run(processor, _inputs(upstream_margin_m=150), FakeWarp())

    with rasterio.open(_cog(tmp_path, result["assets"]["filled_dtm"])) as src:
        values = src.read(1)
        row, col = src.index(ORIGIN_X + 50, ORIGIN_Y + 50)
        x, y = src.xy(row, col)
    assert values[row, col] == pytest.approx(
        float(_plane_dem(np.array(x), np.array(y))), abs=1e-3
    )


@pytest.mark.mocked
def test_default_margin_is_300_m(
    processor: LidarFlowpathProcessor,
    tiles: MagicMock,
    published: list[dict[str, Any]],
) -> None:
    warp = FakeWarp()

    result = _run(processor, _inputs(), warp)

    assert result["parameters"]["upstream_margin_m"] == 300
    assert _extent(warp.commands[0]) == pytest.approx(_expected_extent(300), abs=1e-6)


@pytest.mark.mocked
def test_farm_id_field_is_keyed_by_farm_and_cached(
    processor: LidarFlowpathProcessor,
    tiles: MagicMock,
    published: list[dict[str, Any]],
) -> None:
    warp = FakeWarp()
    data = {"location_type": "farm_id", "farm_id": "12"}

    with patch(
        "processes.spatial_backend.geometry.get_geometry_from_db", return_value=FIELD
    ) as lookup:
        first = _run(processor, data, warp)
        second = _run(processor, data, warp)

    lookup.assert_called_with("12")
    assert all("_farm_12_m300_v1" in item for item in first["stac_items"])
    assert second["stac_items"] == first["stac_items"]
    assert len(warp.commands) == 1


@pytest.mark.mocked
def test_bbox_field_is_computed(
    processor: LidarFlowpathProcessor,
    tiles: MagicMock,
    published: list[dict[str, Any]],
) -> None:
    west, south, east, north = shape(FIELD).bounds

    result = _run(
        processor,
        {"location_type": "bbox", "bbox": [west, south, east, north]},
        FakeWarp(),
    )

    assert result["bbox"] == pytest.approx([west, south, east, north])
    assert result["summary"]["ls"]["mean"] is not None


@pytest.mark.mocked
def test_stac_items_carry_collection_proj_and_sheets(
    processor: LidarFlowpathProcessor,
    tiles: MagicMock,
    published: list[dict[str, Any]],
) -> None:
    _run(processor, _inputs(), FakeWarp())

    assert len(published) == 4
    for item in published:
        assert item["properties"]["proj:code"] == "EPSG:32198"
        assert item["properties"]["agri_sdss:sheets"] == ["31H03SE"]
        assert item["id"].startswith("lidar_flowpath_")


@pytest.mark.mocked
def test_pixels_outside_l_shaped_field_are_nodata(
    processor: LidarFlowpathProcessor,
    tiles: MagicMock,
    published: list[dict[str, Any]],
    tmp_path: Path,
) -> None:
    l_shape = _polygon_4326(
        [(0, 0), (200, 0), (200, 100), (100, 100), (100, 200), (0, 200)]
    )

    result = _run(
        processor, {"location_type": "polygon", "polygon": l_shape}, FakeWarp()
    )

    with rasterio.open(_cog(tmp_path, result["assets"]["ls"])) as src:
        values = src.read(1)
        notch = src.index(ORIGIN_X + 150, ORIGIN_Y + 150)
        inside = src.index(ORIGIN_X + 50, ORIGIN_Y + 50)
    assert values[notch] == -9999
    assert values[inside] != -9999


@pytest.mark.mocked
def test_zones_summarised_in_order_with_positional_ids(
    processor: LidarFlowpathProcessor,
    tiles: MagicMock,
    published: list[dict[str, Any]],
) -> None:
    zones = _zones(
        _feature(_square(0, 0, 100), "A"),
        _feature(_square(100, 100, 100)),
        _feature(_square(151.0, 151.0, 0.5), "tiny"),
    )

    result = _run(processor, _inputs(zones=zones), FakeWarp())

    first, second, tiny = result["summary"]["zones"]
    assert first["id"] == "A"
    assert second["id"] == 2
    assert first["area_ha"] == pytest.approx(1.0, rel=0.05)
    assert set(first["ls"]) == {"mean", "median", "p90", "max"}
    assert first["slope"]["mean_percent"] is not None
    assert tiny["area_ha"] == 0
    assert tiny["slope"]["mean_percent"] is None
    assert tiny["ls"]["mean"] is None


@pytest.mark.mocked
def test_zone_outside_field_fails_before_any_fetch(
    processor: LidarFlowpathProcessor, tiles: MagicMock
) -> None:
    warp = FakeWarp()
    data = _inputs(zones=_zones(_feature(_square(5000, 5000, 100), "far")))

    with patch.object(processor, "_run_gdal", side_effect=warp):
        french = _error(processor, data, "fr")
        english = _error(processor, data, "en")

    assert french == (
        "Paramètres d'entrée invalides : La zone far ne recoupe pas le champ"
    )
    assert english == "Invalid inputs: Zone far does not intersect the field"
    assert warp.commands == []
    tiles.assert_not_called()


@pytest.mark.mocked
def test_cache_hit_with_other_zones_fetches_nothing(
    processor: LidarFlowpathProcessor,
    tiles: MagicMock,
    published: list[dict[str, Any]],
) -> None:
    warp = FakeWarp()
    first = _run(processor, _inputs(), warp)

    second = _run(processor, _inputs(zones=_zones(_feature(_square(0, 0, 100)))), warp)

    assert len(warp.commands) == 1
    assert tiles.call_count == 1
    assert len(published) == 4
    assert second["parameters"] == first["parameters"]
    assert second["source"] == first["source"]
    assert second["stac_items"] == first["stac_items"]
    assert second["summary"]["ls"] == first["summary"]["ls"]
    assert len(second["summary"]["zones"]) == 1


@pytest.mark.mocked
def test_missing_markers_relook_tiles_and_republish_without_rewarp(
    processor: LidarFlowpathProcessor,
    tiles: MagicMock,
    published: list[dict[str, Any]],
    tmp_path: Path,
) -> None:
    """A STAC outage on the first run leaves COGs without publish markers."""
    warp = FakeWarp()
    _run(processor, _inputs(), warp)
    for marker in tmp_path.glob("*.stac.json"):
        marker.unlink()

    second = _run(processor, _inputs(), warp)

    assert tiles.call_count == 2
    assert len(warp.commands) == 1
    assert len(published) == 8
    assert all(
        item["properties"]["agri_sdss:sheets"] == ["31H03SE"] for item in published[4:]
    )
    assert second["source"]["sheets"] == ["31H03SE"]


@pytest.mark.mocked
def test_other_margin_is_a_separate_cache_entry(
    processor: LidarFlowpathProcessor,
    tiles: MagicMock,
    published: list[dict[str, Any]],
) -> None:
    warp = FakeWarp()
    first = _run(processor, _inputs(upstream_margin_m=100), warp)

    second = _run(processor, _inputs(upstream_margin_m=200), warp)

    assert len(warp.commands) == 2
    assert first["stac_items"] != second["stac_items"]


@pytest.mark.mocked
def test_oversized_field_is_rejected_before_any_fetch(
    processor: LidarFlowpathProcessor, tiles: MagicMock
) -> None:
    warp = FakeWarp()
    data = {"location_type": "polygon", "polygon": _square(0, 0, 3000)}

    with patch.object(processor, "_run_gdal", side_effect=warp):
        message = _error(processor, data, "en")

    assert "exceeds maximum allowed (5.0 km²)" in message
    assert "9.0 km²" in message
    assert warp.commands == []
    tiles.assert_not_called()


@pytest.mark.mocked
def test_thin_field_with_large_margin_exceeds_grid_limit(
    processor: LidarFlowpathProcessor, tiles: MagicMock
) -> None:
    """A long strip passes the area cap but not the computation grid cap."""
    warp = FakeWarp()
    data = {
        "location_type": "polygon",
        "polygon": _polygon_4326([(0, 0), (78_000, 0), (78_000, 5), (0, 5)]),
        "upstream_margin_m": 1000,
    }

    with patch.object(processor, "_run_gdal", side_effect=warp):
        french = _error(processor, data, "fr")
        english = _error(processor, data, "en")

    assert "above the limit of 4.5 million" in english
    assert "upstream_margin_m" in english
    assert "au-delà de la limite de 4.5 millions" in french
    assert warp.commands == []
    tiles.assert_not_called()


@pytest.mark.mocked
def test_field_without_tiles_is_not_covered(
    processor: LidarFlowpathProcessor,
    published: list[dict[str, Any]],
    tmp_path: Path,
) -> None:
    with patch.object(LidarTileIndex, "get_tile_urls", return_value={}):
        message = _error(processor, _inputs(), "en")

    assert message.startswith("No LiDAR tiles found")
    assert published == []
    assert not list(tmp_path.glob("*.tif"))


@pytest.mark.mocked
def test_field_with_only_nodata_is_not_covered_with_lonlat_bbox(
    processor: LidarFlowpathProcessor,
    tiles: MagicMock,
    published: list[dict[str, Any]],
    tmp_path: Path,
) -> None:
    warp = FakeWarp(dem=lambda x, y: np.full(x.shape, -9999.0))

    with patch.object(processor, "_run_gdal", side_effect=warp):
        message = _error(processor, _inputs(), "en")

    assert message.startswith("No LiDAR tiles found")
    assert str(shape(FIELD).bounds) in message
    assert published == []
    assert not list(tmp_path.glob("*.tif"))


@pytest.mark.mocked
def test_failed_warp_is_a_translated_error(
    processor: LidarFlowpathProcessor, tiles: MagicMock
) -> None:
    failed = MagicMock(return_value=subprocess.CompletedProcess([], 1, "", "boom"))

    with patch.object(processor, "_run_gdal", failed):
        message = _error(processor, _inputs(), "fr")

    assert message == (
        "Impossible de préparer le modèle de terrain pour le calcul de l'écoulement."
    )


@pytest.mark.mocked
def test_spent_budget_after_warp_stops_before_hydrology(
    processor: LidarFlowpathProcessor,
    tiles: MagicMock,
    tmp_path: Path,
) -> None:
    processor.PROCESS_TIME_BUDGET_SECONDS = -1

    with (
        patch.object(processor, "_run_gdal", side_effect=FakeWarp()),
        patch("processes.lidar_flowpath.fill_depressions") as fill,
    ):
        message = _error(processor, _inputs(), "en")

    assert "exceeded the time limit" in message
    fill.assert_not_called()
    assert not list(tmp_path.glob("*.tif"))


@pytest.mark.mocked
def test_unexpected_error_is_generic_and_logged_in_english(
    processor: LidarFlowpathProcessor,
    tiles: MagicMock,
    published: list[dict[str, Any]],
    caplog: pytest.LogCaptureFixture,
) -> None:
    with (
        patch(
            "processes.lidar_flowpath.fill_depressions",
            side_effect=RuntimeError("kaboom"),
        ),
        patch.object(processor, "_run_gdal", side_effect=FakeWarp()),
        caplog.at_level(logging.ERROR, logger="processes.lidar_flowpath"),
    ):
        message = _error(processor, _inputs(), "en")

    assert message == "An unexpected error occurred while running this process."
    assert "Unexpected error in LidarFlowpathProcessor: kaboom" in caplog.text


@pytest.mark.unit
def test_square_field_at_area_limit_fits_the_grid_limit(
    processor: LidarFlowpathProcessor,
) -> None:
    side = 2236.0
    margin_bounds = snap_outwards((-1000.0, -1000.0, side + 1000.0, side + 1000.0), 2.0)

    processor._check_area((0.0, 0.0, side, side))
    processor._check_grid(margin_bounds)
