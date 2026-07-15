"""
Tests for the weather-timeseries OGC API process.

Markers:
  @pytest.mark.unit    — pure Python logic, no I/O
  @pytest.mark.mocked  — external I/O mocked (xarray, DB, YAML)
"""

from __future__ import annotations

import json
from typing import Any, Dict
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest
import xarray as xr
from processes.weather_backend.models import (
    GeoJSONGeometry,
    WeatherTimeseriesFeature,
    WeatherTimeseriesInput,
    WeatherTimeseriesProperties,
)
from processes.weather_backend.pavics_backend import (
    PAVICSBackend,
    _apply_rolling_dates,
    _cache,
    _make_cache_key,
)
from processes.weather_timeseries import WeatherTimeseriesProcessor
from processes.weather_timeseries_metadata import PROCESS_METADATA
from pygeoapi.process.base import ProcessorExecuteError

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

SAMPLE_REGISTRY: Dict[str, Any] = {
    "era5_land": {
        "title": "ERA5-Land Daily Reanalysis",
        "provider": "pavics",
        "opendap_path": "birdhouse/nrcan/era5_land/era5_land_day.ncml",
        "lat_dim": "lat",
        "lon_dim": "lon",
        "time_dim": "time",
        "valid_time_range": {"start": "1950-01-01", "end": "2023-12-31"},
        "variables": {
            "tasmin": {
                "netcdf_name": "tasmin",
                "native_units": "K",
                "output_units": "degC",
                "add_offset": -273.15,
            },
            "tasmax": {
                "netcdf_name": "tasmax",
                "native_units": "K",
                "output_units": "degC",
                "add_offset": -273.15,
            },
            "tas": {
                "netcdf_name": "tas",
                "native_units": "K",
                "output_units": "degC",
                "add_offset": -273.15,
            },
            "pr": {
                "netcdf_name": "pr",
                "native_units": "kg m-2 s-1",
                "output_units": "mm/day",
                "scale_factor": 86400.0,
            },
        },
    }
}


@pytest.fixture
def pavics_backend() -> PAVICSBackend:
    """PAVICSBackend with in-memory registry — no YAML file or network access."""
    return PAVICSBackend(
        tds_base_url="https://pavics.example.com/thredds",
        registry=SAMPLE_REGISTRY,
    )


@pytest.fixture
def processor_instance() -> WeatherTimeseriesProcessor:
    """WeatherTimeseriesProcessor with an in-memory-registry backend."""
    WeatherTimeseriesProcessor._backend = PAVICSBackend(
        tds_base_url="https://pavics.example.com/thredds",
        registry=SAMPLE_REGISTRY,
    )
    return WeatherTimeseriesProcessor({"name": "weather-timeseries"})


@pytest.fixture
def sample_xr_dataset() -> xr.Dataset:
    """Synthetic daily xarray Dataset mimicking ERA5-Land structure (5 days)."""
    times = pd.date_range("2020-01-01", periods=5, freq="D")
    lats = np.array([45.0, 45.25, 45.5])
    lons = np.array([-72.0, -71.75, -71.5])
    rng = np.random.default_rng(seed=42)
    # Values in Kelvin (native ERA5-Land units), ~263–278 K (-10 to +5 °C)
    tasmin = rng.uniform(263.15, 278.15, (5, 3, 3)).astype("float32")
    tasmax = rng.uniform(273.15, 288.15, (5, 3, 3)).astype("float32")
    return xr.Dataset(
        {
            "tasmin": (["time", "lat", "lon"], tasmin),
            "tasmax": (["time", "lat", "lon"], tasmax),
        },
        coords={"time": times, "lat": lats, "lon": lons},
    )


@pytest.fixture
def mock_db_connection():
    """MagicMock simulating a psycopg3 connection that returns a farm polygon."""
    sample_geom = json.dumps(
        {
            "type": "Polygon",
            "coordinates": [
                [
                    [-72.0, 45.0],
                    [-71.0, 45.0],
                    [-71.0, 46.0],
                    [-72.0, 46.0],
                    [-72.0, 45.0],
                ]
            ],
        }
    )
    mock_cursor = MagicMock()
    mock_cursor.__enter__ = lambda s: s
    mock_cursor.__exit__ = MagicMock(return_value=False)
    mock_cursor.fetchone.return_value = (sample_geom,)

    mock_conn = MagicMock()
    mock_conn.__enter__ = lambda s: s
    mock_conn.__exit__ = MagicMock(return_value=False)
    mock_conn.cursor.return_value = mock_cursor

    return mock_conn


