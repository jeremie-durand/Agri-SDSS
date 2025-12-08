import logging
from datetime import date, datetime, timezone
from types import SimpleNamespace
from unittest.mock import Mock, patch

import geopandas as gpd
import numpy as np
import pytest
import rasterio
from pipeline.config import Config
from pipeline.mapping import DefaultMetadata
from pipeline.modules.processing.processing_stac import (
    StacApiClient,
    StacApiResponse,
    _clean_metadata,
    _create_stac_item_from_raster,
    _ensure_datetime_with_tz,
    _extract_datetime_from_sources,
    _parse_xml_metadata,
    build_stac_collection_from_items,
    build_stac_items_from_cog,
    validate_stac,
)
from pydantic import ValidationError
from pystac import Collection, Extent, Item, SpatialExtent, TemporalExtent
from requests import RequestException, Session
from shapely.geometry import Point, mapping


# ------------------------------------------
# Fixtures
# ------------------------------------------
@pytest.fixture
def sample_datetime_aware():
    """Sample timezone-aware datetime."""
    return datetime(2024, 1, 15, 12, 30, 45, tzinfo=timezone.utc)


@pytest.fixture
def sample_datetime_naive():
    """Sample timezone-naive datetime."""
    return datetime(2024, 1, 15, 12, 30, 45)


@pytest.fixture
def temp_aux_xml(tmp_path):
    """Create a temporary aux.xml file for testing."""
    aux_content = """<?xml version="1.0" encoding="UTF-8"?>
<PAMDataset>
    <PAMRasterBand band="1">
        <Description>Red Band</Description>
    </PAMRasterBand>
    <PAMRasterBand band="2">
        <Description>Green Band</Description>
    </PAMRasterBand>
    <PAMRasterBand band="3">
        <Description>Blue Band</Description>
    </PAMRasterBand>
</PAMDataset>"""

    aux_path = tmp_path / "test.tif.aux.xml"
    aux_path.write_text(aux_content)
    return aux_path


@pytest.fixture
def temp_raster_file(tmp_path):
    """Create a temporary raster file for testing."""
    raster_path = tmp_path / "test_raster.tif"

    # Create a simple in-memory raster using rasterio
    import numpy as np
    from rasterio.transform import from_bounds

    # Create sample data
    width, height = 10, 10
    data = np.random.randint(0, 255, (3, height, width), dtype=np.uint8)

    # Define bounds and transform
    bounds = [-1, -1, 1, 1]  # minx, miny, maxx, maxy
    transform = from_bounds(*bounds, width, height)

    # Write raster file
    with rasterio.open(
        raster_path,
        "w",
        driver="GTiff",
        height=height,
        width=width,
        count=3,
        dtype=rasterio.uint8,
        crs="EPSG:4326",
        transform=transform,
    ) as dst:
        dst.write(data)

    return raster_path


@pytest.fixture
def sample_vector_row():
    """Sample vector row data for STAC item creation."""
    return {
        "geometry": Point(0, 0),
        "metadata": {"source": "test", "type": "sample"},
        "datetime": datetime(2024, 1, 1, tzinfo=timezone.utc),
        "file_url": "/test/data.shp",
    }


@pytest.fixture
def sample_gdf():
    """Sample GeoDataFrame for testing."""
    return gpd.GeoDataFrame(
        {
            "gid": [1, 2, 3],
            "name": ["Feature A", "Feature B", "Feature C"],
            "datetime": [
                datetime(2024, 1, 1, tzinfo=timezone.utc),
                datetime(2024, 2, 1, tzinfo=timezone.utc),
                datetime(2024, 3, 1, tzinfo=timezone.utc),
            ],
            "metadata": [{"type": "A"}, {"type": "B"}, {"type": "C"}],
            "file_url": ["/data/a.shp", "/data/b.shp", "/data/c.shp"],
            "geometry": [Point(0, 0), Point(1, 1), Point(2, 2)],
        },
        crs="EPSG:4326",
    )


@pytest.fixture
def sample_stac_items():
    """Sample STAC items for collection creation."""
    items = []
    for i in range(3):
        item = Item(
            id=f"item_{i}",
            geometry=mapping(Point(i, i)),
            bbox=[i - 0.5, i - 0.5, i + 0.5, i + 0.5],
            datetime=datetime(2024, 1, i + 1, tzinfo=timezone.utc),
            properties={"index": i},
        )
        items.append(item)
    return items


@pytest.fixture
def sample_stac_items_no_bbox():
    """Sample STAC item without bbox for testing."""
    items = []
    for i in range(3):
        item = Item(
            id=f"item_{i}",
            geometry=mapping(Point(i, i)),
            bbox=None,
            datetime=datetime(2024, 1, i + 1, tzinfo=timezone.utc),
            properties={"index": i},
        )
        items.append(item)
    return items


@pytest.fixture
def mock_logger():
    """Mock logger for testing."""
    logger = Mock(spec=logging.Logger)
    logger.info = Mock()
    logger.error = Mock()
    logger.exception = Mock()
    return logger


@pytest.fixture
def sample_collection():
    """Sample STAC collection for testing."""
    spatial_extent = SpatialExtent([[-1, -1, 1, 1]])
    temporal_extent = TemporalExtent(
        [
            [
                datetime(2024, 1, 1, tzinfo=timezone.utc),
                datetime(2024, 12, 31, tzinfo=timezone.utc),
            ]
        ]
    )
    extent = Extent(spatial=spatial_extent, temporal=temporal_extent)

    return Collection(
        id="test_collection",
        description="Test collection for unit tests",
        extent=extent,
        title="Test Collection",
    )


@pytest.fixture
def sample_items():
    """Sample STAC items for testing."""
    items = []
    for i in range(2):
        item = Item(
            id=f"test_item_{i}",
            geometry=mapping(Point(i, i)),
            bbox=[i - 0.5, i - 0.5, i + 0.5, i + 0.5],
            datetime=datetime(2024, 1, i + 1, tzinfo=timezone.utc),
            properties={"test_prop": f"value_{i}"},
        )
        items.append(item)
    return items


@pytest.fixture
def stac_api_client(mock_logger, sample_collection, sample_items, stac_api_url_fixture):
    """StacApiClient instance for testing."""
    return StacApiClient(
        api_url=stac_api_url_fixture,
        collection_id="test_collection",
        stac_collection=sample_collection,
        stac_items=sample_items,
        retries=2,
        backoff_factor=0.1,
        logger=mock_logger,
    )


