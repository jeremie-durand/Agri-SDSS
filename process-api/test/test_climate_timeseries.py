"""
Tests for the climate-timeseries OGC API process (CMIP6 projections).

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
from processes.climate_backend.cmip_backend import (
    CMIPBackend,
    _cache,
    _make_cache_key,
)
from processes.climate_backend.models import (
    ClimateTimeseriesFeature,
    ClimateTimeseriesInput,
    ClimateTimeseriesProperties,
    GeoJSONGeometry,
)
from processes.climate_timeseries import ClimateTimeseriesProcessor
from processes.climate_timeseries_metadata import PROCESS_METADATA
from pygeoapi.process.base import ProcessorExecuteError

# ---------------------------------------------------------------------------
# Sample registry (mirrors real climate_datasets.yaml structure)
# ---------------------------------------------------------------------------

SAMPLE_REGISTRY: Dict[str, Any] = {
    "cmip6_espo_g6_r2": {
        "title": "ESPO-G6-R2 CMIP6 Projections",
        "provider": "pavics",
        "catalog_path": "datasets/simulations/bias_adjusted/cmip6/ouranos/ESPO-G/ESPO-G6-R2v1.0.0",
        "filename_template": "day_ESPO-G6-R2_v1.0.0_CMIP6_ScenarioMIP_NAM_{institution}_{model}_{scenario}_{member_id}_{date_range}.ncml",
        "lat_dim": "lat",
        "lon_dim": "lon",
        "time_dim": "time",
        "valid_time_range": {"start": "1950-01-01", "end": "2100-12-31"},
        "supported_scenarios": ["ssp245", "ssp370", "ssp585"],
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
            "pr": {
                "netcdf_name": "pr",
                "native_units": "kg m-2 s-1",
                "output_units": "mm/day",
                "scale_factor": 86400.0,
            },
        },
        "models": {
            "MPI-ESM1-2-LR": {
                "institution": "MPI-M",
                "member_id": "r1i1p1f1",
                "date_range": "19500101-21001231",
            },
            "EC-Earth3-CC": {
                "institution": "EC-Earth-Consortium",
                "member_id": "r1i1p1f1",
                "date_range": "19500101-21001231",
                "supported_scenarios": ["ssp245", "ssp585"],
            },
        },
    }
}


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def cmip_backend() -> CMIPBackend:
    """CMIPBackend with in-memory registry — no YAML file or network access."""
    return CMIPBackend(
        tds_base_url="https://pavics.example.com/thredds",
        registry=SAMPLE_REGISTRY,
    )


@pytest.fixture
def processor_instance() -> ClimateTimeseriesProcessor:
    """ClimateTimeseriesProcessor with an in-memory-registry backend."""
    ClimateTimeseriesProcessor._backend = CMIPBackend(
        tds_base_url="https://pavics.example.com/thredds",
        registry=SAMPLE_REGISTRY,
    )
    return ClimateTimeseriesProcessor({"name": "climate-timeseries"})


@pytest.fixture
def sample_xr_dataset() -> xr.Dataset:
    """Synthetic daily xarray Dataset mimicking CMIP6 structure (5 days, Kelvin)."""
    times = pd.date_range("2050-01-01", periods=5, freq="D")
    lats = np.array([45.0, 45.25, 45.5])
    lons = np.array([-72.0, -71.75, -71.5])
    rng = np.random.default_rng(seed=99)
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
    """Minimal valid process input dict for a bbox CMIP6 query."""
    return {
        "location_type": "bbox",
        "bbox": [-72.0, 45.0, -71.0, 46.0],
        "variables": ["tasmin", "tasmax"],
        "start_date": "2050-01-01",
        "end_date": "2050-01-05",
        "aggregation": "daily",
        "dataset": "cmip6_espo_g6_r2",
        "scenario": "ssp245",
        "model": "MPI-ESM1-2-LR",
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
        assert PROCESS_METADATA["id"] == "climate-timeseries"

    def test_metadata_inputs_include_scenario_model(self):
        inputs = PROCESS_METADATA["inputs"]
        assert "scenario" in inputs
        assert "model" in inputs

    def test_metadata_variables_excludes_tas(self):
        variables_schema = PROCESS_METADATA["inputs"]["variables"]["schema"]
        enum = variables_schema["items"]["enum"]
        assert "tasmin" in enum
        assert "tasmax" in enum
        assert "pr" in enum
        assert "tas" not in enum

    def test_metadata_outputs_defined(self):
        assert "result" in PROCESS_METADATA["outputs"]


# ---------------------------------------------------------------------------
# Pydantic input model tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestClimateTimeseriesInput:
    def test_valid_input(self):
        obj = ClimateTimeseriesInput(
            location_type="bbox",
            bbox=[-72.0, 45.0, -71.0, 46.0],
            variables=["tasmin"],
            start_date="2050-01-01",
            end_date="2050-12-31",
            scenario="ssp245",
            model="MPI-ESM1-2-LR",
        )
        assert obj.aggregation == "daily"
        assert obj.dataset == "cmip6_espo_g6_r2"

    def test_invalid_scenario_rejected(self):
        with pytest.raises(Exception):
            ClimateTimeseriesInput(
                location_type="bbox",
                bbox=[-72.0, 45.0, -71.0, 46.0],
                variables=["tasmin"],
                start_date="2050-01-01",
                end_date="2050-12-31",
                scenario="ssp119",  # type: ignore[arg-type]
                model="MPI-ESM1-2-LR",
            )

    def test_tas_variable_rejected(self):
        """tas is not available in CMIP6 ESPO-G6-R2."""
        with pytest.raises(Exception):
            ClimateTimeseriesInput(
                location_type="bbox",
                bbox=[-72.0, 45.0, -71.0, 46.0],
                variables=["tas"],  # type: ignore[list-item]
                start_date="2050-01-01",
                end_date="2050-12-31",
                scenario="ssp245",
                model="MPI-ESM1-2-LR",
            )

    def test_start_after_end_rejected(self):
        with pytest.raises(Exception):
            ClimateTimeseriesInput(
                location_type="bbox",
                bbox=[-72.0, 45.0, -71.0, 46.0],
                variables=["tasmin"],
                start_date="2050-12-31",
                end_date="2050-01-01",
                scenario="ssp245",
                model="MPI-ESM1-2-LR",
            )

    def test_empty_model_rejected(self):
        with pytest.raises(Exception):
            ClimateTimeseriesInput(
                location_type="bbox",
                bbox=[-72.0, 45.0, -71.0, 46.0],
                variables=["tasmin"],
                start_date="2050-01-01",
                end_date="2050-12-31",
                scenario="ssp245",
                model="",
            )

    def test_bbox_minx_gte_maxx_rejected(self):
        with pytest.raises(Exception):
            ClimateTimeseriesInput(
                location_type="bbox",
                bbox=[-71.0, 45.0, -72.0, 46.0],
                variables=["tasmin"],
                start_date="2050-01-01",
                end_date="2050-12-31",
                scenario="ssp245",
                model="MPI-ESM1-2-LR",
            )

    def test_missing_bbox_field_rejected(self):
        with pytest.raises(Exception):
            ClimateTimeseriesInput(
                location_type="bbox",
                # bbox omitted
                variables=["tasmin"],
                start_date="2050-01-01",
                end_date="2050-12-31",
                scenario="ssp245",
                model="MPI-ESM1-2-LR",
            )

    def test_duplicate_variables_deduplicated(self):
        obj = ClimateTimeseriesInput(
            location_type="bbox",
            bbox=[-72.0, 45.0, -71.0, 46.0],
            variables=["tasmin", "tasmin", "tasmax"],
            start_date="2050-01-01",
            end_date="2050-12-31",
            scenario="ssp245",
            model="MPI-ESM1-2-LR",
        )
        assert obj.variables == ["tasmin", "tasmax"]


# ---------------------------------------------------------------------------
# CMIPBackend unit tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCMIPBackendInternals:
    def test_get_dataset_config_known(self, cmip_backend):
        config = cmip_backend._get_dataset_config("cmip6_espo_g6_r2")
        assert "ESPO-G6-R2" in config["title"]

    def test_get_dataset_config_unknown_raises(self, cmip_backend):
        with pytest.raises(ProcessorExecuteError, match="Unknown dataset"):
            cmip_backend._get_dataset_config("nonexistent")

    def test_get_model_config_known(self, cmip_backend):
        config = cmip_backend._get_dataset_config("cmip6_espo_g6_r2")
        model_config = cmip_backend._get_model_config(config, "MPI-ESM1-2-LR", "ssp245")
        assert model_config["institution"] == "MPI-M"

    def test_get_model_config_unknown_model_raises(self, cmip_backend):
        config = cmip_backend._get_dataset_config("cmip6_espo_g6_r2")
        with pytest.raises(ProcessorExecuteError, match="Unknown model"):
            cmip_backend._get_model_config(config, "FakeModel-1", "ssp245")

    def test_get_model_config_unsupported_scenario_raises(self, cmip_backend):
        """EC-Earth3-CC does not support ssp370."""
        config = cmip_backend._get_dataset_config("cmip6_espo_g6_r2")
        with pytest.raises(ProcessorExecuteError, match="not available"):
            cmip_backend._get_model_config(config, "EC-Earth3-CC", "ssp370")

    def test_build_opendap_url(self, cmip_backend):
        config = cmip_backend._get_dataset_config("cmip6_espo_g6_r2")
        model_config = cmip_backend._get_model_config(config, "MPI-ESM1-2-LR", "ssp245")
        url = cmip_backend._build_opendap_url(
            config, model_config, "MPI-ESM1-2-LR", "ssp245"
        )
        assert "dodsC" in url
        assert "MPI-ESM1-2-LR" in url
        assert "ssp245" in url
        assert "MPI-M" in url

    def test_resolve_variable_names_known(self, cmip_backend):
        config = cmip_backend._get_dataset_config("cmip6_espo_g6_r2")
        mapping = cmip_backend._resolve_variable_names(["tasmin", "tasmax"], config)
        assert mapping == {"tasmin": "tasmin", "tasmax": "tasmax"}

    def test_resolve_variable_names_unknown_raises(self, cmip_backend):
        config = cmip_backend._get_dataset_config("cmip6_espo_g6_r2")
        with pytest.raises(ProcessorExecuteError, match="not available"):
            cmip_backend._resolve_variable_names(["tas"], config)

    def test_subset_temporal(self, cmip_backend, sample_xr_dataset):
        result = cmip_backend._subset_temporal(
            sample_xr_dataset, "2050-01-02", "2050-01-04"
        )
        assert len(result.time) == 3

    def test_aggregate_monthly(self, cmip_backend):
        # 59 days: Jan (31) + Feb (28) = exactly 2 complete months
        times = pd.date_range("2050-01-01", periods=59, freq="D")
        lats = np.array([45.0])
        lons = np.array([-72.0])
        data = np.ones((59, 1, 1), dtype="float32")
        ds = xr.Dataset(
            {"tasmin": (["time", "lat", "lon"], data)},
            coords={"time": times, "lat": lats, "lon": lons},
        )
        result = cmip_backend._aggregate_monthly(ds)
        assert len(result.time) == 2

    def test_aggregate_spatial_reduces_dims(self, cmip_backend, sample_xr_dataset):
        result = cmip_backend._aggregate_spatial(sample_xr_dataset, "lat", "lon")
        assert "lat" not in result.dims
        assert "lon" not in result.dims

    def test_build_geometry_bbox(self, cmip_backend):
        geom = cmip_backend._build_geometry((-72.0, 45.0, -71.0, 46.0))
        assert geom.type == "Polygon"

    def test_build_geometry_point(self, cmip_backend):
        geom = cmip_backend._build_geometry((-72.0, 45.0, -72.0, 45.0))
        assert geom.type == "Point"

    def test_build_result_structure(self, cmip_backend, sample_xr_dataset):
        config = cmip_backend._get_dataset_config("cmip6_espo_g6_r2")
        canonical_to_netcdf = {"tasmin": "tasmin", "tasmax": "tasmax"}
        ds = cmip_backend._aggregate_spatial(sample_xr_dataset, "lat", "lon")
        ds.load()
        feature = cmip_backend._build_result(
            ds=ds,
            variables=["tasmin", "tasmax"],
            canonical_to_netcdf=canonical_to_netcdf,
            dataset_config=config,
            bbox=(-72.0, 45.0, -71.0, 46.0),
            aggregation="daily",
            dataset="cmip6_espo_g6_r2",
            scenario="ssp245",
            model="MPI-ESM1-2-LR",
            start_date="2050-01-01",
            end_date="2050-01-05",
        )
        assert isinstance(feature, ClimateTimeseriesFeature)
        assert feature.type == "Feature"
        assert feature.geometry.type == "Polygon"
        assert feature.properties.scenario == "ssp245"
        assert feature.properties.model == "MPI-ESM1-2-LR"
        assert "time" in feature.properties.data
        assert "tasmin" in feature.properties.data
        assert len(feature.properties.data["time"]) == 5
        assert feature.properties.units["tasmin"] == "degC"

    def test_unit_conversion_kelvin_to_celsius(self, cmip_backend, sample_xr_dataset):
        """Values in K should be offset to °C in the result."""
        config = cmip_backend._get_dataset_config("cmip6_espo_g6_r2")
        canonical_to_netcdf = {"tasmin": "tasmin"}
        ds = cmip_backend._aggregate_spatial(sample_xr_dataset, "lat", "lon")
        ds.load()
        # Raw values are ~263–278 K → expected °C range: -10 to +5
        feature = cmip_backend._build_result(
            ds=ds,
            variables=["tasmin"],
            canonical_to_netcdf=canonical_to_netcdf,
            dataset_config=config,
            bbox=(-72.0, 45.0, -71.0, 46.0),
            aggregation="daily",
            dataset="cmip6_espo_g6_r2",
            scenario="ssp245",
            model="MPI-ESM1-2-LR",
            start_date="2050-01-01",
            end_date="2050-01-05",
        )
        for val in feature.properties.data["tasmin"]:
            if val is not None:
                assert -20.0 < val < 20.0, f"Unexpected °C value: {val}"


# ---------------------------------------------------------------------------
# CMIPBackend TTL cache tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCMIPCache:
    def setup_method(self):
        _cache.clear()

    def test_cache_miss_returns_none(self):
        assert _cache.get("nonexistent") is None

    def test_cache_set_and_get(self):
        key = _make_cache_key(
            (-72.0, 45.0, -71.0, 46.0),
            ("tasmin",),
            "2050-01-01",
            "2050-01-31",
            "daily",
            "cmip6_espo_g6_r2",
            "ssp245",
            "MPI-ESM1-2-LR",
        )
        dummy = MagicMock(spec=ClimateTimeseriesFeature)
        _cache.set(key, dummy)
        assert _cache.get(key) is dummy

    def test_cache_key_includes_scenario_and_model(self):
        key1 = _make_cache_key(
            (-72.0, 45.0, -71.0, 46.0),
            ("tasmin",),
            "2050-01-01",
            "2050-01-31",
            "daily",
            "cmip6_espo_g6_r2",
            "ssp245",
            "MPI-ESM1-2-LR",
        )
        key2 = _make_cache_key(
            (-72.0, 45.0, -71.0, 46.0),
            ("tasmin",),
            "2050-01-01",
            "2050-01-31",
            "daily",
            "cmip6_espo_g6_r2",
            "ssp585",  # different scenario
            "MPI-ESM1-2-LR",
        )
        assert key1 != key2

    def test_expired_cache_returns_none(self, monkeypatch):
        key = _make_cache_key(
            (-72.0, 45.0, -71.0, 46.0),
            ("tasmin",),
            "2050-01-01",
            "2050-01-31",
            "daily",
            "cmip6_espo_g6_r2",
            "ssp245",
            "MPI-ESM1-2-LR",
        )
        dummy = MagicMock(spec=ClimateTimeseriesFeature)
        _cache.set(key, dummy)
        monkeypatch.setattr(_cache, "_ttl", 0)
        import time

        time.sleep(0.01)
        assert _cache.get(key) is None


# ---------------------------------------------------------------------------
# CMIPBackend mocked fetch tests
# ---------------------------------------------------------------------------


@pytest.mark.mocked
class TestCMIPBackendFetch:
    def _mock_open(self, sample_ds: xr.Dataset):
        return patch.object(CMIPBackend, "_open_dataset", return_value=sample_ds)

    def test_fetch_bbox_daily(self, cmip_backend, sample_xr_dataset):
        _cache.clear()
        with self._mock_open(sample_xr_dataset):
            feature = cmip_backend.fetch(
                bbox=(-72.0, 45.0, -71.0, 46.0),
                variables=["tasmin", "tasmax"],
                start_date="2050-01-01",
                end_date="2050-01-05",
                aggregation="daily",
                dataset="cmip6_espo_g6_r2",
                scenario="ssp245",
                model="MPI-ESM1-2-LR",
            )
        assert isinstance(feature, ClimateTimeseriesFeature)
        assert feature.properties.scenario == "ssp245"
        assert feature.properties.model == "MPI-ESM1-2-LR"
        assert len(feature.properties.data["time"]) == 5

    def test_fetch_cache_hit_skips_opendap(self, cmip_backend, sample_xr_dataset):
        _cache.clear()
        with self._mock_open(sample_xr_dataset) as mock_open:
            for _ in range(2):
                cmip_backend.fetch(
                    bbox=(-72.0, 45.0, -71.0, 46.0),
                    variables=["tasmin"],
                    start_date="2050-01-01",
                    end_date="2050-01-05",
                    aggregation="daily",
                    dataset="cmip6_espo_g6_r2",
                    scenario="ssp245",
                    model="MPI-ESM1-2-LR",
                )
        assert mock_open.call_count == 1

    def test_fetch_unknown_model_raises(self, cmip_backend):
        _cache.clear()
        with pytest.raises(ProcessorExecuteError, match="Unknown model"):
            cmip_backend.fetch(
                bbox=(-72.0, 45.0, -71.0, 46.0),
                variables=["tasmin"],
                start_date="2050-01-01",
                end_date="2050-01-05",
                aggregation="daily",
                dataset="cmip6_espo_g6_r2",
                scenario="ssp245",
                model="NoSuchModel",
            )

    def test_fetch_unsupported_scenario_for_model_raises(self, cmip_backend):
        _cache.clear()
        with pytest.raises(ProcessorExecuteError, match="not available"):
            cmip_backend.fetch(
                bbox=(-72.0, 45.0, -71.0, 46.0),
                variables=["tasmin"],
                start_date="2050-01-01",
                end_date="2050-01-05",
                aggregation="daily",
                dataset="cmip6_espo_g6_r2",
                scenario="ssp370",
                model="EC-Earth3-CC",  # only supports ssp245 + ssp585
            )

    def test_fetch_monthly_aggregation(self, cmip_backend):
        _cache.clear()
        times = pd.date_range("2050-01-01", periods=60, freq="D")
        lats = np.array([45.0, 45.5])
        lons = np.array([-72.0, -71.5])
        rng = np.random.default_rng(seed=1)
        data = rng.uniform(263, 285, (60, 2, 2)).astype("float32")
        ds = xr.Dataset(
            {"tasmin": (["time", "lat", "lon"], data)},
            coords={"time": times, "lat": lats, "lon": lons},
        )
        with patch.object(CMIPBackend, "_open_dataset", return_value=ds):
            feature = cmip_backend.fetch(
                bbox=(-72.0, 45.0, -71.0, 46.0),
                variables=["tasmin"],
                start_date="2050-01-01",
                end_date="2050-02-28",
                aggregation="monthly",
                dataset="cmip6_espo_g6_r2",
                scenario="ssp245",
                model="MPI-ESM1-2-LR",
            )
        assert len(feature.properties.data["time"]) == 2

    def test_fetch_opendap_failure_raises(self, cmip_backend):
        _cache.clear()
        with patch.object(
            CMIPBackend,
            "_open_dataset",
            side_effect=ProcessorExecuteError("Failed to open OPeNDAP dataset"),
        ):
            with pytest.raises(ProcessorExecuteError, match="Failed to open OPeNDAP"):
                cmip_backend.fetch(
                    bbox=(-72.0, 45.0, -71.0, 46.0),
                    variables=["tasmin"],
                    start_date="2050-01-01",
                    end_date="2050-01-05",
                    aggregation="daily",
                    dataset="cmip6_espo_g6_r2",
                    scenario="ssp245",
                    model="MPI-ESM1-2-LR",
                )


# ---------------------------------------------------------------------------
# ClimateTimeseriesProcessor execute tests
# ---------------------------------------------------------------------------


@pytest.mark.mocked
class TestClimateTimeseriesProcessorExecute:
    def _sample_feature(self) -> ClimateTimeseriesFeature:
        return ClimateTimeseriesFeature(
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
            properties=ClimateTimeseriesProperties(
                provider="pavics",
                dataset="cmip6_espo_g6_r2",
                scenario="ssp245",
                model="MPI-ESM1-2-LR",
                variables=["tasmin", "tasmax"],
                aggregation="daily",
                temporal_extent=["2050-01-01", "2050-01-05"],
                data={
                    "time": [
                        "2050-01-01",
                        "2050-01-02",
                        "2050-01-03",
                        "2050-01-04",
                        "2050-01-05",
                    ],
                    "tasmin": [-2.0, -1.5, -0.5, 0.5, 1.0],
                    "tasmax": [5.0, 6.1, 7.2, 8.3, 9.0],
                },
                units={"tasmin": "degC", "tasmax": "degC"},
            ),
        )

    def _mock_backend_fetch(self, feature: ClimateTimeseriesFeature):
        return patch.object(
            ClimateTimeseriesProcessor._backend,  # type: ignore[arg-type]
            "fetch",
            return_value=feature,
        )

    def test_execute_returns_geojson(self, processor_instance, minimal_valid_data):
        feature = self._sample_feature()
        with self._mock_backend_fetch(feature):
            mime, result = processor_instance.execute(minimal_valid_data)
        assert mime == "application/geo+json"
        assert result["id"] == "result"
        value = result["value"]
        assert value["type"] == "Feature"
        assert value["properties"]["scenario"] == "ssp245"
        assert value["properties"]["model"] == "MPI-ESM1-2-LR"

    def test_execute_invalid_scenario_raises(self, processor_instance):
        with pytest.raises(ProcessorExecuteError, match="Invalid inputs"):
            processor_instance.execute(
                {
                    "location_type": "bbox",
                    "bbox": [-72.0, 45.0, -71.0, 46.0],
                    "variables": ["tasmin"],
                    "start_date": "2050-01-01",
                    "end_date": "2050-01-05",
                    "scenario": "ssp999",
                    "model": "MPI-ESM1-2-LR",
                }
            )

    def test_execute_missing_scenario_raises(self, processor_instance):
        with pytest.raises(ProcessorExecuteError, match="Invalid inputs"):
            processor_instance.execute(
                {
                    "location_type": "bbox",
                    "bbox": [-72.0, 45.0, -71.0, 46.0],
                    "variables": ["tasmin"],
                    "start_date": "2050-01-01",
                    "end_date": "2050-01-05",
                    "model": "MPI-ESM1-2-LR",
                    # scenario missing
                }
            )

    def test_execute_farm_id_lookup(self, processor_instance, mock_db_connection):
        feature = self._sample_feature()
        with patch(
            "processes.location_utils.psycopg.connect",
            return_value=mock_db_connection,
        ):
            with self._mock_backend_fetch(feature):
                mime, result = processor_instance.execute(
                    {
                        "location_type": "farm_id",
                        "farm_id": "42",
                        "variables": ["tasmin"],
                        "start_date": "2050-01-01",
                        "end_date": "2050-01-05",
                        "scenario": "ssp245",
                        "model": "MPI-ESM1-2-LR",
                    }
                )
        assert mime == "application/geo+json"

    def test_execute_processor_repr(self, processor_instance):
        assert "ClimateTimeseriesProcessor" in repr(processor_instance)