@pytest.fixture
def minimal_valid_data() -> Dict[str, Any]:
    """Minimal valid process input dict for a bbox query."""
    return {
        "location_type": "bbox",
        "bbox": [-72.0, 45.0, -71.0, 46.0],
        "variables": ["tasmin", "tasmax"],
        "start_date": "2020-01-01",
        "end_date": "2020-01-05",
        "aggregation": "daily",
        "dataset": "era5_land",
    }


# ---------------------------------------------------------------------------
# Metadata tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestMetadata:
    def test_metadata_has_required_keys(self):
        for key in ("version", "id", "title", "description", "inputs", "outputs"):
            assert key in PROCESS_METADATA

    def test_metadata_id(self):
        assert PROCESS_METADATA["id"] == "weather-timeseries"

    def test_metadata_inputs_defined(self):
        inputs = PROCESS_METADATA["inputs"]
        for field in ("location_type", "variables", "start_date", "end_date"):
            assert field in inputs

    def test_metadata_outputs_defined(self):
        assert "result" in PROCESS_METADATA["outputs"]

    def test_metadata_example(self):
        example = PROCESS_METADATA["example"]["inputs"]
        assert example["location_type"] == "bbox"
        assert "variables" in example


# ---------------------------------------------------------------------------
# Pydantic input model tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestWeatherTimeseriesInput:
    def test_valid_bbox_input(self):
        obj = WeatherTimeseriesInput(
            location_type="bbox",
            bbox=[-72.0, 45.0, -71.0, 46.0],
            variables=["tasmin"],
            start_date="2020-01-01",
            end_date="2020-12-31",
        )
        assert obj.aggregation == "daily"
        assert obj.dataset == "era5_land"

    def test_invalid_location_type(self):
        with pytest.raises(Exception):
            WeatherTimeseriesInput(
                location_type="country",  # type: ignore[arg-type]
                bbox=[-72.0, 45.0, -71.0, 46.0],
                variables=["tasmin"],
                start_date="2020-01-01",
                end_date="2020-12-31",
            )

    def test_empty_variables_rejected(self):
        with pytest.raises(Exception):
            WeatherTimeseriesInput(
                location_type="bbox",
                bbox=[-72.0, 45.0, -71.0, 46.0],
                variables=[],
                start_date="2020-01-01",
                end_date="2020-12-31",
            )

    def test_invalid_date_format(self):
        with pytest.raises(Exception):
            WeatherTimeseriesInput(
                location_type="bbox",
                bbox=[-72.0, 45.0, -71.0, 46.0],
                variables=["tasmin"],
                start_date="01/01/2020",
                end_date="2020-12-31",
            )

    def test_start_after_end_rejected(self):
        with pytest.raises(Exception):
            WeatherTimeseriesInput(
                location_type="bbox",
                bbox=[-72.0, 45.0, -71.0, 46.0],
                variables=["tasmin"],
                start_date="2020-12-31",
                end_date="2020-01-01",
            )

    def test_bbox_minx_gte_maxx_rejected(self):
        with pytest.raises(Exception):
            WeatherTimeseriesInput(
                location_type="bbox",
                bbox=[-71.0, 45.0, -72.0, 46.0],  # minx > maxx
                variables=["tasmin"],
                start_date="2020-01-01",
                end_date="2020-12-31",
            )

    def test_missing_farm_id_field_rejected(self):
        with pytest.raises(Exception):
            WeatherTimeseriesInput(
                location_type="farm_id",
                # farm_id not provided
                variables=["tasmin"],
                start_date="2020-01-01",
                end_date="2020-12-31",
            )

    def test_missing_point_field_rejected(self):
        with pytest.raises(Exception):
            WeatherTimeseriesInput(
                location_type="point",
                # point not provided
                variables=["tasmin"],
                start_date="2020-01-01",
                end_date="2020-12-31",
            )

    def test_point_longitude_out_of_range(self):
        with pytest.raises(Exception):
            WeatherTimeseriesInput(
                location_type="point",
                point=[200.0, 45.0],  # lon > 180
                variables=["tasmin"],
                start_date="2020-01-01",
                end_date="2020-12-31",
            )

    def test_duplicate_variables_deduplicated(self):
        obj = WeatherTimeseriesInput(
            location_type="bbox",
            bbox=[-72.0, 45.0, -71.0, 46.0],
            variables=["tasmin", "tasmin", "tasmax"],
            start_date="2020-01-01",
            end_date="2020-12-31",
        )
        assert obj.variables == ["tasmin", "tasmax"]

    def test_invalid_aggregation_rejected(self):
        with pytest.raises(Exception):
            WeatherTimeseriesInput(
                location_type="bbox",
                bbox=[-72.0, 45.0, -71.0, 46.0],
                variables=["tasmin"],
                start_date="2020-01-01",
                end_date="2020-12-31",
                aggregation="weekly",  # type: ignore[arg-type]
            )


