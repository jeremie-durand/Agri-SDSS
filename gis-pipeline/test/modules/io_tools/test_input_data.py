from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from gis_pipeline.modules.io_tools.input_data import (
    detect_non_spatial_csv,
    discover_geodata,
    read_csv_file,
)


# ------------------------------------------
# Fixtures
# ------------------------------------------
@pytest.fixture
def temp_directory_structure(tmp_path):
    """Create a temporary directory structure with test files."""
    # Create subdirectories
    raster_dir = tmp_path / "rasters"
    vector_dir = tmp_path / "vectors"
    mixed_dir = tmp_path / "mixed"
    empty_dir = tmp_path / "empty"

    raster_dir.mkdir()
    vector_dir.mkdir()
    mixed_dir.mkdir()
    empty_dir.mkdir()

    # Create raster files
    (raster_dir / "image1.tif").write_text("dummy raster")
    (raster_dir / "image2.TIFF").write_text("dummy raster")  # Test case sensitivity
    (raster_dir / "sentinel.jp2").write_text("dummy raster")  # Unsupported format

    # Create vector files
    (vector_dir / "polygons.shp").write_text("dummy vector")
    (vector_dir / "points.geojson").write_text("dummy vector")
    (vector_dir / "data.gpkg").write_text("dummy vector")

    # Create mixed directory
    (mixed_dir / "mixed_raster.tif").write_text("dummy raster")
    (mixed_dir / "mixed_vector.shp").write_text("dummy vector")
    (mixed_dir / "unsupported.txt").write_text("text file")  # Unsupported format
    (mixed_dir / "no_extension").write_text("no extension")

    # Create nested structure
    nested_dir = mixed_dir / "nested"
    nested_dir.mkdir()
    (nested_dir / "deep_raster.tiff").write_text("nested raster")
    (nested_dir / "deep_vector.kml").write_text("nested vector")  # Unsupported format

    return tmp_path


# ------------------------------------------
# Test cases for discover_geodata()
# ------------------------------------------
def test_discover_geodata_empty_directory(tmp_path):
    """Test discover_geodata with empty directory."""
    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()

    result = discover_geodata(input_path=empty_dir)

    assert result == {"rasters": [], "vectors": []}
    assert isinstance(result["rasters"], list)
    assert isinstance(result["vectors"], list)


def test_discover_geodata_only_raster_files(tmp_path):
    """Test discover_geodata with only raster files."""
    raster_dir = tmp_path / "rasters"
    raster_dir.mkdir()

    raster1 = raster_dir / "image1.tif"

    raster1.write_text("dummy")

    result = discover_geodata(input_path=raster_dir)

    assert len(result["rasters"]) == 1
    assert len(result["vectors"]) == 0
    assert raster1 in result["rasters"]


def test_discover_geodata_only_vector_files(tmp_path):
    """Test discover_geodata with only vector files."""
    vector_dir = tmp_path / "vectors"
    vector_dir.mkdir()

    vector1 = vector_dir / "polygons.shp"
    vector2 = vector_dir / "points.geojson"
    vector3 = vector_dir / "data.gpkg"

    vector1.write_text("dummy")
    vector2.write_text("dummy")
    vector3.write_text("dummy")

    result = discover_geodata(input_path=vector_dir)

    assert len(result["rasters"]) == 0
    assert len(result["vectors"]) == 3
    assert vector1 in result["vectors"]
    assert vector2 in result["vectors"]
    assert vector3 in result["vectors"]


def test_discover_geodata_mixed_files(tmp_path):
    """Test discover_geodata with mixed raster and vector files."""
    mixed_dir = tmp_path / "mixed"
    mixed_dir.mkdir()

    # Create mixed files
    raster1 = mixed_dir / "image.tif"
    vector1 = mixed_dir / "shapes.shp"
    unsupported = mixed_dir / "document.txt"

    raster1.write_text("dummy")
    vector1.write_text("dummy")
    unsupported.write_text("dummy")

    result = discover_geodata(input_path=mixed_dir)

    assert len(result["rasters"]) == 1
    assert len(result["vectors"]) == 1
    assert raster1 in result["rasters"]
    assert vector1 in result["vectors"]
    assert unsupported not in result["rasters"]
    assert unsupported not in result["vectors"]