# ------------------------------------------
# Test cases for _ensure_datetime_with_tz()
# ------------------------------------------
def test_ensure_datetime_with_tz_string_input():
    """Test _ensure_datetime_with_tz with string input."""
    result = _ensure_datetime_with_tz(dt="2024-01-15T12:30:45Z")

    assert isinstance(result, datetime)
    assert result.tzinfo is not None
    assert result.year == 2024
    assert result.month == 1
    assert result.day == 15


def test_ensure_datetime_with_tz_naive_datetime_input(sample_datetime_naive):
    """Test _ensure_datetime_with_tz with naive datetime input."""
    result = _ensure_datetime_with_tz(dt=sample_datetime_naive)

    assert isinstance(result, datetime)
    assert result.tzinfo == timezone.utc
    assert result.year == 2024
    assert result.month == 1
    assert result.day == 15


def test_ensure_datetime_with_tz_aware_datetime_input(sample_datetime_aware):
    """Test _ensure_datetime_with_tz with timezone-aware datetime input."""
    result = _ensure_datetime_with_tz(dt=sample_datetime_aware)

    assert result == sample_datetime_aware


def test_ensure_datetime_with_tz_invalid_type():
    """Test _ensure_datetime_with_tz with invalid input type."""
    result = _ensure_datetime_with_tz(dt=12345)  # Invalid type

    assert result is None


@pytest.mark.parametrize(
    "date_string,expected_year,expected_month,expected_day",
    [
        ("2024-01-15", 2024, 1, 15),
        ("2023-12-31T23:59:59Z", 2023, 12, 31),
        ("2022-06-15T12:30:00+00:00", 2022, 6, 15),
        ("January 15, 2024", 2024, 1, 15),
    ],
)
def test_ensure_datetime_with_tz_various_string_formats(
    date_string, expected_year, expected_month, expected_day
):
    """Parametrized test for various date string formats."""
    result = _ensure_datetime_with_tz(dt=date_string)

    assert result.year == expected_year
    assert result.month == expected_month
    assert result.day == expected_day
    assert result.tzinfo is not None


# ------------------------------------------
# Test cases for _clean_metadata()
# ------------------------------------------
def test_clean_metadata_simple_types():
    """Test _clean_metadata with simple native types."""
    obj = {"a": "b", "n": 5, "flag": True, "none": None}
    result = _clean_metadata(obj)
    assert result == obj


def test_clean_metadata_numpy_scalars_and_nested():
    """Test _clean_metadata converts numpy scalars to native types, including nested structures."""
    obj = {
        "f": np.float64(1.5),
        "i": np.int32(7),
        "lst": [np.float64(2.0), {"inner": np.int64(3)}],
    }

    result = _clean_metadata(obj)
    assert isinstance(result["f"], float) and result["f"] == 1.5
    assert isinstance(result["i"], int) and result["i"] == 7
    assert isinstance(result["lst"][0], float) and result["lst"][0] == 2.0
    assert result["lst"][1]["inner"] == 3


def test_clean_metadata_nan_and_inf_become_none():
    """Test _clean_metadata converts NaN and Inf to None."""
    obj = {"nan": float("nan"), "inf": float("inf"), "ninf": float("-inf")}
    # include numpy versions as well
    obj_np = {"nan_np": np.float64(np.nan), "inf_np": np.float64(np.inf)}

    res = _clean_metadata(obj)
    res_np = _clean_metadata(obj_np)

    assert res["nan"] is None
    assert res["inf"] is None
    assert res["ninf"] is None

    assert res_np["nan_np"] is None
    assert res_np["inf_np"] is None


def test_clean_metadata_dates_and_datetimes():
    """Test _clean_metadata converts date and datetime objects to ISO strings."""
    d = date(2024, 1, 15)
    dt_aware = datetime(2024, 1, 15, 12, 30, 45, tzinfo=timezone.utc)
    dt_naive = datetime(2024, 1, 15, 12, 30, 45)

    obj = {"d": d, "dt_aware": dt_aware, "dt_naive": dt_naive}
    res = _clean_metadata(obj)

    assert res["d"] == "2024-01-15"
    # aware should be suffixed with Z
    assert res["dt_aware"].endswith("Z")
    assert res["dt_aware"].startswith("2024-01-15T12:30:45")
    # naive datetime isoformat has no timezone marker; ensure isoformat string returned
    assert res["dt_naive"].startswith("2024-01-15T12:30:45")


def test_clean_metadata_preserves_other_types_and_structure():
    """Test _clean_metadata preserves other types and nested structures."""
    obj = {
        "mixed": [
            {"a": np.int64(10)},
            datetime(2024, 1, 1, tzinfo=timezone.utc),
            "text",
            False,
        ]
    }

    res = _clean_metadata(obj)
    assert res["mixed"][0]["a"] == 10
    assert isinstance(res["mixed"][0]["a"], int)
    assert res["mixed"][1].endswith("Z")
    assert res["mixed"][2] == "text"
    assert res["mixed"][3] is False


# ------------------------------------------
# Test cases for _parse_xml_metadata()
# ------------------------------------------
def test_parse_xml_metadata_file_not_exist(tmp_path):
    """Non-existent file -> returns DefaultMetadata defaults."""
    xml_path = tmp_path / "does_not_exist.aux.xml"

    result = _parse_xml_metadata(xml_path)
    assert result == DefaultMetadata.get_defaults()


def test_parse_xml_metadata_path_not_file(tmp_path):
    """Path exists but is not a file (directory) -> returns defaults."""
    dir_path = tmp_path / "some_dir"
    dir_path.mkdir()

    result = _parse_xml_metadata(dir_path)
    assert result == DefaultMetadata.get_defaults()


def test_parse_xml_metadata_invalid_xml(tmp_path):
    """Malformed XML -> returns defaults."""
    xml_path = tmp_path / "bad.aux.xml"
    xml_path.write_text("<PAMDataset><PAMRasterBand></PAMDataset")  # malformed

    result = _parse_xml_metadata(xml_path)
    assert result == DefaultMetadata.get_defaults()


