"""Unit tests for services/mapping.py enums and helpers."""

import re

import pytest
from gis_pipeline.services.mapping import (
    AttributeNullValues,
    ColumnMappings,
    ColumnName,
    DefaultMetadata,
    NamingPatterns,
    SupportedRasterFormats,
    SupportedVectorFormats,
)

# ---------------------------------------------------------------------------
# TestColumnName
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestColumnName:
    def test_canonical_lowercased(self) -> None:
        assert ColumnName("GID").canonical == "gid"

    def test_single_string_alias_becomes_list(self) -> None:
        col = ColumnName("geometry", alias="geom")
        assert col.alias == ["geom"]

    def test_none_alias_becomes_empty_list(self) -> None:
        col = ColumnName("bbox")
        assert col.alias == []

    def test_aliases_lowercased(self) -> None:
        col = ColumnName("x", alias=["LAT", "Y"])
        assert col.alias == ["lat", "y"]

    def test_iterable_aliases_preserved(self) -> None:
        col = ColumnName("gid", alias=["id", "station_id", "no"])
        assert "id" in col.alias
        assert "station_id" in col.alias
        assert len(col.alias) == 3


# ---------------------------------------------------------------------------
# TestColumnMappingsFind
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestColumnMappingsFind:
    def test_find_by_canonical(self) -> None:
        assert ColumnMappings.find("gid") == ColumnMappings.GID

    def test_find_by_alias_id(self) -> None:
        assert ColumnMappings.find("id") == ColumnMappings.GID

    def test_find_by_alias_lat(self) -> None:
        assert ColumnMappings.find("lat") == ColumnMappings.LATITUDE

    def test_find_case_insensitive(self) -> None:
        assert ColumnMappings.find("GID") == ColumnMappings.GID
        assert ColumnMappings.find("DATETIME") == ColumnMappings.DATETIME

    def test_find_strips_whitespace(self) -> None:
        assert ColumnMappings.find("  gid  ") == ColumnMappings.GID

    def test_find_unknown_returns_none(self) -> None:
        assert ColumnMappings.find("unknown_col") is None

    def test_find_empty_string_returns_none(self) -> None:
        assert ColumnMappings.find("") is None

    @pytest.mark.parametrize(
        "alias,expected",
        [
            ("station_id", ColumnMappings.GID),
            ("geom", ColumnMappings.GEOMETRY),
            ("date", ColumnMappings.DATETIME),
            ("lon", ColumnMappings.LONGITUDE),
            ("properties", ColumnMappings.METADATA),
            ("y", ColumnMappings.LATITUDE),
            ("x", ColumnMappings.LONGITUDE),
        ],
    )
    def test_find_known_aliases(self, alias: str, expected: ColumnMappings) -> None:
        assert ColumnMappings.find(alias) == expected


# ---------------------------------------------------------------------------
# TestAttributeNullValues
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestAttributeNullValues:
    def test_contains_empty_string(self) -> None:
        values = {m.value for m in AttributeNullValues}
        assert "" in values

    def test_contains_none(self) -> None:
        values = {m.value for m in AttributeNullValues}
        assert None in values

    def test_full_set_of_values(self) -> None:
        values = {m.value for m in AttributeNullValues}
        assert values == {"", "na", "Na", "NA", "n/a", "N/A", None}


# ---------------------------------------------------------------------------
# TestDefaultMetadata
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestDefaultMetadata:
    def test_get_defaults_returns_dict(self) -> None:
        result = DefaultMetadata.get_defaults()
        assert isinstance(result, dict)

    def test_get_defaults_has_source_key(self) -> None:
        result = DefaultMetadata.get_defaults()
        assert "source" in result
        assert result["source"] == "unknown"

    def test_get_defaults_has_description_key(self) -> None:
        result = DefaultMetadata.get_defaults()
        assert "description" in result

    def test_datetime_is_epoch(self) -> None:
        assert DefaultMetadata.DATETIME.value == "1970-01-01T00:00:00Z"

    def test_get_defaults_does_not_include_datetime(self) -> None:
        # datetime is a fallback constant, not a default metadata field
        result = DefaultMetadata.get_defaults()
        assert "datetime" not in result


# ---------------------------------------------------------------------------
# TestNamingPatterns
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestNamingPatterns:
    def test_gdf_pattern_replaces_special_chars(self) -> None:
        result = re.sub(NamingPatterns.PATTERN_GDF_NAME.value, "_", "foo bar-baz")
        assert result == "foo_bar_baz"

    def test_gdf_pattern_keeps_valid_chars(self) -> None:
        result = re.sub(NamingPatterns.PATTERN_GDF_NAME.value, "_", "valid_name_123")
        assert result == "valid_name_123"

    def test_duckdb_pattern_accepts_valid_name(self) -> None:
        assert (
            re.match(NamingPatterns.PATTERN_DUCKDB_NAME.value, "valid_name") is not None
        )

    def test_duckdb_pattern_rejects_hyphen(self) -> None:
        assert re.match(NamingPatterns.PATTERN_DUCKDB_NAME.value, "has-hyphen") is None

    def test_duckdb_pattern_rejects_space(self) -> None:
        assert re.match(NamingPatterns.PATTERN_DUCKDB_NAME.value, "has space") is None

    def test_valid_pg_identifier_rejects_digit_start(self) -> None:
        assert re.match(NamingPatterns.VALID_PG_IDENTIFIER.value, "123abc") is None

    def test_valid_pg_identifier_accepts_underscore_start(self) -> None:
        assert re.match(NamingPatterns.VALID_PG_IDENTIFIER.value, "_valid") is not None


# ---------------------------------------------------------------------------
# TestSupportedFormats
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSupportedFormats:
    def test_vector_formats_include_csv(self) -> None:
        values = {f.value for f in SupportedVectorFormats}
        assert ".csv" in values

    def test_vector_formats_include_shp(self) -> None:
        values = {f.value for f in SupportedVectorFormats}
        assert ".shp" in values

    def test_raster_formats_complete(self) -> None:
        values = {f.value for f in SupportedRasterFormats}
        assert values == {".tif", ".tiff"}

    def test_raster_and_vector_formats_are_disjoint(self) -> None:
        vector = {f.value for f in SupportedVectorFormats}
        raster = {f.value for f in SupportedRasterFormats}
        assert vector.isdisjoint(raster)