# ---------------------------------------------------------------------------
# GeoJSON output model tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestWeatherTimeseriesFeature:
    def _make_feature(self) -> WeatherTimeseriesFeature:
        return WeatherTimeseriesFeature(
            geometry=GeoJSONGeometry(
                type="Polygon",
                coordinates=[
                    [
                        [-72.0, 45.0],
                        [-71.0, 45.0],
                        [-71.0, 46.0],
                        [-72.0, 46.0],
                        [-72.0, 45.0],
                    ]
                ],
            ),
            properties=WeatherTimeseriesProperties(
                provider="pavics",
                dataset="era5_land",
                variables=["tasmin"],
                aggregation="daily",
                temporal_extent=["2020-01-01", "2020-01-05"],
                data={"time": ["2020-01-01"], "tasmin": [-3.0]},
                units={"tasmin": "degC"},
            ),
        )

    def test_type_is_feature(self):
        feature = self._make_feature()
        assert feature.type == "Feature"

    def test_to_geojson_returns_dict(self):
        feature = self._make_feature()
        result = feature.to_geojson()
        assert isinstance(result, dict)
        assert result["type"] == "Feature"
        assert "geometry" in result
        assert "properties" in result

    def test_geometry_is_polygon(self):
        feature = self._make_feature()
        assert feature.geometry.type == "Polygon"

    def test_properties_contain_data(self):
        feature = self._make_feature()
        assert "time" in feature.properties.data
        assert "tasmin" in feature.properties.data


# ---------------------------------------------------------------------------
# TTL cache tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCache:
    def setup_method(self):
        _cache.clear()

    def test_cache_miss_returns_none(self):
        assert _cache.get("nonexistent_key") is None

    def test_cache_set_and_get(self):
        key = _make_cache_key(
            (-72.0, 45.0, -71.0, 46.0),
            ("tasmin",),
            "2020-01-01",
            "2020-01-31",
            "daily",
            "era5_land",
        )
        dummy_feature = MagicMock(spec=WeatherTimeseriesFeature)
        _cache.set(key, dummy_feature)
        assert _cache.get(key) is dummy_feature

    def test_cache_key_deterministic(self):
        key1 = _make_cache_key(
            (-72.0, 45.0, -71.0, 46.0),
            ("tasmin",),
            "2020-01-01",
            "2020-01-31",
            "daily",
            "era5_land",
        )
        key2 = _make_cache_key(
            (-72.0, 45.0, -71.0, 46.0),
            ("tasmin",),
            "2020-01-01",
            "2020-01-31",
            "daily",
            "era5_land",
        )
        assert key1 == key2

    def test_cache_key_differs_for_different_params(self):
        key1 = _make_cache_key(
            (-72.0, 45.0, -71.0, 46.0),
            ("tasmin",),
            "2020-01-01",
            "2020-01-31",
            "daily",
            "era5_land",
        )
        key2 = _make_cache_key(
            (-72.0, 45.0, -71.0, 46.0),
            ("tasmax",),
            "2020-01-01",
            "2020-01-31",
            "daily",
            "era5_land",
        )
        assert key1 != key2

    def test_expired_cache_returns_none(self, monkeypatch):

        key = _make_cache_key(
            (-72.0, 45.0, -71.0, 46.0),
            ("tasmin",),
            "2020-01-01",
            "2020-01-31",
            "daily",
            "era5_land",
        )
        dummy_feature = MagicMock(spec=WeatherTimeseriesFeature)
        _cache.set(key, dummy_feature)

        # Fast-forward time beyond TTL
        monkeypatch.setattr(_cache, "_ttl", 0)
        import time

        time.sleep(0.01)
        assert _cache.get(key) is None


