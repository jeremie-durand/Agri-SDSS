"""Unit tests for eo_sentinel_fetch_metadata.PROCESS_METADATA.

Imports directly from eo_sentinel_fetch_metadata (not via SentinelFetchProcessor)
to give the module its own coverage line.
"""

import pytest
from eo_sentinel_fetch_metadata import PROCESS_METADATA


@pytest.mark.unit
def test_metadata_is_dict():
    assert isinstance(PROCESS_METADATA, dict)


@pytest.mark.unit
def test_required_top_level_keys():
    required = {
        "version",
        "id",
        "title",
        "description",
        "keywords",
        "jobControlOptions",
        "inputs",
        "outputs",
        "example",
    }
    assert required.issubset(PROCESS_METADATA.keys())


@pytest.mark.unit
def test_id_is_sentinel_fetch():
    assert PROCESS_METADATA["id"] == "sentinel-fetch"


@pytest.mark.unit
def test_job_control_options_sync():
    assert "sync-execute" in PROCESS_METADATA["jobControlOptions"]


@pytest.mark.unit
def test_all_six_inputs_present():
    expected = {
        "farm_geometry",
        "farm_id",
        "temporal_extent",
        "output_products",
        "aggregation_method",
        "cloud_cover_max",
    }
    assert expected == set(PROCESS_METADATA["inputs"].keys())


@pytest.mark.unit
def test_temporal_extent_required_and_array():
    schema = PROCESS_METADATA["inputs"]["temporal_extent"]["schema"]
    assert schema["type"] == "array"
    assert schema["minItems"] == 2
    assert schema["maxItems"] == 2
    assert PROCESS_METADATA["inputs"]["temporal_extent"]["minOccurs"] == 1


@pytest.mark.unit
def test_output_products_enum_values():
    items_schema = PROCESS_METADATA["inputs"]["output_products"]["schema"]["items"]
    enum_values = set(items_schema["enum"])
    assert enum_values == {"raw_bands", "ndvi", "evi", "savi", "true_color"}


@pytest.mark.unit
def test_aggregation_method_enum_values():
    schema = PROCESS_METADATA["inputs"]["aggregation_method"]["schema"]
    assert set(schema["enum"]) == {"median", "max", "min", "mean"}


@pytest.mark.unit
def test_cloud_cover_max_range():
    schema = PROCESS_METADATA["inputs"]["cloud_cover_max"]["schema"]
    assert schema["minimum"] == 0
    assert schema["maximum"] == 100


@pytest.mark.unit
def test_outputs_result_schema_properties():
    props = PROCESS_METADATA["outputs"]["result"]["schema"]["properties"]
    expected = {"stac_item_id", "assets", "preview_url", "bbox", "temporal_extent"}
    assert expected.issubset(props.keys())


@pytest.mark.unit
def test_example_has_valid_farm_id():
    farm_id = PROCESS_METADATA["example"]["inputs"]["farm_id"]
    assert isinstance(farm_id, int)


@pytest.mark.unit
def test_bilingual_title_and_description():
    assert "en" in PROCESS_METADATA["title"]
    assert "fr" in PROCESS_METADATA["title"]
    assert "en" in PROCESS_METADATA["description"]
    assert "fr" in PROCESS_METADATA["description"]
