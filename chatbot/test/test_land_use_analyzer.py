import pytest
from tools.land_use_analyzer import LandUseHistory, merge_land_use


@pytest.mark.unit
class TestMergeLandUse:
    def setup_method(self):
        self.parcel = {"id": "parcel-1"}

    def test_returns_land_use_history(self):
        result = merge_land_use([], self.parcel)
        assert isinstance(result, LandUseHistory)

    def test_parcel_id_from_parcel(self):
        result = merge_land_use([], {"id": "abc-123"})
        assert result.parcel_id == "abc-123"

    def test_parcel_id_unknown_when_missing(self):
        result = merge_land_use([], {})
        assert result.parcel_id == "unknown"

    def test_empty_stac_items_yields_empty_history(self):
        result = merge_land_use([], self.parcel)
        assert result.years == []
        assert result.land_uses == []

    def test_extracts_year_from_iso_datetime(self):
        items = [
            {"properties": {"datetime": "2023-06-15T00:00:00Z", "land_use": "corn"}}
        ]
        result = merge_land_use(items, self.parcel)
        assert result.years == [2023]

    def test_extracts_year_from_date_only(self):
        items = [{"properties": {"datetime": "2021-01-01", "land_use": "soy"}}]
        result = merge_land_use(items, self.parcel)
        assert result.years == [2021]

    def test_extracts_year_from_datetime_with_offset(self):
        items = [
            {
                "properties": {
                    "datetime": "2022-03-10T12:00:00+05:00",
                    "land_use": "wheat",
                }
            }
        ]
        result = merge_land_use(items, self.parcel)
        assert result.years == [2022]

    def test_extracts_land_use(self):
        items = [{"properties": {"datetime": "2023-01-01", "land_use": "corn"}}]
        result = merge_land_use(items, self.parcel)
        assert result.land_uses == ["corn"]

    def test_missing_land_use_defaults_to_unknown(self):
        items = [{"properties": {"datetime": "2023-01-01"}}]
        result = merge_land_use(items, self.parcel)
        assert result.land_uses == ["unknown"]

    def test_skips_items_without_datetime(self):
        items = [{"properties": {"land_use": "corn"}}]
        result = merge_land_use(items, self.parcel)
        assert result.years == []
        assert result.land_uses == []

    def test_multiple_items(self):
        items = [
            {"properties": {"datetime": "2021-05-01", "land_use": "soy"}},
            {"properties": {"datetime": "2022-05-01", "land_use": "corn"}},
            {"properties": {"datetime": "2023-05-01", "land_use": "wheat"}},
        ]
        result = merge_land_use(items, self.parcel)
        assert result.years == [2021, 2022, 2023]
        assert result.land_uses == ["soy", "corn", "wheat"]
