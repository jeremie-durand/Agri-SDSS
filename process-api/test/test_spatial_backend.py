"""
Tests for the spatial_backend input models and geometry preparation.

Markers:
  @pytest.mark.unit    — pure Python logic, no I/O
  @pytest.mark.mocked  — external I/O mocked (farm lookup)
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from processes.spatial_backend import (
    PedoCoverageInput,
    SomFieldMatchInput,
    WaterDistanceInput,
    prepare_geometry,
)
from pydantic import ValidationError
from pygeoapi.process.base import ProcessorExecuteError
from shapely.geometry import shape

import agri_i18n

_SQUARE = {
    "type": "Polygon",
    "coordinates": [
        [[-72.0, 45.0], [-71.99, 45.0], [-71.99, 45.01], [-72.0, 45.01], [-72.0, 45.0]]
    ],
}

_BOW_TIE = {
    "type": "Polygon",
    "coordinates": [
        [[-72.0, 45.0], [-71.99, 45.01], [-71.99, 45.0], [-72.0, 45.01], [-72.0, 45.0]]
    ],
}

_COLLAPSED = {
    "type": "Polygon",
    "coordinates": [[[-72.0, 45.0], [-71.99, 45.0], [-72.0, 45.0], [-72.0, 45.0]]],
}


@pytest.fixture(autouse=True)
def _english_messages():
    """Assert against the English msgids rather than the French default."""
    with agri_i18n.use_locale("en"):
        yield


# ---------------------------------------------------------------------------
# Input models
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_polygon_input_uses_defaults():
    validated = WaterDistanceInput(location_type="polygon", polygon=_SQUARE)

    assert validated.max_distance_m == 100_000


@pytest.mark.unit
def test_bbox_location_rejected():
    with pytest.raises(ValidationError, match="'bbox' is not supported"):
        PedoCoverageInput(location_type="bbox", bbox=[-72, 45, -71, 46])


@pytest.mark.unit
def test_bbox_rejection_is_french_by_default():
    with agri_i18n.use_locale("fr"):
        with pytest.raises(ValidationError) as excinfo:
            PedoCoverageInput(location_type="bbox")

    assert "bbox" in str(excinfo.value)
    assert "is not supported" not in str(excinfo.value)


@pytest.mark.unit
def test_missing_polygon_rejected():
    with pytest.raises(ValidationError, match="'polygon' must be provided"):
        SomFieldMatchInput(location_type="polygon")


@pytest.mark.unit
def test_point_out_of_range_rejected():
    with pytest.raises(ValidationError, match="Latitude 95.0 out of range"):
        SomFieldMatchInput(location_type="point", point=[-72.0, 95.0])


@pytest.mark.unit
@pytest.mark.parametrize(
    ("model", "field", "value"),
    [
        (WaterDistanceInput, "max_distance_m", 0),
        (WaterDistanceInput, "max_distance_m", 250_000),
        (PedoCoverageInput, "min_described_pct", -1),
        (PedoCoverageInput, "min_described_pct", 120),
        (SomFieldMatchInput, "tolerance_m", -1),
        (SomFieldMatchInput, "tolerance_m", 1000),
    ],
)
def test_optional_input_out_of_range_rejected(model, field, value):
    with pytest.raises(ValidationError, match=field):
        model(location_type="polygon", polygon=_SQUARE, **{field: value})


@pytest.mark.unit
@pytest.mark.parametrize(
    ("model", "field", "value"),
    [
        (WaterDistanceInput, "max_distance_m", 100_000),
        (PedoCoverageInput, "min_described_pct", 0),
        (PedoCoverageInput, "min_described_pct", 100),
        (SomFieldMatchInput, "tolerance_m", 0),
        (SomFieldMatchInput, "tolerance_m", 500),
    ],
)
def test_optional_input_bounds_accepted(model, field, value):
    validated = model(location_type="polygon", polygon=_SQUARE, **{field: value})

    assert getattr(validated, field) == value


# ---------------------------------------------------------------------------
# prepare_geometry
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_point_becomes_geojson_point():
    location = SomFieldMatchInput(location_type="point", point=[-72.0, 45.0])

    assert prepare_geometry(location) == {
        "type": "Point",
        "coordinates": [-72.0, 45.0],
    }


@pytest.mark.unit
def test_valid_polygon_unchanged():
    location = WaterDistanceInput(location_type="polygon", polygon=_SQUARE)

    assert shape(prepare_geometry(location)).equals(shape(_SQUARE))


@pytest.mark.unit
def test_bow_tie_polygon_repaired():
    location = WaterDistanceInput(location_type="polygon", polygon=_BOW_TIE)

    repaired = shape(prepare_geometry(location))

    assert repaired.is_valid
    assert repaired.geom_type in {"Polygon", "MultiPolygon"}
    assert repaired.area > 0


@pytest.mark.unit
def test_collapsed_polygon_rejected():
    location = WaterDistanceInput(location_type="polygon", polygon=_COLLAPSED)

    with pytest.raises(ProcessorExecuteError, match="invalid or empty"):
        prepare_geometry(location)


@pytest.mark.unit
def test_unparsable_geometry_rejected():
    location = WaterDistanceInput(
        location_type="polygon", polygon={"type": "Polygon", "coordinates": "x"}
    )

    with pytest.raises(ProcessorExecuteError, match="Invalid GeoJSON geometry"):
        prepare_geometry(location)


@pytest.mark.unit
@pytest.mark.parametrize(
    "geometry",
    [
        {"type": "LineString", "coordinates": [[-72.0, 45.0], [-71.99, 45.01]]},
        {"type": "Point", "coordinates": [-72.0, 45.0]},
    ],
)
def test_non_polygonal_geometry_rejected(geometry):
    location = PedoCoverageInput(location_type="polygon", polygon=geometry)

    with pytest.raises(ProcessorExecuteError, match="Polygon or MultiPolygon"):
        prepare_geometry(location)


@pytest.mark.unit
def test_non_polygonal_geometry_rejection_is_french_by_default():
    location = PedoCoverageInput(
        location_type="polygon",
        polygon={"type": "LineString", "coordinates": [[-72.0, 45.0], [-71.99, 45.01]]},
    )

    with agri_i18n.use_locale("fr"):
        with pytest.raises(ProcessorExecuteError) as excinfo:
            prepare_geometry(location)

    assert "Géométrie invalide" in str(excinfo.value)


@pytest.mark.mocked
def test_non_polygonal_farm_geometry_rejected():
    location = PedoCoverageInput(location_type="farm_id", farm_id="42")

    with patch(
        "processes.spatial_backend.geometry.get_geometry_from_db",
        return_value={"type": "Point", "coordinates": [-72.0, 45.0]},
    ):
        with pytest.raises(ProcessorExecuteError, match="Polygon or MultiPolygon"):
            prepare_geometry(location)


@pytest.mark.mocked
def test_farm_geometry_looked_up_and_repaired():
    location = PedoCoverageInput(location_type="farm_id", farm_id="42")

    with patch(
        "processes.spatial_backend.geometry.get_geometry_from_db",
        return_value=_BOW_TIE,
    ) as lookup:
        repaired = shape(prepare_geometry(location))

    lookup.assert_called_once_with("42")
    assert repaired.is_valid
