import pytest
from tools.quebec_zones import bbox_for_region


@pytest.mark.unit
class TestBboxForRegion:
    def test_returns_bbox_string_for_known_region(self):
        result = bbox_for_region("estrie")
        assert result == "-72.5,45.0,-71.0,45.8"

    def test_case_insensitive(self):
        assert bbox_for_region("Estrie") == bbox_for_region("estrie")
        assert bbox_for_region("ESTRIE") == bbox_for_region("estrie")

    def test_strips_whitespace(self):
        assert bbox_for_region("  estrie  ") == bbox_for_region("estrie")

    def test_raises_for_unknown_region(self):
        with pytest.raises(ValueError, match="Unknown region 'atlantis'"):
            bbox_for_region("atlantis")

    def test_error_message_lists_known_regions(self):
        with pytest.raises(ValueError, match="estrie"):
            bbox_for_region("unknown")

    @pytest.mark.parametrize(
        "region", ["estrie", "montérégie", "chaudière-appalaches", "bas-saint-laurent"]
    )
    def test_all_defined_regions_resolve(self, region: str):
        result = bbox_for_region(region)
        assert isinstance(result, str)
        assert result.count(",") == 3