def test_discover_geodata_recursive_search(tmp_path):
    """Test discover_geodata recursive search in nested directories."""
    # Create nested structure
    root_dir = tmp_path / "root"
    sub_dir1 = root_dir / "level1"
    sub_dir2 = sub_dir1 / "level2"

    root_dir.mkdir()
    sub_dir1.mkdir()
    sub_dir2.mkdir()

    # Create files at different levels
    root_raster = root_dir / "root.tif"
    level1_vector = sub_dir1 / "level1.shp"
    level2_raster = sub_dir2 / "level2.tif"

    root_raster.write_text("dummy")
    level1_vector.write_text("dummy")
    level2_raster.write_text("dummy")

    result = discover_geodata(input_path=root_dir)

    assert len(result["rasters"]) == 2
    assert len(result["vectors"]) == 1
    assert root_raster in result["rasters"]
    assert level2_raster in result["rasters"]
    assert level1_vector in result["vectors"]


def test_discover_geodata_case_insensitive_extensions(tmp_path):
    """Test discover_geodata handles case-insensitive file extensions."""
    test_dir = tmp_path / "case_test"
    test_dir.mkdir()

    # Create files with different cases
    files = [
        test_dir / "image1.tif",  # lowercase
        test_dir / "image2.TIF",  # uppercase
        test_dir / "image3.Tif",  # mixed case
        test_dir / "vector1.shp",  # lowercase
        test_dir / "vector2.SHP",  # uppercase
        test_dir / "vector3.Shp",  # mixed case
    ]

    for file in files:
        file.write_text("dummy")

    result = discover_geodata(input_path=test_dir)

    assert len(result["rasters"]) == 3
    assert len(result["vectors"]) == 3

    # Verify all files are found regardless of case
    for file in files[:3]:
        assert file in result["rasters"]
    for file in files[3:]:
        assert file in result["vectors"]


def test_discover_geodata_ignores_directories(tmp_path):
    """Test discover_geodata ignores directories even if they have supported extensions."""
    test_dir = tmp_path / "test"
    test_dir.mkdir()

    fake_raster_dir = test_dir / "not_a_file.tif"
    fake_raster_dir.mkdir()

    real_raster = test_dir / "real_file.tif"
    real_raster.write_text("dummy")

    result = discover_geodata(input_path=test_dir)

    assert len(result["rasters"]) == 1
    assert real_raster in result["rasters"]
    assert fake_raster_dir not in result["rasters"]


def test_discover_geodata_nonexistent_directory():
    """Test discover_geodata with non-existent directory."""
    non_existent = Path("/non/existent/path")

    result = discover_geodata(input_path=non_existent)
    assert result == {"rasters": [], "vectors": []}


def test_discover_geodata_comprehensive_structure(temp_directory_structure):
    """Test discover_geodata with comprehensive directory structure."""
    result = discover_geodata(input_path=temp_directory_structure)

    assert (
        len(result["rasters"]) == 4
    )  # image1.tif, image2.TIFF, mixed_raster.tif, deep_raster.tiff
    assert (
        len(result["vectors"]) == 4
    )  # polygons.shp, points.geojson, data.gpkg, mixed_vector.shp

    raster_files = [f.name for f in result["rasters"]]
    vector_files = [f.name for f in result["vectors"]]

    assert "image1.tif" in raster_files
    assert "image2.TIFF" in raster_files
    assert "mixed_raster.tif" in raster_files
    assert "deep_raster.tiff" in raster_files

    assert "polygons.shp" in vector_files
    assert "points.geojson" in vector_files
    assert "data.gpkg" in vector_files

    assert "deep_vector.kml" not in vector_files  # Unsupported format
    assert "sentinel.jp2" not in raster_files  # Unsupported format
    assert "unsupported.txt" not in raster_files  # Unsupported format


def test_discover_geodata_performance_with_many_files(tmp_path):
    """Test discover_geodata performance with large number of files."""
    test_dir = tmp_path / "performance"
    test_dir.mkdir()

    num_files = 100
    for i in range(num_files):
        if i % 2 == 0:
            (test_dir / f"raster_{i}.tif").write_text("dummy")
        else:
            (test_dir / f"vector_{i}.shp").write_text("dummy")

    result = discover_geodata(input_path=test_dir)

    assert len(result["rasters"]) == 50
    assert len(result["vectors"]) == 50


def test_discover_geodata_edge_case_extensions(tmp_path):
    """Test discover_geodata with edge case extensions."""
    test_dir = tmp_path / "edge_cases"
    test_dir.mkdir()

    files = [
        test_dir / "file.tif",  # valid raster
        test_dir / "file.",  # dot only
        test_dir / "file",  # no extension (empty string)
        test_dir / "file.unknown",  # unsupported
    ]

    # Patch the Enums by replacing them with iterables of SimpleNamespace(value=...)
    with patch(
        "gis_pipeline.modules.io_tools.input_data.SupportedRasterFormats",
        new=[SimpleNamespace(value=".tif"), SimpleNamespace(value=".")],
    ), patch(
        "gis_pipeline.modules.io_tools.input_data.SupportedVectorFormats",
        new=[SimpleNamespace(value=".shp"), SimpleNamespace(value="")],
    ):

        for file in files:
            file.write_text("dummy")

        result = discover_geodata(input_path=test_dir)

        # Only .tif should be found as raster
        assert len(result["rasters"]) == 1
        assert files[0] in result["rasters"]