def test_parse_xml_metadata_no_bands_returns_defaults(tmp_path):
    """Valid XML but no PAMRasterBand elements -> returns defaults."""
    xml_path = tmp_path / "empty.aux.xml"
    xml_path.write_text(
        """<?xml version="1.0"?>
    <PAMDataset>
    </PAMDataset>"""
    )

    result = _parse_xml_metadata(xml_path)
    assert result == DefaultMetadata.get_defaults()


def test_parse_xml_metadata_extracts_band_descriptions(tmp_path):
    """Valid aux.xml with PAMRasterBand descriptions -> returns dict with band descriptions."""
    xml_path = tmp_path / "test.tif.aux.xml"
    content = """<?xml version="1.0" encoding="UTF-8"?>
    <PAMDataset>
        <PAMRasterBand band="1">
            <Description>Red Band</Description>
        </PAMRasterBand>
        <PAMRasterBand band="2">
            <Description>Green Band</Description>
        </PAMRasterBand>
        <PAMRasterBand band="3">
            <Description>Blue Band</Description>
        </PAMRasterBand>
    </PAMDataset>"""
    xml_path.write_text(content)

    result = _parse_xml_metadata(xml_path)
    assert isinstance(result, dict)
    assert result["band_1_description"] == "Red Band"
    assert result["band_2_description"] == "Green Band"
    assert result["band_3_description"] == "Blue Band"


def test_parse_xml_metadata_permission_error_returns_defaults(tmp_path):
    """If ET.parse raises PermissionError -> returns defaults."""
    xml_path = tmp_path / "test.tif.aux.xml"
    xml_path.write_text("irrelevant")

    with patch(
        "pipeline.modules.processing.processing_stac.ET.parse",
        side_effect=PermissionError("denied"),
    ):
        result = _parse_xml_metadata(xml_path)
        assert result == DefaultMetadata.get_defaults()


# ------------------------------------------
# Test cases for _extract_datetime_from_sources()
# ------------------------------------------
def test_extract_datetime_from_metadata_nested_string_value():
    """A shallow nested string value that parses as a date/time is accepted."""
    meta = {"other": "2024-01-10"}
    res = _extract_datetime_from_sources(metadata=meta, filename=None)
    assert isinstance(res, datetime)
    assert res == datetime(2024, 1, 10, 0, 0, 0, tzinfo=timezone.utc)


def test_extract_datetime_from_metadata_nested_date_object():
    """A shallow nested date object is converted to midnight UTC."""
    meta = {"x": date(2024, 2, 5)}
    res = _extract_datetime_from_sources(metadata=meta, filename=None)
    assert isinstance(res, datetime)
    assert res == datetime(2024, 2, 5, 0, 0, 0, tzinfo=timezone.utc)


@pytest.mark.parametrize(
    "filename,expected_dt",
    [
        (
            "IMG_20240115T123045.tif",
            datetime(2024, 1, 15, 12, 30, 45, tzinfo=timezone.utc),
        ),
        (
            "IMG_20240115_123045.tif",
            datetime(2024, 1, 15, 12, 30, 45, tzinfo=timezone.utc),
        ),
        ("IMG_20240115.tif", datetime(2024, 1, 15, 0, 0, 0, tzinfo=timezone.utc)),
        ("file_2023_extra.tif", datetime(2023, 1, 1, 0, 0, 0, tzinfo=timezone.utc)),
    ],
)
def test_extract_datetime_from_filename_patterns(filename, expected_dt):
    """Filename patterns (ymdhms, ymd, year) are parsed into UTC datetimes."""
    res = _extract_datetime_from_sources(metadata=None, filename=filename)
    assert isinstance(res, datetime)
    # normalize to UTC for comparison
    if res.tzinfo is None:
        res = res.replace(tzinfo=timezone.utc)
    else:
        res = res.astimezone(timezone.utc)
    assert res == expected_dt


def test_extract_datetime_returns_none_when_no_sources():
    """If neither metadata nor filename yield a datetime the function returns default datetime."""
    res = _extract_datetime_from_sources(metadata=None, filename=None)
    assert res == Config.DEFAULT_DATETIME


# ------------------------------------------
# Test cases for _create_stac_item_from_raster()
# ------------------------------------------
def test_create_stac_item_from_raster_valid_input(tmp_path):
    """Valid raster dict should produce a pystac.Item with expected properties and asset."""
    raster_dict = {
        "geometry": mapping(Point(1, 2)),
        "bbox": [1.0, 2.0, 1.0, 2.0],
        "datetime": "2024-01-15T12:00:00Z",
        "properties": {"sensor": "test-sensor"},
        "file_url": "/tmp/test_raster.tif",
    }

    fake_dt = datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
    with patch(
        "pipeline.modules.processing.processing_stac._ensure_datetime_with_tz",
        return_value=fake_dt,
    ):
        item = _create_stac_item_from_raster(
            raster_dict=raster_dict, unique_id="raster_1", asset_key="data"
        )

    assert isinstance(item, Item)
    assert item.id == "raster_1"
    # properties contain automatic fields
    assert item.properties["title"] == "raster_1"
    assert item.properties["data_type"] == "raster"
    assert item.properties["source"] == "cog_processing"
    # the provided property was preserved (after cleaning)
    assert item.properties["sensor"] == "test-sensor"
    # asset added
    assert "data" in item.assets
    assert item.assets["data"].href == "/tmp/test_raster.tif"
    assert item.assets["data"].media_type.startswith("image/tiff")


def test_create_stac_item_from_raster_missing_geometry_raises():
    """Missing geometry must raise ValueError."""
    raster_dict = {
        "bbox": [0, 0, 1, 1],
        "properties": {},
    }

    with pytest.raises(ValueError, match="geometry"):
        _create_stac_item_from_raster(raster_dict=raster_dict, unique_id="no_geom")


def test_create_stac_item_from_raster_missing_bbox_raises():
    """Missing bbox must raise ValueError."""
    raster_dict = {
        "geometry": mapping(Point(0, 0)),
        "properties": {},
    }

    with pytest.raises(ValueError, match="bbox"):
        _create_stac_item_from_raster(raster_dict=raster_dict, unique_id="no_bbox")