# ---------------------------------------------------------------------------
# PAVICSBackend unit tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestPAVICSBackendInternals:
    def test_get_dataset_config_known(self, pavics_backend):
        config = pavics_backend._get_dataset_config("era5_land")
        assert config["title"] == "ERA5-Land Daily Reanalysis"

    def test_get_dataset_config_unknown_raises(self, pavics_backend):
        with pytest.raises(ProcessorExecuteError, match="Unknown dataset"):
            pavics_backend._get_dataset_config("nonexistent")

    def test_build_opendap_url(self, pavics_backend):
        config = pavics_backend._get_dataset_config("era5_land")
        url = pavics_backend._build_opendap_url(config)
        assert url.startswith("https://pavics.example.com/thredds/dodsC/")
        assert "era5_land" in url

    def test_resolve_variable_names_known(self, pavics_backend):
        config = pavics_backend._get_dataset_config("era5_land")
        mapping = pavics_backend._resolve_variable_names(["tasmin", "tasmax"], config)
        assert mapping == {"tasmin": "tasmin", "tasmax": "tasmax"}

    def test_resolve_variable_names_unknown_raises(self, pavics_backend):
        config = pavics_backend._get_dataset_config("era5_land")
        with pytest.raises(ProcessorExecuteError, match="not available"):
            pavics_backend._resolve_variable_names(["wind_speed"], config)

    def test_subset_temporal(self, pavics_backend, sample_xr_dataset):
        result = pavics_backend._subset_temporal(
            sample_xr_dataset, "2020-01-02", "2020-01-04"
        )
        assert len(result.time) == 3

    def test_aggregate_monthly(self, pavics_backend):
        times = pd.date_range("2020-01-01", periods=60, freq="D")
        lats = np.array([45.0])
        lons = np.array([-72.0])
        data = np.ones((60, 1, 1), dtype="float32")
        ds = xr.Dataset(
            {"t2mn": (["time", "lat", "lon"], data)},
            coords={"time": times, "lat": lats, "lon": lons},
        )
        result = pavics_backend._aggregate_monthly(ds)
        # Jan (31 days) + Feb (29 days, 2020 is leap year) = 2 months
        assert len(result.time) == 2

    def test_aggregate_spatial_reduces_dims(self, pavics_backend, sample_xr_dataset):
        result = pavics_backend._aggregate_spatial(sample_xr_dataset, "lat", "lon")
        assert "lat" not in result.dims
        assert "lon" not in result.dims

    def test_aggregate_spatial_noop_for_point(self, pavics_backend):
        """After a point .sel(), lat/lon dims are gone — spatial agg is a no-op."""
        times = pd.date_range("2020-01-01", periods=3, freq="D")
        ds = xr.Dataset(
            {"t2mn": (["time"], np.array([1.0, 2.0, 3.0], dtype="float32"))},
            coords={"time": times},
        )
        result = pavics_backend._aggregate_spatial(ds, "lat", "lon")
        assert list(result.dims) == ["time"]

    def test_build_geometry_bbox(self, pavics_backend):
        geom = pavics_backend._build_geometry((-72.0, 45.0, -71.0, 46.0))
        assert geom.type == "Polygon"

    def test_build_geometry_point(self, pavics_backend):
        geom = pavics_backend._build_geometry((-72.0, 45.0, -72.0, 45.0))
        assert geom.type == "Point"

    def test_build_result_structure(self, pavics_backend, sample_xr_dataset):
        config = pavics_backend._get_dataset_config("era5_land")
        canonical_to_netcdf = {"tasmin": "tasmin", "tasmax": "tasmax"}
        # Spatially aggregate so the result is 1-D (time only)
        ds = pavics_backend._aggregate_spatial(sample_xr_dataset, "lat", "lon")
        ds.load()
        feature = pavics_backend._build_result(
            ds=ds,
            variables=["tasmin", "tasmax"],
            canonical_to_netcdf=canonical_to_netcdf,
            dataset_config=config,
            bbox=(-72.0, 45.0, -71.0, 46.0),
            aggregation="daily",
            dataset="era5_land",
            start_date="2020-01-01",
            end_date="2020-01-05",
        )
        assert isinstance(feature, WeatherTimeseriesFeature)
        assert feature.type == "Feature"
        assert feature.geometry.type == "Polygon"
        assert "time" in feature.properties.data
        assert "tasmin" in feature.properties.data
        assert "tasmax" in feature.properties.data
        assert len(feature.properties.data["time"]) == 5
        assert feature.properties.units["tasmin"] == "degC"


