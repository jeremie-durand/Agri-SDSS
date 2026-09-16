"""
Tests for backend_utils.py shared validation and conversion utilities.

Markers:
  @pytest.mark.unit    — pure Python logic, no I/O
"""

from __future__ import annotations

from typing import Optional

import numpy as np
import pytest
import xarray as xr
from processes.backend_utils import (
    LocationType,
    LocationValidatorMixin,
    apply_variable_conversions,
)

# ---------------------------------------------------------------------------
# Minimal Pydantic model for LocationValidatorMixin tests
# ---------------------------------------------------------------------------


class _Input(LocationValidatorMixin):
    """Minimal model that exercises all LocationValidatorMixin validators."""

    location_type: LocationType
    farm_id: Optional[str] = None
    point: Optional[list] = None
    bbox: Optional[list] = None
    polygon: Optional[dict] = None


# ---------------------------------------------------------------------------
# TestLocationTypeEnum
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestLocationTypeEnum:
    def test_all_values_are_strings(self) -> None:
        for member in LocationType:
            assert isinstance(member.value, str)

    def test_expected_members(self) -> None:
        values = {m.value for m in LocationType}
        assert values == {"farm_id", "point", "bbox", "polygon"}

    def test_enum_from_string(self) -> None:
        assert LocationType("bbox") == LocationType.BBOX
        assert LocationType("farm_id") == LocationType.FARM_ID

    def test_invalid_value_raises(self) -> None:
        with pytest.raises(ValueError):
            LocationType("unknown")


# ---------------------------------------------------------------------------
# TestLocationValidatorMixin
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestLocationValidatorMixin:
    def test_valid_point_accepted(self) -> None:
        obj = _Input(location_type="point", point=[-73.5, 45.5])
        assert obj.point == [-73.5, 45.5]

    def test_longitude_out_of_range_raises(self) -> None:
        with pytest.raises(Exception, match="Longitude"):
            _Input(location_type="point", point=[181.0, 45.5])

    def test_latitude_out_of_range_raises(self) -> None:
        with pytest.raises(Exception, match="Latitude"):
            _Input(location_type="point", point=[-73.5, 91.0])

    def test_valid_bbox_accepted(self) -> None:
        obj = _Input(location_type="bbox", bbox=[-74.0, 45.0, -73.0, 46.0])
        assert obj.bbox == [-74.0, 45.0, -73.0, 46.0]

    def test_bbox_minx_ge_maxx_raises(self) -> None:
        with pytest.raises(Exception, match="minx"):
            _Input(location_type="bbox", bbox=[-73.0, 45.0, -74.0, 46.0])

    def test_bbox_miny_ge_maxy_raises(self) -> None:
        with pytest.raises(Exception, match="miny"):
            _Input(location_type="bbox", bbox=[-74.0, 46.0, -73.0, 45.0])

    def test_missing_farm_id_raises(self) -> None:
        with pytest.raises(Exception, match="farm_id"):
            _Input(location_type="farm_id")

    def test_missing_point_raises(self) -> None:
        with pytest.raises(Exception, match="point"):
            _Input(location_type="point")

    def test_missing_bbox_raises(self) -> None:
        with pytest.raises(Exception, match="bbox"):
            _Input(location_type="bbox")

    def test_missing_polygon_raises(self) -> None:
        with pytest.raises(Exception, match="polygon"):
            _Input(location_type="polygon")

    def test_valid_farm_id_accepted(self) -> None:
        obj = _Input(location_type="farm_id", farm_id="42")
        assert obj.farm_id == "42"

    def test_valid_polygon_accepted(self) -> None:
        poly = {"type": "Polygon", "coordinates": []}
        obj = _Input(location_type="polygon", polygon=poly)
        assert obj.polygon == poly


# ---------------------------------------------------------------------------
# TestApplyVariableConversions
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestApplyVariableConversions:
    def _make_ds(self, data: dict) -> xr.Dataset:
        """Build a minimal 1-D xarray Dataset from {netcdf_name: array} pairs."""
        return xr.Dataset(
            {k: ("time", np.array(v, dtype="float32")) for k, v in data.items()}
        )

    def test_offset_applied_correctly(self) -> None:
        ds = self._make_ds({"tasmin_nc": [273.15, 283.15]})
        canonical_to_netcdf = {"tasmin": "tasmin_nc"}
        var_registry = {"tasmin": {"add_offset": -273.15, "output_units": "degC"}}

        values, units = apply_variable_conversions(
            ds, canonical_to_netcdf, var_registry
        )

        assert abs(values["tasmin"][0] - 0.0) < 0.01
        assert abs(values["tasmin"][1] - 10.0) < 0.01

    def test_scale_factor_applied(self) -> None:
        ds = self._make_ds({"pr_nc": [1e-5]})
        canonical_to_netcdf = {"pr": "pr_nc"}
        var_registry = {"pr": {"scale_factor": 86400.0, "output_units": "mm/day"}}

        values, units = apply_variable_conversions(
            ds, canonical_to_netcdf, var_registry
        )

        assert abs(values["pr"][0] - 0.864) < 0.01

    def test_nan_becomes_none(self) -> None:
        ds = self._make_ds({"tas_nc": [float("nan"), 10.0]})
        canonical_to_netcdf = {"tas": "tas_nc"}
        var_registry = {"tas": {"output_units": "degC"}}

        values, _ = apply_variable_conversions(ds, canonical_to_netcdf, var_registry)

        assert values["tas"][0] is None
        assert values["tas"][1] is not None

    def test_scalar_value_rounded(self) -> None:
        ds = xr.Dataset({"t_nc": 273.15678})
        canonical_to_netcdf = {"t": "t_nc"}
        var_registry = {"t": {"add_offset": -273.15, "output_units": "degC"}}

        values, _ = apply_variable_conversions(ds, canonical_to_netcdf, var_registry)

        assert isinstance(values["t"], float)
        assert values["t"] == round(values["t"], 4)

    def test_output_units_returned(self) -> None:
        ds = self._make_ds({"pr_nc": [1.0]})
        canonical_to_netcdf = {"pr": "pr_nc"}
        var_registry = {"pr": {"output_units": "mm/day"}}

        _, units = apply_variable_conversions(ds, canonical_to_netcdf, var_registry)

        assert units["pr"] == "mm/day"

    def test_multiple_variables_processed(self) -> None:
        ds = self._make_ds({"tmin_nc": [270.0], "tmax_nc": [280.0]})
        canonical_to_netcdf = {"tasmin": "tmin_nc", "tasmax": "tmax_nc"}
        var_registry = {
            "tasmin": {"add_offset": -273.15, "output_units": "degC"},
            "tasmax": {"add_offset": -273.15, "output_units": "degC"},
        }

        values, units = apply_variable_conversions(
            ds, canonical_to_netcdf, var_registry
        )

        assert "tasmin" in values
        assert "tasmax" in values
        assert units["tasmin"] == "degC"
        assert units["tasmax"] == "degC"