def test_create_stac_item_from_raster_uses_provided_metadata_and_not_parse_aux(
    tmp_path,
):
    """If 'metadata' key is present, _parse_xml_metadata should not be called."""
    raster_dict = {
        "geometry": mapping(Point(0, 0)),
        "bbox": [0.0, 0.0, 0.0, 0.0],
        "properties": {"existing": "value"},
        "metadata": {"from_meta": "yes"},
        "datetime": "2024-01-15T12:00:00Z",
    }

    with patch(
        "pipeline.modules.processing.processing_stac._parse_xml_metadata"
    ) as mock_parse:
        item = _create_stac_item_from_raster(
            raster_dict=raster_dict, unique_id="with_meta"
        )
        # parse should not be called because metadata was provided directly
        mock_parse.assert_not_called()

    assert item.properties["from_meta"] == "yes"
    assert item.properties["existing"] == "value"


def test_create_stac_item_from_raster_falls_back_to_aux_parse(tmp_path):
    """When metadata absent but file_url present, _parse_xml_metadata is used to enrich properties."""
    aux_result = {"band_1_description": "Red"}
    raster_file = tmp_path / "test_r.tif"
    raster_file.write_text("dummy")
    raster_dict = {
        "geometry": mapping(Point(5, 6)),
        "bbox": [5.0, 6.0, 5.0, 6.0],
        "properties": {"sensor": "s"},
        "file_url": str(raster_file),
        "datetime": "2024-01-15T12:00:00Z",
    }

    with patch(
        "pipeline.modules.processing.processing_stac._parse_xml_metadata",
        return_value=aux_result,
    ) as mock_parse:
        item = _create_stac_item_from_raster(
            raster_dict=raster_dict, unique_id="aux_test"
        )
        mock_parse.assert_called_once()
    # aux metadata merged into properties
    assert item.properties.get("band_1_description") == "Red"
    assert item.assets["data"].href == str(raster_file)


# ------------------------------------------
# Test cases for build_stac_items_from_cog()
# ------------------------------------------
def _make_item(uid: str) -> Item:
    """Helper to create a minimal pystac.Item for tests."""
    return Item(
        id=uid,
        geometry=mapping(Point(0, 0)),
        bbox=[0.0, 0.0, 0.0, 0.0],
        datetime=datetime(2024, 1, 1, tzinfo=timezone.utc),
        properties={},
    )


def test_build_stac_items_from_cog_success():
    """Should build items for a list of valid raster metadata dicts."""
    raster_list = [
        {
            "id": "r1",
            "geometry": mapping(Point(1, 1)),
            "bbox": [1, 1, 1, 1],
            "datetime": "2024-01-01T00:00:00Z",
        },
        {
            "id": "r2",
            "geometry": mapping(Point(2, 2)),
            "bbox": [2, 2, 2, 2],
            "datetime": "2024-01-02T00:00:00Z",
        },
    ]

    with patch(
        "pipeline.modules.processing.processing_stac._create_stac_item_from_raster"
    ) as mock_create, patch(
        "pipeline.modules.processing.processing_stac.validate_stac"
    ) as mock_validate:
        mock_create.side_effect = [_make_item("r1"), _make_item("r2")]

        items = build_stac_items_from_cog(
            raster_metadata_list=raster_list, source_name="MySource"
        )

        assert len(items) == 2
        # properties should include source and data_type set by builder
        assert all(item.properties.get("source") == "MySource" for item in items)
        assert all(item.properties.get("data_type") == "raster" for item in items)
        # validate_stac called once per created item
        assert mock_validate.call_count == 2


def test_build_stac_items_from_cog_skips_non_dict_entry_and_continues():
    """Non-dict entries are skipped (logged) and valid ones are created."""
    raster_list = [
        "not_a_dict",
        {
            "id": "ok",
            "geometry": mapping(Point(3, 3)),
            "bbox": [3, 3, 3, 3],
            "datetime": "2024-01-03T00:00:00Z",
        },
    ]

    with patch(
        "pipeline.modules.processing.processing_stac._create_stac_item_from_raster"
    ) as mock_create, patch(
        "pipeline.modules.processing.processing_stac.validate_stac"
    ) as mock_validate:
        mock_create.return_value = _make_item("ok")

        items = build_stac_items_from_cog(
            raster_metadata_list=raster_list, source_name="Src"
        )

        assert len(items) == 1
        assert items[0].id == "ok"
        assert mock_validate.call_count == 1


def test_build_stac_items_from_cog_all_failures_raises_runtimeerror():
    """If no items are created and all entries error, a RuntimeError is raised."""
    raster_list = [
        {
            "id": "a",
            "geometry": mapping(Point(0, 0)),
            "bbox": [0, 0, 0, 0],
            "datetime": "2024-01-01T00:00:00Z",
        },
        {
            "id": "b",
            "geometry": mapping(Point(1, 1)),
            "bbox": [1, 1, 1, 1],
            "datetime": "2024-01-02T00:00:00Z",
        },
    ]

    with patch(
        "pipeline.modules.processing.processing_stac._create_stac_item_from_raster",
        side_effect=ValueError("boom"),
    ):
        with pytest.raises(RuntimeError, match="Failed to create any STAC items"):
            build_stac_items_from_cog(
                raster_metadata_list=raster_list, source_name="Src"
            )


def test_build_stac_items_from_cog_partial_failure_logs_warning(mock_logger):
    """When some items fail and some succeed, a warning is logged and successful items returned."""
    raster_list = [
        {
            "id": "good",
            "geometry": mapping(Point(4, 4)),
            "bbox": [4, 4, 4, 4],
            "datetime": "2024-01-04T00:00:00Z",
        },
        {
            "id": "bad",
            "geometry": mapping(Point(5, 5)),
            "bbox": [5, 5, 5, 5],
            "datetime": "2024-01-05T00:00:00Z",
        },
    ]

    with patch(
        "pipeline.modules.processing.processing_stac._create_stac_item_from_raster"
    ) as mock_create, patch(
        "pipeline.modules.processing.processing_stac.logger"
    ) as mock_log:
        # first call returns item, second raises
        mock_create.side_effect = [_make_item("good"), Exception("create failed")]

        items = build_stac_items_from_cog(
            raster_metadata_list=raster_list, source_name="SrcName"
        )

        # one item created, one error recorded -> function returns items and logs a warning
        assert len(items) == 1
        mock_log.warning.assert_called()