# ---------------------------------------------------------------------------
# PAVICSBackend mocked fetch tests
# ---------------------------------------------------------------------------


@pytest.mark.mocked
class TestPAVICSBackendFetch:
    def _make_open_dataset_mock(self, sample_ds: xr.Dataset):
        """Return a patcher that makes _open_dataset return sample_ds directly."""
        return patch.object(
            PAVICSBackend,
            "_open_dataset",
            return_value=sample_ds,
        )

    def test_fetch_bbox_daily(self, pavics_backend, sample_xr_dataset):
        _cache.clear()
        with self._make_open_dataset_mock(sample_xr_dataset):
            feature = pavics_backend.fetch(
                bbox=(-72.0, 45.0, -71.0, 46.0),
                variables=["tasmin", "tasmax"],
                start_date="2020-01-01",
                end_date="2020-01-05",
                aggregation="daily",
                dataset="era5_land",
            )
        assert isinstance(feature, WeatherTimeseriesFeature)
        assert feature.properties.aggregation == "daily"
        assert len(feature.properties.data["time"]) == 5

    def test_fetch_uses_cache_on_second_call(self, pavics_backend, sample_xr_dataset):
        _cache.clear()
        with self._make_open_dataset_mock(sample_xr_dataset) as mock_open:
            pavics_backend.fetch(
                bbox=(-72.0, 45.0, -71.0, 46.0),
                variables=["tasmin"],
                start_date="2020-01-01",
                end_date="2020-01-05",
                aggregation="daily",
                dataset="era5_land",
            )
            pavics_backend.fetch(
                bbox=(-72.0, 45.0, -71.0, 46.0),
                variables=["tasmin"],
                start_date="2020-01-01",
                end_date="2020-01-05",
                aggregation="daily",
                dataset="era5_land",
            )
        # OPeNDAP should be opened only once (second call hits cache)
        assert mock_open.call_count == 1

    def test_fetch_unknown_dataset_raises(self, pavics_backend):
        _cache.clear()
        with pytest.raises(ProcessorExecuteError, match="Unknown dataset"):
            pavics_backend.fetch(
                bbox=(-72.0, 45.0, -71.0, 46.0),
                variables=["tasmin"],
                start_date="2020-01-01",
                end_date="2020-01-05",
                aggregation="daily",
                dataset="does_not_exist",
            )

    def test_fetch_opendap_failure_raises(self, pavics_backend):
        _cache.clear()
        with patch.object(
            PAVICSBackend,
            "_open_dataset",
            side_effect=ProcessorExecuteError(
                "Failed to open OPeNDAP dataset at ...: Connection refused"
            ),
        ):
            with pytest.raises(ProcessorExecuteError, match="Failed to open OPeNDAP"):
                pavics_backend.fetch(
                    bbox=(-72.0, 45.0, -71.0, 46.0),
                    variables=["tasmin"],
                    start_date="2020-01-01",
                    end_date="2020-01-05",
                    aggregation="daily",
                    dataset="era5_land",
                )

    def test_fetch_point_returns_point_geometry(
        self, pavics_backend, sample_xr_dataset
    ):
        _cache.clear()
        # Point query: bbox is degenerate (minx==maxx, miny==maxy)
        with self._make_open_dataset_mock(sample_xr_dataset):
            feature = pavics_backend.fetch(
                bbox=(-72.0, 45.0, -72.0, 45.0),
                variables=["tasmin"],
                start_date="2020-01-01",
                end_date="2020-01-05",
                aggregation="daily",
                dataset="era5_land",
            )
        assert feature.geometry.type == "Point"

    def test_fetch_monthly_aggregation(self, pavics_backend):
        _cache.clear()
        times = pd.date_range("2020-01-01", periods=60, freq="D")
        lats = np.array([45.0, 45.5])
        lons = np.array([-72.0, -71.5])
        rng = np.random.default_rng(seed=0)
        data = rng.uniform(-5, 10, (60, 2, 2)).astype("float32")
        monthly_ds = xr.Dataset(
            {"tasmin": (["time", "lat", "lon"], data)},
            coords={"time": times, "lat": lats, "lon": lons},
        )
        with patch.object(PAVICSBackend, "_open_dataset", return_value=monthly_ds):
            feature = pavics_backend.fetch(
                bbox=(-72.0, 45.0, -71.0, 46.0),
                variables=["tasmin"],
                start_date="2020-01-01",
                end_date="2020-02-29",
                aggregation="monthly",
                dataset="era5_land",
            )
        # 2 months: January + February
        assert len(feature.properties.data["time"]) == 2