# ------------------------------------------
# Test cases for read_csv_file()
# ------------------------------------------
def test_read_csv_file_utf8_default(tmp_path):
    """Reads a simple UTF-8 encoded CSV with default settings."""
    csv_file = tmp_path / "utf8.csv"
    csv_file.write_text("colA,colB\n1,2\nx,y", encoding="utf-8")

    df = read_csv_file(csv_file)

    assert df.shape == (2, 2)
    assert "colA" in df.columns and "colB" in df.columns


def test_read_csv_file_latin1_fallback_and_semicolon_sep(tmp_path):
    """Ensures fallback to latin1 when utf-8 fails and semicolon separator is detected."""
    csv_file = tmp_path / "latin1_semicolon.csv"
    # bytes that are valid latin1 but invalid utf-8 for the é character
    csv_bytes = b"col1;col2\nv1;caf\xe9\n"
    csv_file.write_bytes(csv_bytes)

    df = read_csv_file(csv_file)  # default encodings try utf-8 then latin1

    assert df.shape == (1, 2)
    # pandas should have detected ';' as separator and decoded to 'café'
    assert df.iloc[0]["col2"] == "café"


def test_read_csv_file_accepts_read_csv_kwargs(tmp_path):
    """Passes additional kwargs to pandas.read_csv (header/names)."""
    csv_file = tmp_path / "no_header.csv"
    csv_file.write_text("a;bb\nc;d", encoding="utf-8")

    df = read_csv_file(csv_file, header=None, names=["first", "second"])

    assert list(df.columns) == ["first", "second"]
    assert df.shape == (2, 2)


def test_read_csv_file_no_encodings_provided_raises_value_error(tmp_path):
    """If encodings list is empty the function should raise ValueError."""
    csv_file = tmp_path / "some.csv"
    csv_file.write_text("col1,col2\n1,2", encoding="utf-8")

    with pytest.raises(ValueError):
        read_csv_file(csv_file, encodings=[])


def test_read_csv_file_propagates_last_exception_when_all_fail(tmp_path):
    """If pandas.read_csv raises for all attempts, the last exception is propagated."""
    csv_file = tmp_path / "bad.csv"
    csv_file.write_text("not,a,csv", encoding="utf-8")

    with patch(
        "gis_pipeline.modules.io_tools.input_data.pd.read_csv",
        side_effect=RuntimeError("read failure"),
    ):
        with pytest.raises(RuntimeError, match="read failure"):
            read_csv_file(csv_file, encodings=["utf-8", "latin1"])


# ------------------------------------------
# Test cases for detect_non_spatial_csv()
# ------------------------------------------
def test_detect_non_spatial_csv_mixed(tmp_path):
    """Detects non-spatial CSVs when mixed with known spatial CSVs."""
    with patch(
        "gis_pipeline.modules.io_tools.input_data.CSVDataRegistryForSourceCRS",
        new=[
            SimpleNamespace(value=["spatial1"]),
            SimpleNamespace(value=["spatial2"]),
        ],
    ):
        known1 = tmp_path / "spatial1.csv"
        known2 = tmp_path / "spatial2.csv"
        unknown = tmp_path / "other.csv"

        known1.write_text("a")
        known2.write_text("b")
        unknown.write_text("c")

        result = detect_non_spatial_csv([known1, known2, unknown])

        assert isinstance(result, list)
        assert result == [unknown]


def test_detect_non_spatial_csv_case_insensitive(tmp_path):
    """Stems comparison should be case-insensitive."""
    with patch(
        "gis_pipeline.modules.io_tools.input_data.CSVDataRegistryForSourceCRS",
        new=[SimpleNamespace(value=["spatialX"])],
    ):
        file_upper = tmp_path / "SPATIALX.csv"
        file_mixed = tmp_path / "Spatialx.csv"
        unknown = tmp_path / "other.csv"

        file_upper.write_text("x")
        file_mixed.write_text("y")
        unknown.write_text("z")

        result = detect_non_spatial_csv([file_upper, file_mixed, unknown])

        # both spatialX variants should be treated as known -> only unknown returned
        assert result == [unknown]


def test_detect_non_spatial_csv_empty_input(tmp_path):
    """Returns empty list for empty input."""
    with patch(
        "gis_pipeline.modules.io_tools.input_data.CSVDataRegistryForSourceCRS",
        new=[SimpleNamespace(value=["spatial"])],
    ):
        result = detect_non_spatial_csv([])
        assert result == []