# ------------------------------------------
# Test cases for build_stac_collection_from_items()
# ------------------------------------------
def test_build_stac_collection_from_items_valid_input(sample_stac_items):
    """Test build_stac_collection_from_items with valid items."""
    result = build_stac_collection_from_items(
        items=sample_stac_items, collection_id="test_collection"
    )

    assert isinstance(result, Collection)
    assert result.id == "test_collection"
    assert result.title == "test_collection"
    assert result.description == "A STAC Collection generated from Python"

    # Check spatial extent
    assert result.extent.spatial.bboxes is not None
    assert len(result.extent.spatial.bboxes[0]) == 4

    # Check temporal extent
    assert result.extent.temporal.intervals is not None
    assert len(result.extent.temporal.intervals[0]) == 2


def test_build_stac_collection_from_items_empty_list():
    """Test build_stac_collection_from_items with empty items list."""
    with pytest.raises(ValueError, match="The list of items is empty"):
        build_stac_collection_from_items(items=[], collection_id="empty_collection")


def test_build_stac_collection_from_items_missing_bbox(sample_stac_items_no_bbox):
    """Test build_stac_collection_from_items with item missing bbox."""
    with pytest.raises(ValueError, match="Item .* does not have a valid bbox"):
        build_stac_collection_from_items(
            items=sample_stac_items_no_bbox, collection_id="test_collection"
        )


def test_build_stac_collection_from_items_no_datetime():
    """Test build_stac_collection_from_items with item missing datetime."""
    items = [
        SimpleNamespace(id="item1", bbox=[0.0, 0.0, 1.0, 1.0]),
        SimpleNamespace(id="item2", bbox=[1.0, 1.0, 2.0, 2.0]),
    ]

    with pytest.raises(
        ValueError, match="No datetime found in items to create the collection."
    ):
        build_stac_collection_from_items(items=items, collection_id="test_collection")


def test_build_stac_collection_from_items_single_item(sample_stac_items):
    """Test build_stac_collection_from_items with single item."""
    single_item = [sample_stac_items[0]]
    result = build_stac_collection_from_items(
        items=single_item, collection_id="single_collection"
    )

    assert isinstance(result, Collection)
    assert result.id == "single_collection"

    # Temporal extent should have same start and end
    temporal_interval = result.extent.temporal.intervals[0]
    assert temporal_interval[0] == temporal_interval[1]


def test_build_stac_collection_from_items_spatial_extent_calculation(sample_stac_items):
    """Test that spatial extent is calculated correctly."""
    result = build_stac_collection_from_items(
        items=sample_stac_items, collection_id="spatial_test"
    )

    bbox = result.extent.spatial.bboxes[0]

    # Should encompass all item bboxes
    # Items have bboxes: [-0.5, -0.5, 0.5, 0.5], [0.5, 0.5, 1.5, 1.5], [1.5, 1.5, 2.5, 2.5]
    assert bbox[0] <= -0.5  # min x
    assert bbox[1] <= -0.5  # min y
    assert bbox[2] >= 2.5  # max x
    assert bbox[3] >= 2.5  # max y


def test_build_stac_collection_from_items_temporal_extent_calculation(
    sample_stac_items,
):
    """Test that temporal extent is calculated correctly."""
    result = build_stac_collection_from_items(
        items=sample_stac_items, collection_id="temporal_test"
    )

    temporal_interval = result.extent.temporal.intervals[0]
    start_time = temporal_interval[0]
    end_time = temporal_interval[1]

    # Should span from earliest to latest datetime
    assert start_time <= datetime(2024, 1, 1, tzinfo=timezone.utc)
    assert end_time >= datetime(2024, 1, 3, tzinfo=timezone.utc)


# ------------------------------------------
# Test cases for validate_stac()
# ------------------------------------------
def test_validate_stac_valid_item():
    """Test validate_stac with valid STAC item."""
    valid_item = {
        "type": "Feature",
        "stac_version": "1.0.0",
        "id": "test_item",
        "geometry": {"type": "Point", "coordinates": [0, 0]},
        "bbox": [-1, -1, 1, 1],
        "properties": {"datetime": "2024-01-15T12:00:00Z"},
        "assets": {},
        "links": [],
    }

    # Should not raise exception
    validate_stac(stac_obj=valid_item, stac_type="item")


def test_validate_stac_valid_collection():
    """Test validate_stac with valid STAC collection."""
    valid_collection = {
        "type": "Collection",
        "stac_version": "1.0.0",
        "id": "test_collection",
        "title": "Test Collection",
        "description": "A test collection",
        "license": "proprietary",
        "extent": {
            "spatial": {"bbox": [[-1, -1, 1, 1]]},
            "temporal": {
                "interval": [["2024-01-01T00:00:00Z", "2024-12-31T23:59:59Z"]]
            },
        },
        "links": [],
    }

    # Should not raise exception
    validate_stac(stac_obj=valid_collection, stac_type="collection")


def test_validate_stac_invalid_item():
    """Test validate_stac with invalid STAC item."""
    invalid_item = {
        "type": "Feature",
        # Missing required fields like geometry, properties, etc.
        "id": "test_item",
    }

    with pytest.raises(ValueError, match="STAC item validation error"):
        validate_stac(stac_obj=invalid_item, stac_type="item")


def test_validate_stac_invalid_collection():
    """Test validate_stac with invalid STAC collection."""
    invalid_collection = {
        "type": "Collection",
        # Missing required fields like description, extent, etc.
        "id": "test_collection",
    }

    with pytest.raises(ValueError, match="STAC collection validation error"):
        validate_stac(stac_obj=invalid_collection, stac_type="collection")


def test_validate_stac_invalid_type():
    """Test validate_stac with invalid stac_type parameter."""
    valid_item = {
        "type": "Feature",
        "id": "test_item",
        "geometry": {"type": "Point", "coordinates": [0, 0]},
        "properties": {},
        "stac_version": "1.0.0",
        "links": [],
    }

    with pytest.raises(
        ValueError, match="stac_type must be either 'item' or 'collection'"
    ):
        validate_stac(stac_obj=valid_item, stac_type="invalid_type")