# ---------------------------------------------------------------------------
# WeatherTimeseriesProcessor full execute tests
# ---------------------------------------------------------------------------


@pytest.mark.mocked
class TestWeatherTimeseriesProcessorExecute:
    def _make_backend_fetch_mock(self, feature: WeatherTimeseriesFeature):
        """Patch backend.fetch to return a pre-built feature."""
        return patch.object(
            WeatherTimeseriesProcessor._backend,  # type: ignore[arg-type]
            "fetch",
            return_value=feature,
        )

    def _sample_feature(self) -> WeatherTimeseriesFeature:
        return WeatherTimeseriesFeature(
            geometry=GeoJSONGeometry(
                type="Polygon",
                coordinates=[
                    [
                        [-72.0, 45.0],
                        [-71.0, 45.0],
                        [-71.0, 46.0],
                        [-72.0, 46.0],
                        [-72.0, 45.0],
                    ]
                ],
            ),
            properties=WeatherTimeseriesProperties(
                provider="pavics",
                dataset="era5_land",
                variables=["tasmin", "tasmax"],
                aggregation="daily",
                temporal_extent=["2020-01-01", "2020-01-05"],
                data={
                    "time": [
                        "2020-01-01",
                        "2020-01-02",
                        "2020-01-03",
                        "2020-01-04",
                        "2020-01-05",
                    ],
                    "tasmin": [-3.0, -2.5, -1.0, 0.5, 1.2],
                    "tasmax": [4.0, 5.1, 6.2, 7.3, 8.0],
                },
                units={"tasmin": "degC", "tasmax": "degC"},
            ),
        )

    def test_execute_bbox_returns_geojson(self, processor_instance, minimal_valid_data):
        feature = self._sample_feature()
        with self._make_backend_fetch_mock(feature):
            mime, result = processor_instance.execute(minimal_valid_data)
        assert mime == "application/geo+json"
        assert result["id"] == "result"
        value = result["value"]
        assert value["type"] == "Feature"
        assert "geometry" in value
        assert "properties" in value

    def test_execute_invalid_location_type_raises(self, processor_instance):
        with pytest.raises(ProcessorExecuteError, match="Invalid inputs"):
            processor_instance.execute(
                {
                    "location_type": "country",
                    "variables": ["tasmin"],
                    "start_date": "2020-01-01",
                    "end_date": "2020-12-31",
                }
            )

    def test_execute_missing_bbox_raises(self, processor_instance):
        with pytest.raises(ProcessorExecuteError, match="Invalid inputs"):
            processor_instance.execute(
                {
                    "location_type": "bbox",
                    # bbox omitted
                    "variables": ["tasmin"],
                    "start_date": "2020-01-01",
                    "end_date": "2020-12-31",
                }
            )

    def test_execute_start_after_end_raises(self, processor_instance):
        with pytest.raises(ProcessorExecuteError, match="Invalid inputs"):
            processor_instance.execute(
                {
                    "location_type": "bbox",
                    "bbox": [-72.0, 45.0, -71.0, 46.0],
                    "variables": ["tasmin"],
                    "start_date": "2020-12-31",
                    "end_date": "2020-01-01",
                }
            )

    def test_execute_farm_id_db_lookup(self, processor_instance, mock_db_connection):
        feature = self._sample_feature()
        with patch(
            "processes.location_utils.psycopg.connect",
            return_value=mock_db_connection,
        ):
            with self._make_backend_fetch_mock(feature):
                mime, result = processor_instance.execute(
                    {
                        "location_type": "farm_id",
                        "farm_id": "42",
                        "variables": ["tasmin"],
                        "start_date": "2020-01-01",
                        "end_date": "2020-01-05",
                    }
                )
        assert mime == "application/geo+json"
        assert result["value"]["type"] == "Feature"

    def test_execute_farm_id_not_found_raises(
        self, processor_instance, mock_db_connection
    ):
        mock_db_connection.cursor.return_value.fetchone.return_value = None
        with patch(
            "processes.location_utils.psycopg.connect",
            return_value=mock_db_connection,
        ):
            with pytest.raises(ProcessorExecuteError, match="not found"):
                processor_instance.execute(
                    {
                        "location_type": "farm_id",
                        "farm_id": "999",
                        "variables": ["tasmin"],
                        "start_date": "2020-01-01",
                        "end_date": "2020-01-05",
                    }
                )

    def test_execute_invalid_farm_id_zero_raises(self, processor_instance):
        with pytest.raises(ProcessorExecuteError):
            processor_instance.execute(
                {
                    "location_type": "farm_id",
                    "farm_id": "0",
                    "variables": ["tasmin"],
                    "start_date": "2020-01-01",
                    "end_date": "2020-01-05",
                }
            )

    def test_execute_point_query(self, processor_instance):
        feature = self._sample_feature()
        feature.geometry.type = "Point"
        feature.geometry.coordinates = [-72.0, 45.0]
        with self._make_backend_fetch_mock(feature):
            mime, result = processor_instance.execute(
                {
                    "location_type": "point",
                    "point": [-72.0, 45.0],
                    "variables": ["tasmin"],
                    "start_date": "2020-01-01",
                    "end_date": "2020-01-05",
                }
            )
        assert mime == "application/geo+json"

    def test_execute_polygon_query(self, processor_instance):
        feature = self._sample_feature()
        polygon_geojson = {
            "type": "Polygon",
            "coordinates": [
                [
                    [-72.0, 45.0],
                    [-71.0, 45.0],
                    [-71.0, 46.0],
                    [-72.0, 46.0],
                    [-72.0, 45.0],
                ]
            ],
        }
        with self._make_backend_fetch_mock(feature):
            mime, result = processor_instance.execute(
                {
                    "location_type": "polygon",
                    "polygon": polygon_geojson,
                    "variables": ["tasmin"],
                    "start_date": "2020-01-01",
                    "end_date": "2020-01-05",
                }
            )
        assert mime == "application/geo+json"

    def test_execute_processor_repr(self, processor_instance):
        assert "WeatherTimeseriesProcessor" in repr(processor_instance)


