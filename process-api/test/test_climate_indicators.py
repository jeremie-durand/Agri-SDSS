"""
Tests for the climate-indicators OGC API process.

Markers:
  @pytest.mark.unit    — pure Python logic, no I/O
  @pytest.mark.mocked  — external I/O mocked
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import numpy as np
import pytest
from processes.climate_backend.cmip_backend import CMIPBackend
from processes.climate_backend.indicators import (
    calc_frost_days,
    calc_growing_degree_days,
    calc_heat_stress_days,
    calc_precipitation_days,
    calc_precipitation_total,
)
from processes.climate_backend.models import (
    ClimateIndicatorsInput,
    ClimateTimeseriesFeature,
    ClimateTimeseriesProperties,
    GeoJSONGeometry,
)
from processes.climate_indicators import ClimateIndicatorsProcessor
from processes.climate_indicators_metadata import PROCESS_METADATA
from processes.weather_backend.models import GeoJSONGeometry as WTGeometry
from processes.weather_backend.models import WeatherTimeseriesFeature as WTFeature
from processes.weather_backend.models import WeatherTimeseriesProperties as WTProps
from processes.weather_backend.pavics_backend import PAVICSBackend
from pygeoapi.process.base import ProcessorExecuteError

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

_BBOX_POLY_CLIMATE = GeoJSONGeometry(
    type="Polygon",
    coordinates=[
        [[-72.0, 45.0], [-71.0, 45.0], [-71.0, 46.0], [-72.0, 46.0], [-72.0, 45.0]]
    ],
)
_BBOX_POLY_WEATHER = WTGeometry(
    type="Polygon",
    coordinates=[
        [[-72.0, 45.0], [-71.0, 45.0], [-71.0, 46.0], [-72.0, 46.0], [-72.0, 45.0]]
    ],
)

_FIVE_DAYS = ["2020-04-01", "2020-04-02", "2020-04-03", "2020-04-04", "2020-04-05"]


def _make_weather_feature(tasmax: list, tasmin: list) -> WTFeature:
    """Build a synthetic WeatherTimeseriesFeature for mocking (tasmin + tasmax)."""
    return WTFeature(
        geometry=_BBOX_POLY_WEATHER,
        properties=WTProps(
            provider="pavics",
            dataset="era5_land",
            variables=["tasmin", "tasmax"],
            aggregation="daily",
            temporal_extent=["2020-04-01", "2020-04-05"],
            data={"time": _FIVE_DAYS, "tasmin": tasmin, "tasmax": tasmax},
            units={"tasmin": "degC", "tasmax": "degC"},
        ),
    )


def _make_weather_feature_single(variable: str, values: list) -> WTFeature:
    """Build a synthetic WeatherTimeseriesFeature for a single variable."""
    return WTFeature(
        geometry=_BBOX_POLY_WEATHER,
        properties=WTProps(
            provider="pavics",
            dataset="era5_land",
            variables=[variable],
            aggregation="daily",
            temporal_extent=["2020-04-01", "2020-04-05"],
            data={"time": _FIVE_DAYS, variable: values},
            units={variable: "degC" if variable != "pr" else "mm/day"},
        ),
    )


def _make_climate_feature(tasmax: list, tasmin: list) -> ClimateTimeseriesFeature:
    """Build a synthetic ClimateTimeseriesFeature for mocking."""
    return ClimateTimeseriesFeature(
        geometry=_BBOX_POLY_CLIMATE,
        properties=ClimateTimeseriesProperties(
            provider="pavics",
            dataset="cmip6_espo_g6_r2",
            scenario="ssp245",
            model="MPI-ESM1-2-LR",
            variables=["tasmin", "tasmax"],
            aggregation="daily",
            temporal_extent=["2050-04-01", "2050-04-05"],
            data={"time": _FIVE_DAYS, "tasmin": tasmin, "tasmax": tasmax},
            units={"tasmin": "degC", "tasmax": "degC"},
        ),
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def reset_processor_backends():
    """Ensure class-level backends are re-initialised for each test."""
    ClimateIndicatorsProcessor._weather_backend = None
    ClimateIndicatorsProcessor._climate_backend = None


@pytest.fixture
def processor_instance() -> ClimateIndicatorsProcessor:
    with patch.object(PAVICSBackend, "__init__", return_value=None), patch.object(
        CMIPBackend, "__init__", return_value=None
    ):
        proc = ClimateIndicatorsProcessor({"name": "climate-indicators"})
    return proc


# ---------------------------------------------------------------------------
# Metadata tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestMetadata:
    def test_metadata_required_keys(self):
        for key in ("version", "id", "title", "description", "inputs", "outputs"):
            assert key in PROCESS_METADATA

    def test_metadata_id(self):
        assert PROCESS_METADATA["id"] == "climate-indicators"

    def test_metadata_inputs_include_indicator(self):
        assert "indicator" in PROCESS_METADATA["inputs"]
        assert "base_temp" in PROCESS_METADATA["inputs"]

    def test_metadata_indicator_enum_has_gdd(self):
        enum = PROCESS_METADATA["inputs"]["indicator"]["schema"]["enum"]
        assert "gdd" in enum


# ---------------------------------------------------------------------------
# Pydantic input model tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestClimateIndicatorsInput:
    def test_valid_era5_input(self):
        obj = ClimateIndicatorsInput(
            location_type="bbox",
            bbox=[-72.0, 45.0, -71.0, 46.0],
            indicator="gdd",
            start_date="2020-04-01",
            end_date="2020-09-30",
        )
        assert obj.base_temp == 5.0
        assert obj.dataset == "era5_land"

    def test_valid_cmip6_input(self):
        obj = ClimateIndicatorsInput(
            location_type="bbox",
            bbox=[-72.0, 45.0, -71.0, 46.0],
            indicator="gdd",
            start_date="2050-04-01",
            end_date="2050-09-30",
            dataset="cmip6_espo_g6_r2",
            scenario="ssp245",
            model="MPI-ESM1-2-LR",
        )
        assert obj.scenario == "ssp245"

    def test_cmip6_without_scenario_raises(self):
        with pytest.raises(Exception):
            ClimateIndicatorsInput(
                location_type="bbox",
                bbox=[-72.0, 45.0, -71.0, 46.0],
                indicator="gdd",
                start_date="2050-04-01",
                end_date="2050-09-30",
                dataset="cmip6_espo_g6_r2",
                model="MPI-ESM1-2-LR",
                # scenario missing
            )

    def test_cmip6_without_model_raises(self):
        with pytest.raises(Exception):
            ClimateIndicatorsInput(
                location_type="bbox",
                bbox=[-72.0, 45.0, -71.0, 46.0],
                indicator="gdd",
                start_date="2050-04-01",
                end_date="2050-09-30",
                dataset="cmip6_espo_g6_r2",
                scenario="ssp245",
                # model missing
            )

    def test_base_temp_out_of_range_rejected(self):
        with pytest.raises(Exception):
            ClimateIndicatorsInput(
                location_type="bbox",
                bbox=[-72.0, 45.0, -71.0, 46.0],
                indicator="gdd",
                start_date="2020-04-01",
                end_date="2020-09-30",
                base_temp=20.0,  # > 15
            )

    def test_start_after_end_rejected(self):
        with pytest.raises(Exception):
            ClimateIndicatorsInput(
                location_type="bbox",
                bbox=[-72.0, 45.0, -71.0, 46.0],
                indicator="gdd",
                start_date="2020-09-30",
                end_date="2020-04-01",
            )


# ---------------------------------------------------------------------------
# calc_growing_degree_days pure function tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGrowingDegreeDays:
    def test_basic_computation(self):
        tasmax = np.array([20.0, 18.0, 15.0])
        tasmin = np.array([10.0, 8.0, 5.0])
        result = calc_growing_degree_days(tasmax, tasmin, base_temp=5.0)
        # (20+10)/2 - 5 = 10; (18+8)/2 - 5 = 8; (15+5)/2 - 5 = 5
        np.testing.assert_allclose(result, [10.0, 8.0, 5.0])

    def test_below_base_temp_returns_zero(self):
        tasmax = np.array([3.0])
        tasmin = np.array([1.0])
        result = calc_growing_degree_days(tasmax, tasmin, base_temp=5.0)
        # (3+1)/2 - 5 = -3 → clamped to 0
        assert result[0] == 0.0

    def test_exactly_at_base_temp_returns_zero(self):
        tasmax = np.array([5.0])
        tasmin = np.array([5.0])
        result = calc_growing_degree_days(tasmax, tasmin, base_temp=5.0)
        assert result[0] == 0.0

    def test_custom_base_temp(self):
        tasmax = np.array([12.0])
        tasmin = np.array([8.0])
        result = calc_growing_degree_days(tasmax, tasmin, base_temp=10.0)
        # (12+8)/2 - 10 = 0
        assert result[0] == 0.0

    def test_returns_float64(self):
        result = calc_growing_degree_days(np.array([20.0]), np.array([10.0]))
        assert result.dtype == np.float64

    def test_zero_length_input(self):
        result = calc_growing_degree_days(np.array([]), np.array([]))
        assert len(result) == 0


# ---------------------------------------------------------------------------
# ClimateIndicatorsProcessor execute tests (historical ERA5)
# ---------------------------------------------------------------------------


@pytest.mark.mocked
class TestClimateIndicatorsProcessorHistorical:
    def _make_proc(self) -> ClimateIndicatorsProcessor:
        with patch.object(PAVICSBackend, "__init__", return_value=None), patch.object(
            CMIPBackend, "__init__", return_value=None
        ):
            proc = ClimateIndicatorsProcessor({"name": "climate-indicators"})
        return proc

    def test_execute_gdd_historical(self):
        proc = self._make_proc()
        # 5 days, all above base_temp=5 → known GDD values
        tasmax = [20.0, 18.0, 15.0, 12.0, 10.0]
        tasmin = [10.0, 8.0, 5.0, 4.0, 2.0]
        feature = _make_weather_feature(tasmax, tasmin)

        proc._weather_backend = MagicMock()
        proc._weather_backend.fetch.return_value = feature

        mime, result = proc.execute(
            {
                "location_type": "bbox",
                "bbox": [-72.0, 45.0, -71.0, 46.0],
                "indicator": "gdd",
                "start_date": "2020-04-01",
                "end_date": "2020-04-05",
                "base_temp": 5.0,
                "dataset": "era5_land",
            }
        )
        assert mime == "application/geo+json"
        value = result["value"]
        assert value["type"] == "Feature"
        props = value["properties"]
        assert props["indicator"] == "gdd"
        assert props["base_temp"] == 5.0
        assert "total_gdd" in props["result"]
        assert props["result"]["total_gdd"] > 0
        # (20+10)/2-5=10, (18+8)/2-5=8, (15+5)/2-5=5, (12+4)/2-5=3, (10+2)/2-5=1 → total=27
        assert abs(props["result"]["total_gdd"] - 27.0) < 0.01

    def test_execute_gdd_all_below_base_temp(self):
        proc = self._make_proc()
        tasmax = [2.0, 1.0, 0.0]
        tasmin = [-3.0, -4.0, -5.0]
        feature = _make_weather_feature(tasmax, tasmin)
        proc._weather_backend = MagicMock()
        proc._weather_backend.fetch.return_value = feature

        mime, result = proc.execute(
            {
                "location_type": "bbox",
                "bbox": [-72.0, 45.0, -71.0, 46.0],
                "indicator": "gdd",
                "start_date": "2020-04-01",
                "end_date": "2020-04-03",
                "base_temp": 5.0,
                "dataset": "era5_land",
            }
        )
        assert result["value"]["properties"]["result"]["total_gdd"] == 0.0

    def test_execute_invalid_indicator_raises(self):
        proc = self._make_proc()
        with pytest.raises(ProcessorExecuteError, match="Invalid inputs"):
            proc.execute(
                {
                    "location_type": "bbox",
                    "bbox": [-72.0, 45.0, -71.0, 46.0],
                    "indicator": "unknown_indicator",
                    "start_date": "2020-04-01",
                    "end_date": "2020-04-05",
                }
            )


# ---------------------------------------------------------------------------
# ClimateIndicatorsProcessor execute tests (CMIP6 projections)
# ---------------------------------------------------------------------------


@pytest.mark.mocked
class TestClimateIndicatorsProcessorCMIP6:
    def _make_proc(self) -> ClimateIndicatorsProcessor:
        with patch.object(PAVICSBackend, "__init__", return_value=None), patch.object(
            CMIPBackend, "__init__", return_value=None
        ):
            proc = ClimateIndicatorsProcessor({"name": "climate-indicators"})
        return proc

    def test_execute_gdd_cmip6(self):
        proc = self._make_proc()
        tasmax = [22.0, 20.0, 18.0, 16.0, 14.0]
        tasmin = [12.0, 10.0, 8.0, 6.0, 4.0]
        feature = _make_climate_feature(tasmax, tasmin)

        proc._climate_backend = MagicMock()
        proc._climate_backend.fetch.return_value = feature

        mime, result = proc.execute(
            {
                "location_type": "bbox",
                "bbox": [-72.0, 45.0, -71.0, 46.0],
                "indicator": "gdd",
                "start_date": "2050-04-01",
                "end_date": "2050-04-05",
                "base_temp": 5.0,
                "dataset": "cmip6_espo_g6_r2",
                "scenario": "ssp245",
                "model": "MPI-ESM1-2-LR",
            }
        )
        assert mime == "application/geo+json"
        props = result["value"]["properties"]
        assert props["indicator"] == "gdd"
        # (22+12)/2-5=12, (20+10)/2-5=10, (18+8)/2-5=8, (16+6)/2-5=6, (14+4)/2-5=4 → total=40
        assert abs(props["result"]["total_gdd"] - 40.0) < 0.01

    def test_execute_cmip6_routes_to_climate_backend(self):
        proc = self._make_proc()
        tasmax = [20.0]
        tasmin = [10.0]
        feature = _make_climate_feature(tasmax, tasmin)

        proc._climate_backend = MagicMock()
        proc._climate_backend.fetch.return_value = feature
        proc._weather_backend = MagicMock()

        proc.execute(
            {
                "location_type": "bbox",
                "bbox": [-72.0, 45.0, -71.0, 46.0],
                "indicator": "gdd",
                "start_date": "2050-04-01",
                "end_date": "2050-04-01",
                "dataset": "cmip6_espo_g6_r2",
                "scenario": "ssp245",
                "model": "MPI-ESM1-2-LR",
            }
        )
        proc._climate_backend.fetch.assert_called_once()
        proc._weather_backend.fetch.assert_not_called()

    def test_execute_era5_routes_to_weather_backend(self):
        proc = self._make_proc()
        tasmax = [20.0]
        tasmin = [10.0]
        w_feature = _make_weather_feature(tasmax, tasmin)

        proc._weather_backend = MagicMock()
        proc._weather_backend.fetch.return_value = w_feature
        proc._climate_backend = MagicMock()

        proc.execute(
            {
                "location_type": "bbox",
                "bbox": [-72.0, 45.0, -71.0, 46.0],
                "indicator": "gdd",
                "start_date": "2020-04-01",
                "end_date": "2020-04-01",
                "dataset": "era5_land",
            }
        )
        proc._weather_backend.fetch.assert_called_once()
        proc._climate_backend.fetch.assert_not_called()


# ---------------------------------------------------------------------------
# Pure function tests — frost_days, heat_stress_days, precipitation_*
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestFrostDays:
    def test_counts_below_zero(self):
        arr = np.array([-5.0, -1.0, 0.0, 1.0, 3.0])
        # -5 and -1 are below 0; 0.0 is not (strict <)
        assert calc_frost_days(arr) == 2

    def test_all_above_zero_returns_zero(self):
        assert calc_frost_days(np.array([1.0, 2.0, 3.0])) == 0

    def test_all_below_zero_counts_all(self):
        arr = np.array([-10.0, -5.0, -1.0])
        assert calc_frost_days(arr) == 3

    def test_empty_array_returns_zero(self):
        assert calc_frost_days(np.array([])) == 0

    def test_returns_int(self):
        assert isinstance(calc_frost_days(np.array([-1.0, 1.0])), int)


@pytest.mark.unit
class TestHeatStressDays:
    def test_counts_above_default_threshold(self):
        arr = np.array([28.0, 30.0, 31.0, 35.0])
        # Only 31 and 35 are strictly > 30
        assert calc_heat_stress_days(arr) == 2

    def test_custom_threshold(self):
        arr = np.array([28.0, 30.0, 31.0, 35.0])
        assert calc_heat_stress_days(arr, threshold=25.0) == 4

    def test_none_above_threshold_returns_zero(self):
        assert calc_heat_stress_days(np.array([10.0, 20.0, 29.0])) == 0

    def test_empty_array_returns_zero(self):
        assert calc_heat_stress_days(np.array([])) == 0

    def test_returns_int(self):
        assert isinstance(calc_heat_stress_days(np.array([35.0])), int)


@pytest.mark.unit
class TestPrecipitationTotal:
    def test_sums_values(self):
        arr = np.array([2.0, 3.0, 5.0])
        assert abs(calc_precipitation_total(arr) - 10.0) < 1e-6

    def test_ignores_nan(self):
        arr = np.array([2.0, np.nan, 3.0])
        assert abs(calc_precipitation_total(arr) - 5.0) < 1e-6

    def test_all_zero_returns_zero(self):
        assert calc_precipitation_total(np.array([0.0, 0.0])) == 0.0

    def test_returns_float(self):
        assert isinstance(calc_precipitation_total(np.array([1.0])), float)


@pytest.mark.unit
class TestPrecipitationDays:
    def test_counts_above_default_threshold(self):
        arr = np.array([0.5, 1.0, 2.0, 5.0])
        # 0.5 and 1.0 are not strictly > 1.0; 2.0 and 5.0 are
        assert calc_precipitation_days(arr) == 2

    def test_custom_threshold(self):
        arr = np.array([0.5, 1.0, 2.0, 5.0])
        assert calc_precipitation_days(arr, threshold=0.0) == 4

    def test_none_above_threshold_returns_zero(self):
        assert calc_precipitation_days(np.array([0.1, 0.5, 1.0]), threshold=1.0) == 0

    def test_returns_int(self):
        assert isinstance(calc_precipitation_days(np.array([2.0])), int)


# ---------------------------------------------------------------------------
# New indicator processor tests (mocked)
# ---------------------------------------------------------------------------


@pytest.mark.mocked
class TestNewIndicatorsProcessor:
    def _make_proc(self) -> ClimateIndicatorsProcessor:
        with patch.object(PAVICSBackend, "__init__", return_value=None), patch.object(
            CMIPBackend, "__init__", return_value=None
        ):
            proc = ClimateIndicatorsProcessor({"name": "climate-indicators"})
        return proc

    def _exec(self, proc, indicator: str, extra: dict = None) -> dict:
        payload = {
            "location_type": "bbox",
            "bbox": [-72.0, 45.0, -71.0, 46.0],
            "indicator": indicator,
            "start_date": "2020-01-01",
            "end_date": "2020-01-05",
            "dataset": "era5_land",
        }
        if extra:
            payload.update(extra)
        _, result = proc.execute(payload)
        return result["value"]["properties"]

    def test_frost_days_count(self):
        proc = self._make_proc()
        # 3 days below 0, 2 above
        feature = _make_weather_feature_single("tasmin", [-5.0, -1.0, -0.5, 1.0, 3.0])
        proc._weather_backend = MagicMock()
        proc._weather_backend.fetch.return_value = feature

        props = self._exec(proc, "frost_days")
        assert props["indicator"] == "frost_days"
        assert props["result"]["frost_days"] == 3
        assert "time" in props["result"]
        assert props["base_temp"] is None

    def test_heat_stress_days_default_threshold(self):
        proc = self._make_proc()
        # 2 days above 30 °C
        feature = _make_weather_feature_single("tasmax", [28.0, 31.0, 35.0, 29.0, 25.0])
        proc._weather_backend = MagicMock()
        proc._weather_backend.fetch.return_value = feature

        props = self._exec(proc, "heat_stress_days")
        assert props["indicator"] == "heat_stress_days"
        assert props["result"]["heat_stress_days"] == 2
        assert props["result"]["threshold"] == 30.0

    def test_heat_stress_days_custom_threshold(self):
        proc = self._make_proc()
        feature = _make_weather_feature_single("tasmax", [28.0, 31.0, 35.0, 29.0, 25.0])
        proc._weather_backend = MagicMock()
        proc._weather_backend.fetch.return_value = feature

        props = self._exec(proc, "heat_stress_days", {"threshold": 27.0})
        # 28, 31, 35, 29 are all > 27 (4 days)
        assert props["result"]["heat_stress_days"] == 4
        assert props["result"]["threshold"] == 27.0

    def test_pr_total(self):
        proc = self._make_proc()
        feature = _make_weather_feature_single("pr", [1.0, 2.0, 0.5, 3.0, 0.0])
        proc._weather_backend = MagicMock()
        proc._weather_backend.fetch.return_value = feature

        props = self._exec(proc, "pr_total")
        assert props["indicator"] == "pr_total"
        assert abs(props["result"]["pr_total"] - 6.5) < 0.01

    def test_pr_days_with_explicit_threshold(self):
        proc = self._make_proc()
        # 2 days strictly > 1 mm/day (2.0 and 3.0); 1.0 is not strictly greater
        feature = _make_weather_feature_single("pr", [0.5, 1.0, 2.0, 3.0, 0.8])
        proc._weather_backend = MagicMock()
        proc._weather_backend.fetch.return_value = feature

        props = self._exec(proc, "pr_days", {"threshold": 1.0})
        assert props["indicator"] == "pr_days"
        assert props["result"]["pr_days"] == 2
        assert props["result"]["threshold"] == 1.0

    def test_pr_days_custom_threshold(self):
        proc = self._make_proc()
        feature = _make_weather_feature_single("pr", [0.5, 1.0, 2.0, 3.0, 0.8])
        proc._weather_backend = MagicMock()
        proc._weather_backend.fetch.return_value = feature

        props = self._exec(proc, "pr_days", {"threshold": 0.4})
        # All 5 values > 0.4
        assert props["result"]["pr_days"] == 5

    def test_pr_days_without_threshold_uses_model_default_30(self):
        """Without an explicit threshold, pr_days uses the model default (30.0).
        Typical precipitation values are well below 30 mm/day, so the result
        will be 0. Callers must pass threshold=1.0 explicitly for wet-day counts.
        """
        proc = self._make_proc()
        feature = _make_weather_feature_single("pr", [0.5, 1.0, 2.0, 5.0, 0.8])
        proc._weather_backend = MagicMock()
        proc._weather_backend.fetch.return_value = feature

        props = self._exec(proc, "pr_days")  # no threshold → defaults to 30.0
        assert props["result"]["threshold"] == 30.0
        assert props["result"]["pr_days"] == 0  # nothing exceeds 30 mm/day

    def test_metadata_indicator_enum_includes_all_indicators(self):
        from processes.climate_indicators_metadata import PROCESS_METADATA

        enum = PROCESS_METADATA["inputs"]["indicator"]["schema"]["enum"]
        for expected in (
            "gdd",
            "frost_days",
            "heat_stress_days",
            "pr_total",
            "pr_days",
        ):
            assert expected in enum

    def test_metadata_has_threshold_input(self):
        from processes.climate_indicators_metadata import PROCESS_METADATA

        assert "threshold" in PROCESS_METADATA["inputs"]
        schema = PROCESS_METADATA["inputs"]["threshold"]["schema"]
        assert schema["minimum"] == 0.0
        assert schema["maximum"] == 50.0