@pytest.mark.parametrize(
    "stac_type,object_type",
    [
        ("item", "item"),
        ("collection", "collection"),
    ],
)
def test_validate_stac_parametrized_types(stac_type, object_type):
    """Parametrized test for different STAC types."""
    if object_type == "item":
        stac_obj = {
            "type": "Feature",
            "stac_version": "1.0.0",
            "id": "test_item",
            "geometry": {"type": "Point", "coordinates": [0, 0]},
            "bbox": [-1, -1, 1, 1],
            "properties": {"datetime": "2024-01-15T12:00:00Z"},
            "assets": {},
            "links": [],
        }
    else:
        stac_obj = {
            "type": "Collection",
            "stac_version": "1.0.0",
            "id": "test_collection",
            "title": "Test Collection",
            "description": "A test collection",
            "license": "proprietary",
            "extent": {
                "spatial": {"bbox": [[-1, -1, 1, 1]]},
                "temporal": {
                    "interval": [["2024-01-01T00:00:00Z", "2024-12-31T23:59:59Z"]]
                },
            },
            "links": [],
        }

    # Should validate successfully
    validate_stac(stac_obj=stac_obj, stac_type=stac_type)


# ------------------------------------------
# Test cases for StacApiResponse Class
# ------------------------------------------
def test_stac_api_response_success_creation():
    """Test creating a successful StacApiResponse."""
    response = StacApiResponse(
        success=True,
        status_code=200,
        message="Operation successful",
        data={"result": "created"},
    )

    assert response.success is True
    assert response.status_code == 200
    assert response.message == "Operation successful"
    assert response.data == {"result": "created"}


def test_stac_api_response_error_creation():
    """Test creating an error StacApiResponse."""
    response = StacApiResponse(
        success=False, status_code=404, message="Resource not found"
    )

    assert response.success is False
    assert response.status_code == 404
    assert response.message == "Resource not found"
    assert response.data is None


def test_stac_api_response_required_fields():
    """Test that required fields are validated."""
    # Missing success field should raise ValidationError
    with pytest.raises(ValidationError):
        StacApiResponse(status_code=200, message="Test message")

    # Missing status_code field should raise ValidationError
    with pytest.raises(ValidationError):
        StacApiResponse(success=True, message="Test message")

    # Missing message field should raise ValidationError
    with pytest.raises(ValidationError):
        StacApiResponse(success=True, status_code=200)


def test_stac_api_response_optional_data():
    """Test that data field is optional."""
    response = StacApiResponse(
        success=True, status_code=200, message="Success without data"
    )

    assert response.data is None


def test_stac_api_response_various_data_types():
    """Test StacApiResponse with different data types."""
    test_cases = [
        {"string_data": "test"},
        ["list", "data"],
        42,
        {"nested": {"complex": "data"}},
        None,
    ]

    for data in test_cases:
        response = StacApiResponse(
            success=True, status_code=200, message="Test", data=data
        )
        assert response.data == data


def test_stac_api_response_field_descriptions():
    """Test that field descriptions are accessible."""
    response = StacApiResponse(success=True, status_code=200, message="Test")

    assert hasattr(response, "success")
    assert hasattr(response, "status_code")
    assert hasattr(response, "message")
    assert hasattr(response, "data")


def test_stac_api_response_json_serialization():
    """Test that StacApiResponse can be serialized to JSON."""
    response = StacApiResponse(
        success=True,
        status_code=201,
        message="Resource created",
        data={"id": "test_123", "created_at": "2024-01-15T12:00:00Z"},
    )

    response_dict = response.model_dump()
    assert response_dict["success"] is True
    assert response_dict["status_code"] == 201
    assert response_dict["message"] == "Resource created"
    assert response_dict["data"]["id"] == "test_123"


@pytest.mark.parametrize(
    "success,status_code,expected_success",
    [
        (True, 200, True),
        (True, 201, True),
        (False, 400, False),
        (False, 404, False),
        (False, 500, False),
    ],
)
def test_stac_api_response_parametrized_status(success, status_code, expected_success):
    """Parametrized test for different success/status combinations."""
    response = StacApiResponse(
        success=success, status_code=status_code, message="Test message"
    )

    assert response.success == expected_success
    assert response.status_code == status_code


def test_stac_api_response_immutability():
    """Test that StacApiResponse fields behave as expected."""
    response = StacApiResponse(
        success=True, status_code=200, message="Original message"
    )

    assert response.success is True
    assert response.message == "Original message"


def test_stac_api_response_model_validation():
    """Test Pydantic model validation."""
    # Test with invalid types
    with pytest.raises(ValidationError):
        StacApiResponse(
            success="not_boolean", status_code=200, message="Test"  # Should be boolean
        )

    with pytest.raises(ValidationError):
        StacApiResponse(
            success=True, status_code="not_integer", message="Test"  # Should be integer
        )

    with pytest.raises(ValidationError):
        StacApiResponse(success=True, status_code=200, message=123)  # Should be string


# ------------------------------------------
# Test cases for StacApiClient Class Initialization
# ------------------------------------------
def test_stac_api_client_initialization(
    mock_logger, sample_collection, sample_items, stac_api_url_fixture
):
    """Test StacApiClient initialization with all parameters."""
    client = StacApiClient(
        api_url=stac_api_url_fixture,
        collection_id="my_collection",
        stac_collection=sample_collection,
        stac_items=sample_items,
        retries=5,
        backoff_factor=0.5,
        logger=mock_logger,
    )

    assert client.api_url == stac_api_url_fixture
    assert client.collection_id == "my_collection"
    assert client.stac_collection == sample_collection
    assert client.stac_items == sample_items
    assert client.logger == mock_logger
    assert isinstance(client.session, Session)


def test_stac_api_client_default_parameters(
    mock_logger, sample_collection, sample_items, stac_api_url_fixture
):
    """Test StacApiClient initialization with default parameters."""
    client = StacApiClient(
        api_url=stac_api_url_fixture,
        collection_id="default_collection",
        stac_collection=sample_collection,
        stac_items=sample_items,
        logger=mock_logger,
    )

    # Check that defaults are applied (retries=3, backoff_factor=0.3)
    assert client.api_url == stac_api_url_fixture
    assert client.collection_id == "default_collection"