# ---------------------------------------------------------------------------
# Rolling date logic tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestApplyRollingDates:
    def test_rolling_dataset_gets_dynamic_end_date(self):
        from datetime import date, timedelta

        registry = {
            "era5_land": {
                "rolling": True,
                "rolling_lag_days": 90,
                "valid_time_range": {"start": "1950-01-01", "end": "2026-02-28"},
            }
        }
        _apply_rolling_dates(registry)
        expected_end = (date.today() - timedelta(days=90)).strftime("%Y-%m-%d")
        assert registry["era5_land"]["valid_time_range"]["end"] == expected_end

    def test_non_rolling_dataset_end_date_unchanged(self):
        registry = {
            "rdrs_v2_1": {
                "valid_time_range": {"start": "1980-01-01", "end": "2018-12-31"},
            }
        }
        _apply_rolling_dates(registry)
        assert registry["rdrs_v2_1"]["valid_time_range"]["end"] == "2018-12-31"

    def test_custom_lag_days_applied(self):
        from datetime import date, timedelta

        registry = {
            "era5_land_hourly": {
                "rolling": True,
                "rolling_lag_days": 60,
                "valid_time_range": {"start": "1950-01-01", "end": "2026-02-28"},
            }
        }
        _apply_rolling_dates(registry)
        expected_end = (date.today() - timedelta(days=60)).strftime("%Y-%m-%d")
        assert registry["era5_land_hourly"]["valid_time_range"]["end"] == expected_end

    def test_default_lag_is_90_when_missing(self):
        from datetime import date, timedelta

        registry = {
            "era5_land": {
                "rolling": True,
                # rolling_lag_days not set
                "valid_time_range": {"start": "1950-01-01", "end": "2026-02-28"},
            }
        }
        _apply_rolling_dates(registry)
        expected_end = (date.today() - timedelta(days=90)).strftime("%Y-%m-%d")
        assert registry["era5_land"]["valid_time_range"]["end"] == expected_end

    def test_mixed_registry_only_patches_rolling(self):
        from datetime import date, timedelta

        registry = {
            "era5_land": {
                "rolling": True,
                "rolling_lag_days": 90,
                "valid_time_range": {"start": "1950-01-01", "end": "2026-02-28"},
            },
            "rdrs_v2_1": {
                "valid_time_range": {"start": "1980-01-01", "end": "2018-12-31"},
            },
        }
        _apply_rolling_dates(registry)
        expected_end = (date.today() - timedelta(days=90)).strftime("%Y-%m-%d")
        assert registry["era5_land"]["valid_time_range"]["end"] == expected_end
        assert registry["rdrs_v2_1"]["valid_time_range"]["end"] == "2018-12-31"

    def test_returns_registry(self):
        registry = {"era5_land": {"rolling": True, "rolling_lag_days": 90}}
        result = _apply_rolling_dates(registry)
        assert result is registry


