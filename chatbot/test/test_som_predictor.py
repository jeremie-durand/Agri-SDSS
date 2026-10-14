import pytest
from tools.som_predictor import SomPrediction, enrich_som


@pytest.mark.unit
class TestEnrichSom:
    def test_returns_som_prediction(self):
        result = enrich_som({}, 45.0, -72.0, "corn")
        assert isinstance(result, SomPrediction)

    def test_passes_lat_lon_land_use(self):
        result = enrich_som({}, 45.5, -71.5, "soy")
        assert result.lat == 45.5
        assert result.lon == -71.5
        assert result.land_use == "soy"

    def test_extracts_value_from_raw(self):
        result = enrich_som({"value": 3.7}, 45.0, -72.0, "corn")
        assert result.som_value == 3.7

    def test_extracts_unit_from_raw(self):
        result = enrich_som({"unit": "mg/kg"}, 45.0, -72.0, "corn")
        assert result.unit == "mg/kg"

    def test_default_value_when_missing(self):
        result = enrich_som({}, 45.0, -72.0, "corn")
        assert result.som_value == 0.0

    def test_default_unit_when_missing(self):
        result = enrich_som({}, 45.0, -72.0, "corn")
        assert result.unit == "g/kg"