def test_stac_api_client_session_configuration(
    sample_collection, sample_items, mock_logger, stac_api_url_fixture
):
    """Test that session is configured with retry strategy."""
    mock_session = Mock()
    mock_retry = Mock()
    mock_adapter = Mock()

    with patch(
        "pipeline.modules.processing.processing_stac.Session"
    ) as mock_session_class:
        with patch(
            "pipeline.modules.processing.processing_stac.Retry"
        ) as mock_retry_class:
            with patch(
                "pipeline.modules.processing.processing_stac.HTTPAdapter"
            ) as mock_adapter_class:

                mock_session_class.return_value = mock_session

                mock_retry_class.return_value = mock_retry

                mock_adapter_class.return_value = mock_adapter

                client = StacApiClient(
                    api_url=stac_api_url_fixture,
                    collection_id="test",
                    stac_collection=sample_collection,
                    stac_items=sample_items,
                    retries=3,
                    backoff_factor=0.3,
                    logger=mock_logger,
                )

                # Check retry configuration
                mock_retry_class.assert_called_once_with(
                    total=3,
                    backoff_factor=0.3,
                    status_forcelist=[500, 502, 503, 504],
                    allowed_methods=["GET", "POST", "DELETE", "PUT"],
                )

                # Check adapter configuration
                mock_adapter_class.assert_called_once_with(max_retries=mock_retry)

                # Check session mount calls
                assert mock_session.mount.call_count == 2
                mock_session.mount.assert_any_call("http://", mock_adapter)
                mock_session.mount.assert_any_call("https://", mock_adapter)
                assert client.session == mock_session


# ------------------------------------------
# Test cases for StacApiClient._request()
# ------------------------------------------
def test_stac_api_client_request_success(stac_api_client):
    """Test _request method with successful response."""
    mock_response = Mock()
    mock_response.ok = True
    mock_response.status_code = 200
    mock_response.text = "Success"
    mock_response.content = b'{"result": "success"}'
    mock_response.json.return_value = {"result": "success"}

    with patch.object(stac_api_client.session, "request", return_value=mock_response):
        result = stac_api_client._request(
            method="GET", endpoint="/test", payload={"test": "data"}
        )

    assert isinstance(result, StacApiResponse)
    assert result.success is True
    assert result.status_code == 200
    assert result.message == "Success"
    assert result.data == {"result": "success"}


def test_stac_api_client_request_error(stac_api_client):
    """Test _request method with error response."""
    mock_response = Mock()
    mock_response.ok = False
    mock_response.status_code = 404
    mock_response.text = "Not Found"
    mock_response.content = b'{"error": "Resource not found"}'
    mock_response.json.return_value = {"error": "Resource not found"}

    with patch.object(stac_api_client.session, "request", return_value=mock_response):
        result = stac_api_client._request(method="GET", endpoint="/nonexistent")

    assert isinstance(result, StacApiResponse)
    assert result.success is False
    assert result.status_code == 404
    assert "Error 404" in result.message
    assert result.data == {"error": "Resource not found"}


def test_stac_api_client_request_network_error(stac_api_client):
    """Test _request method with network error."""
    with patch.object(
        stac_api_client.session,
        "request",
        side_effect=RequestException("Connection failed"),
    ):
        result = stac_api_client._request(
            method="POST", endpoint="/test", payload={"data": "test"}
        )

    assert isinstance(result, StacApiResponse)
    assert result.success is False
    assert result.status_code == 0
    assert "Network error" in result.message
    assert "Connection failed" in result.message


def test_stac_api_client_request_invalid_json_response(stac_api_client):
    """Test _request method with invalid JSON response."""
    mock_response = Mock()
    mock_response.ok = True
    mock_response.status_code = 200
    mock_response.text = "Plain text response"
    mock_response.content = b"Plain text response"
    mock_response.json.side_effect = ValueError("Invalid JSON")

    with patch.object(stac_api_client.session, "request", return_value=mock_response):
        result = stac_api_client._request(method="GET", endpoint="/text-response")

    assert result.success is True
    assert result.data == "Plain text response"  # Should fall back to text


def test_stac_api_client_request_empty_content(stac_api_client):
    """Test _request method with empty response content."""
    mock_response = Mock()
    mock_response.ok = True
    mock_response.status_code = 204  # No Content
    mock_response.text = ""
    mock_response.content = b""

    with patch.object(stac_api_client.session, "request", return_value=mock_response):
        result = stac_api_client._request(method="DELETE", endpoint="/resource/123")

    assert result.success is True
    assert result.status_code == 204
    assert result.data is None


def test_stac_api_client_request_url_construction(
    stac_api_client, stac_api_url_fixture
):
    """Test that URLs are constructed correctly."""
    mock_response = Mock()
    mock_response.ok = True
    mock_response.status_code = 200
    mock_response.content = b""

    with patch.object(
        stac_api_client.session, "request", return_value=mock_response
    ) as mock_request:
        stac_api_client._request(
            method="POST",
            endpoint="/collections/test/items",
        )

        mock_request.assert_called_once()
        called_args = mock_request.call_args
        assert called_args[1] == {
            "method": "POST",
            "url": f"{stac_api_url_fixture}/collections/test/items",
            "json": None,
            "headers": {"Content-Type": "application/json"},
            "timeout": 30,
        }


def test_stac_api_client_request_logging(stac_api_client):
    """Test that _request method logs correctly."""
    mock_response = Mock()
    mock_response.ok = True
    mock_response.status_code = 200
    mock_response.text = "OK"
    mock_response.content = b""

    with patch.object(stac_api_client.session, "request", return_value=mock_response):
        stac_api_client._request(
            method="GET", endpoint="/test", payload={"test": "data"}
        )

    # Check that logging was called
    assert stac_api_client.logger.info.call_count >= 2


# ------------------------------------------
# Test cases for StacApiClient.post_collection()
# ------------------------------------------
def test_stac_api_client_post_collection_success(stac_api_client):
    """Test post_collection method with successful response."""
    mock_response = StacApiResponse(
        success=True, status_code=201, message="Success", data={"id": "test_collection"}
    )

    with patch.object(
        stac_api_client, "_request", return_value=mock_response
    ) as mock_request:
        result = stac_api_client.post_collection()

        mock_request.assert_called_once_with(
            method="POST",
            endpoint="/collections",
            payload=stac_api_client.stac_collection.to_dict(),
        )

    assert result.success is True
    assert result.status_code == 201
    assert "created successfully" in result.message
    assert stac_api_client.collection_id in result.message