@pytest.mark.unit
class TestDateValidation:
    def test_end_date_beyond_range_raises(self):
        registry = {
            "era5_land": {
                "title": "ERA5-Land",
                "provider": "pavics",
                "opendap_path": "birdhouse/nrcan/era5_land/era5_land_day.ncml",
                "lat_dim": "lat",
                "lon_dim": "lon",
                "time_dim": "time",
                "valid_time_range": {"start": "1950-01-01", "end": "2023-12-31"},
                "variables": {
                    "tasmin": {
                        "netcdf_name": "tasmin",
                        "native_units": "K",
                        "output_units": "degC",
                        "add_offset": -273.15,
                    }
                },
            }
        }
        backend = PAVICSBackend(
            tds_base_url="https://pavics.example.com/thredds",
            registry=registry,
        )
        _cache.clear()
        with pytest.raises(
            ProcessorExecuteError, match="exceeds the available data range"
        ):
            backend.fetch(
                bbox=(-72.0, 45.0, -71.0, 46.0),
                variables=["tasmin"],
                start_date="2023-01-01",
                end_date="2025-06-01",  # beyond 2023-12-31
                aggregation="daily",
                dataset="era5_land",
            )

    def test_end_date_at_range_boundary_does_not_raise(
        self, pavics_backend, sample_xr_dataset
    ):
        """end_date == valid_time_range.end is valid (not strictly greater)."""
        _cache.clear()
        with patch.object(
            PAVICSBackend, "_open_dataset", return_value=sample_xr_dataset
        ):
            # SAMPLE_REGISTRY has end: "2023-12-31"
            feature = pavics_backend.fetch(
                bbox=(-72.0, 45.0, -71.0, 46.0),
                variables=["tasmin"],
                start_date="2020-01-01",
                end_date="2023-12-31",
                aggregation="daily",
                dataset="era5_land",
            )
        assert feature is not None