def test_stac_api_client_post_collection_error(stac_api_client):
    """Test post_collection method with error response."""
    mock_response = StacApiResponse(
        success=False,
        status_code=400,
        message="Validation error",
        data={"error": "Invalid collection data"},
    )

    with patch.object(stac_api_client, "_request", return_value=mock_response):
        result = stac_api_client.post_collection()

    assert result.success is False
    assert result.status_code == 400
    assert result.message == "Validation error"


def test_stac_api_client_post_collection_logging(stac_api_client):
    """Test that post_collection logs correctly."""
    mock_response = StacApiResponse(success=True, status_code=201, message="Success")

    with patch.object(stac_api_client, "_request", return_value=mock_response):
        stac_api_client.post_collection()

    # Check that logging was called with collection info
    stac_api_client.logger.info.assert_called_with(
        f"Posting collection {stac_api_client.collection_id} to STAC API."
    )


# ------------------------------------------
# Test cases for StacApiClient.upsert_items()
# ------------------------------------------
def test_stac_api_client_upsert_items_all_success(stac_api_client):
    """Test upsert_items method with all items successful."""
    success_response = StacApiResponse(success=True, status_code=200, message="Success")

    with patch.object(
        stac_api_client, "_request", return_value=success_response
    ) as mock_request:
        result = stac_api_client.upsert_items()

    # Should have made PUT requests for each item
    assert mock_request.call_count == len(stac_api_client.stac_items)

    assert result.success is True
    assert result.status_code == 200
    assert "2 success, 0 errors" in result.message
    assert result.data["success"] == 2
    assert result.data["errors"] == 0
    assert all(status == "success" for status in result.data["results"].values())


def test_stac_api_client_upsert_items_post_fallback(stac_api_client):
    """Test upsert_items method falling back to POST on 404 error."""
    not_found_response = StacApiResponse(
        success=False, status_code=404, message="Item not found"
    )
    post_success_response = StacApiResponse(
        success=True, status_code=201, message="Created"
    )

    call_count = 0

    def mock_request_side_effect(method, endpoint, payload=None):
        nonlocal call_count
        call_count += 1

        if call_count == 1 and method == "PUT":
            return not_found_response
        elif call_count == 2 and method == "POST":
            return post_success_response

        elif call_count == 3 and method == "PUT":
            return StacApiResponse(success=True, status_code=200, message="Updated")
        else:
            return post_success_response

    with patch.object(
        stac_api_client, "_request", side_effect=mock_request_side_effect
    ):
        result = stac_api_client.upsert_items()

    assert result.success is True or (
        result.success is False and result.data["success"] == 2
    )
    assert result.data["success"] == 2
    assert result.data["errors"] == 0

    results = result.data["results"]
    assert len(results) == 2
    assert all("success" in str(status) for status in results.values())


def test_stac_api_client_upsert_items_mixed_results(stac_api_client):
    """Test upsert_items method with mixed success/failure results."""
    success_response = StacApiResponse(success=True, status_code=200, message="Success")
    error_response = StacApiResponse(
        success=False, status_code=500, message="Internal server error"
    )

    with patch.object(
        stac_api_client,
        "_request",
        side_effect=[
            success_response,  # First item succeeds
            error_response,  # Second item fails
        ],
    ):
        result = stac_api_client.upsert_items()

    assert result.success is False  # Overall failure due to some errors
    assert result.status_code == 207  # Multi-status
    assert "1 success, 1 errors" in result.message
    assert result.data["success"] == 1
    assert result.data["errors"] == 1

    # Check individual results
    results = result.data["results"]
    assert len(results) == 2
    assert "success" in list(results.values())
    assert any("error (500)" in str(v) for v in results.values())


def test_stac_api_client_upsert_items_exception_handling(stac_api_client):
    """Test upsert_items method with exceptions during processing."""
    success_response = StacApiResponse(success=True, status_code=200, message="Success")

    with patch.object(
        stac_api_client,
        "_request",
        side_effect=[
            success_response,  # First item succeeds
            Exception("Network timeout"),  # Second item raises exception
        ],
    ):
        result = stac_api_client.upsert_items()

    assert result.success is False
    assert result.status_code == 207
    assert result.data["success"] == 1
    assert result.data["errors"] == 1

    # Check that exception was logged
    stac_api_client.logger.exception.assert_called_once()

    # Check individual results
    results = result.data["results"]
    assert "success" in list(results.values())
    assert any("exception" in str(v) for v in results.values())


def test_stac_api_client_upsert_items_empty_items_list(mock_logger, sample_collection):
    """Test upsert_items method with empty items list."""
    client = StacApiClient(
        api_url="http://test.com",
        collection_id="empty_collection",
        stac_collection=sample_collection,
        stac_items=[],  # Empty list
        logger=mock_logger,
    )

    result = client.upsert_items()

    assert result.success is True  # No errors if no items
    assert result.status_code == 200
    assert result.data["success"] == 0
    assert result.data["errors"] == 0
    assert result.data["results"] == {}


def test_stac_api_client_upsert_items_endpoint_construction(stac_api_client):
    """Test that upsert_items constructs correct endpoints."""
    success_response = StacApiResponse(success=True, status_code=200, message="Success")

    with patch.object(
        stac_api_client, "_request", return_value=success_response
    ) as mock_request:
        stac_api_client.upsert_items()

    # Check that correct endpoints were called
    calls = mock_request.call_args_list
    expected_endpoint = f"/collections/{stac_api_client.collection_id}/items"
    assert calls[0][1]["endpoint"] == expected_endpoint
    assert calls[0][1]["method"] == "POST" or calls[0][1]["method"] == "PUT"


def test_stac_api_client_upsert_items_payload_validation(stac_api_client):
    """Test that upsert_items sends correct payloads."""
    success_response = StacApiResponse(success=True, status_code=200, message="Success")

    with patch.object(
        stac_api_client, "_request", return_value=success_response
    ) as mock_request:
        stac_api_client.upsert_items()

    # Check that correct payloads were sent
    calls = mock_request.call_args_list
    for i, call in enumerate(calls):
        expected_payload = stac_api_client.stac_items[i].to_dict()
        assert call[1]["payload"] == expected_payload
