from pathlib import Path

import pytest
from gis_pipeline.core.config import Config
from gis_pipeline.core.utils import harmonize_name
from gis_pipeline.services.mapping import NamingPatterns

_GDF_PATTERN = NamingPatterns.PATTERN_GDF_NAME.value
_RASTER_PATTERN = NamingPatterns.PATTERN_RASTER_NAME.value
_MAX = Config.POSTGRES_MAX_NAME_LENGTH


# ------------------------------------------
# Test cases for harmonize_name() — GDF pattern
# ------------------------------------------
def test_harmonize_name_gdf_simple_name():
    assert harmonize_name("simple_name", _GDF_PATTERN, _MAX) == "simple_name"


def test_harmonize_name_gdf_uppercase_conversion():
    assert harmonize_name("UPPERCASE_NAME", _GDF_PATTERN, _MAX) == "uppercase_name"


def test_harmonize_name_gdf_mixed_case_conversion():
    assert harmonize_name("MixedCase_Name", _GDF_PATTERN, _MAX) == "mixedcase_name"


def test_harmonize_name_gdf_special_characters_replacement():
    assert (
        harmonize_name("name-with.special@chars!", _GDF_PATTERN, _MAX)
        == "name_with_special_chars"
    )


def test_harmonize_name_gdf_spaces_replacement():
    assert harmonize_name("name with spaces", _GDF_PATTERN, _MAX) == "name_with_spaces"


def test_harmonize_name_gdf_multiple_consecutive_specials():
    assert (
        harmonize_name("name---with...multiple@@@specials", _GDF_PATTERN, _MAX)
        == "name_with_multiple_specials"
    )


def test_harmonize_name_gdf_leading_trailing_underscores_stripped():
    assert (
        harmonize_name("___name_with_underscores___", _GDF_PATTERN, _MAX)
        == "name_with_underscores"
    )


def test_harmonize_name_gdf_numbers_preserved():
    assert (
        harmonize_name("table123_with_numbers456", _GDF_PATTERN, _MAX)
        == "table123_with_numbers456"
    )


def test_harmonize_name_gdf_only_numbers():
    assert harmonize_name("123456", _GDF_PATTERN, _MAX) == "123456"


def test_harmonize_name_gdf_only_underscores():
    assert harmonize_name("___---...", _GDF_PATTERN, _MAX) == ""


def test_harmonize_name_gdf_empty_string_after_cleaning():
    assert harmonize_name("!@#$%^&*()", _GDF_PATTERN, _MAX) == ""


def test_harmonize_name_gdf_whitespace_only_name_raises_error():
    with pytest.raises(ValueError, match="Name must not be empty or whitespace."):
        harmonize_name("   ", _GDF_PATTERN, _MAX)


def test_harmonize_name_gdf_long_name_truncation():
    long_name = "a" * 70
    result = harmonize_name(long_name, _GDF_PATTERN, _MAX)
    assert len(result) <= _MAX
    assert result.endswith("_" + result[-6:])
    assert result.startswith("a" * (_MAX - 7))


def test_harmonize_name_gdf_long_name_with_custom_max_len():
    long_name = "very_long_table_name_that_exceeds_limit"
    max_len = 20
    result = harmonize_name(long_name, _GDF_PATTERN, max_len)
    assert len(result) <= max_len
    assert "_" in result
    assert len(result.split("_")[-1]) == 6


def test_harmonize_name_gdf_exactly_max_length():
    max_len = 10
    exact_name = "a" * max_len
    result = harmonize_name(exact_name, _GDF_PATTERN, max_len)
    assert result == exact_name
    assert len(result) == max_len


def test_harmonize_name_gdf_one_char_over_max():
    max_len = 10
    over_name = "a" * (max_len + 1)
    result = harmonize_name(over_name, _GDF_PATTERN, max_len)
    assert len(result) <= max_len
    assert result != over_name


def test_harmonize_name_gdf_unicode_characters():
    assert (
        harmonize_name("table_with_éñ_chars", _GDF_PATTERN, _MAX)
        == "table_with___chars"
    )


def test_harmonize_name_gdf_complex_real_world_example():
    assert (
        harmonize_name("My Data Table (2023) - Version 1.0.xlsx", _GDF_PATTERN, _MAX)
        == "my_data_table_2023_version_1_0_xlsx"
    )


def test_harmonize_name_gdf_sql_injection_attempt():
    assert (
        harmonize_name("table'; DROP TABLE users; --", _GDF_PATTERN, _MAX)
        == "table_drop_table_users"
    )


def test_harmonize_name_gdf_hash_consistency():
    long_name = (
        "very_long_table_name_that_will_definitely_exceed_the_maximum_length_limit"
    )
    result1 = harmonize_name(long_name, _GDF_PATTERN, 20)
    result2 = harmonize_name(long_name, _GDF_PATTERN, 20)
    assert result1 == result2
    assert len(result1) == 20


def test_harmonize_name_gdf_different_long_names_different_hashes():
    result1 = harmonize_name(
        "very_long_table_name_that_will_definitely_exceed_the_maximum_length_limit_1",
        _GDF_PATTERN,
        20,
    )
    result2 = harmonize_name(
        "very_long_table_name_that_will_definitely_exceed_the_maximum_length_limit_2",
        _GDF_PATTERN,
        20,
    )
    assert result1 != result2
    assert result1[-6:] != result2[-6:]


def test_harmonize_name_gdf_preserves_valid_database_names():
    valid_names = [
        "users",
        "user_data",
        "table_123",
        "my_table_name",
        "data2023",
        "a_very_long_but_valid_name_under_limit",
    ]
    for name in valid_names:
        if len(name) <= _MAX:
            assert harmonize_name(name, _GDF_PATTERN, _MAX) == name


@pytest.mark.parametrize(
    "input_name,expected",
    [
        ("simple", "simple"),
        ("UPPER", "upper"),
        ("With Spaces", "with_spaces"),
        ("with-dashes", "with_dashes"),
        ("with.dots", "with_dots"),
        ("123numbers", "123numbers"),
        ("_underscore_", "underscore"),
        ("mix3d_Ch4rs!", "mix3d_ch4rs"),
    ],
)
def test_harmonize_name_gdf_parametrized_cases(input_name, expected):
    assert harmonize_name(input_name, _GDF_PATTERN, _MAX) == expected


def test_harmonize_name_gdf_hash_format():
    result = harmonize_name("a" * 100, _GDF_PATTERN, 20)
    hash_part = result.split("_")[-1]
    assert len(hash_part) == 6
    try:
        int(hash_part, 16)
        is_hex = True
    except ValueError:
        is_hex = False
    assert is_hex, f"Hash '{hash_part}' is not valid hexadecimal"


# ------------------------------------------
# Test cases for harmonize_name() — raster pattern
# ------------------------------------------


def _raster_max_len(
    filename: str, base_max: int = Config.POSTGRES_MAX_NAME_LENGTH
) -> int:
    return base_max - len(Path(filename).suffix.lower())


def test_harmonize_name_raster_basic():
    assert (
        harmonize_name(
            "test_raster", _RASTER_PATTERN, _raster_max_len("test_raster.tif")
        )
        == "test_raster"
    )


def test_harmonize_name_raster_with_special_characters():
    test_names = [
        ("raster-with-dashes.tif", "raster_with_dashes"),
        ("raster with spaces.tif", "raster_with_spaces"),
        ("raster@#$%^&*().tif", "raster"),
        ("raster(2024).tif", "raster_2024"),
        ("raster[version1].tif", "raster_version1"),
        ("raster{final}.tif", "raster_final"),
        ("_raster_.tif", "raster"),
        ("__multiple__underscores__.tif", "multiple__underscores"),
    ]
    for filename, expected in test_names:
        stem = Path(filename).stem
        result = harmonize_name(stem, _RASTER_PATTERN, _raster_max_len(filename))
        assert result == expected


def test_harmonize_name_raster_uppercase_to_lowercase():
    test_cases = [
        ("RASTER.TIF", "raster"),
        ("MyRaster.TIF", "myraster"),
        ("RASTER_FILE_2024.TIF", "raster_file_2024"),
    ]
    for filename, expected in test_cases:
        stem = Path(filename).stem
        result = harmonize_name(stem, _RASTER_PATTERN, _raster_max_len(filename))
        assert result == expected


def test_harmonize_name_raster_strip_leading_trailing_underscores():
    test_cases = [
        ("_raster.tif", "raster"),
        ("raster_.tif", "raster"),
        ("__raster__.tif", "raster"),
        ("___multiple___underscores___.tif", "multiple___underscores"),
    ]
    for filename, expected in test_cases:
        stem = Path(filename).stem
        result = harmonize_name(stem, _RASTER_PATTERN, _raster_max_len(filename))
        assert result == expected


def test_harmonize_name_raster_empty_string():
    with pytest.raises(ValueError, match="Name must not be empty or whitespace"):
        harmonize_name("", _RASTER_PATTERN, _raster_max_len(".tif"))


def test_harmonize_name_raster_whitespace_only():
    for whitespace_input in ["   ", "\t", "\n", "  \t\n  "]:
        with pytest.raises(ValueError, match="Name must not be empty or whitespace"):
            harmonize_name(whitespace_input, _RASTER_PATTERN, _raster_max_len(".tif"))


def test_harmonize_name_raster_max_length_truncation():
    max_len = 20 - len(".tif")
    long_stem = "this_is_a_very_long_raster_file_name_that_exceeds_the_limit"
    result = harmonize_name(long_stem, _RASTER_PATTERN, max_len)
    assert len(result) <= max_len
    assert "_" in result


def test_harmonize_name_raster_hash_consistency():
    max_len = 20 - len(".tif")
    long_stem = "extremely_long_raster_file_name_for_testing_hash_consistency"
    result1 = harmonize_name(long_stem, _RASTER_PATTERN, max_len)
    result2 = harmonize_name(long_stem, _RASTER_PATTERN, max_len)
    assert result1 == result2


def test_harmonize_name_raster_exact_max_length():
    max_len = 20 - len(".tif")
    exact_stem = "a" * max_len
    result = harmonize_name(exact_stem, _RASTER_PATTERN, max_len)
    assert result == exact_stem
    assert len(result) == max_len


def test_harmonize_name_raster_one_char_over_limit():
    max_len = 20 - len(".tif")
    over_limit_stem = "a" * (max_len + 1)
    result = harmonize_name(over_limit_stem, _RASTER_PATTERN, max_len)
    assert len(result) <= max_len


def test_harmonize_name_raster_numeric_names():
    numeric_names = [
        ("123456.tif", "123456"),
        ("2024_01_15.tif", "2024_01_15"),
        ("001-raster-2024.tif", "001_raster_2024"),
    ]
    for filename, expected in numeric_names:
        stem = Path(filename).stem
        result = harmonize_name(stem, _RASTER_PATTERN, _raster_max_len(filename))
        assert result == expected


def test_harmonize_name_raster_unicode_characters():
    unicode_names = [
        ("raster_café.tif", "raster_caf"),
        ("raster_naïve.tif", "raster_na_ve"),
        ("raster_münchen.tif", "raster_m_nchen"),
    ]
    for filename, expected in unicode_names:
        stem = Path(filename).stem
        result = harmonize_name(stem, _RASTER_PATTERN, _raster_max_len(filename))
        assert result == expected


def test_harmonize_name_raster_multiple_extensions():
    multi_extension_names = [
        ("raster.backup.tif", "raster_backup"),
        ("data.2024.01.tif", "data_2024_01"),
        ("file.v1.0.final.tif", "file_v1_0_final"),
    ]
    for filename, expected in multi_extension_names:
        stem = Path(filename).stem
        result = harmonize_name(stem, _RASTER_PATTERN, _raster_max_len(filename))
        assert result == expected


@pytest.mark.unit
def test_harmonize_name_max_len_smaller_than_suffix_returns_hash_prefix():
    """When max_len < HASH_SUFFIX_LENGTH, available_length <= 0 and the result
    is the first max_len characters of the MD5 hash (no truncated stem)."""
    long_name = "a" * 100  # guaranteed to exceed any small max_len
    max_len = Config.HASH_HEX_LENGTH - 1  # e.g. 5 if HASH_HEX_LENGTH=6
    if max_len <= 0:
        pytest.skip("HASH_HEX_LENGTH too small for this edge case")
    result = harmonize_name(long_name, _GDF_PATTERN, max_len)
    assert len(result) <= max_len
    # Must be a hex string (only [0-9a-f] characters)
    assert all(c in "0123456789abcdef" for c in result)


@pytest.mark.unit
def test_harmonize_name_max_len_exactly_suffix_length_returns_hash_prefix():
    """max_len == HASH_SUFFIX_LENGTH means available_length == 0 → pure hash prefix."""
    long_name = "b" * 100
    max_len = Config.HASH_SUFFIX_LENGTH
    result = harmonize_name(long_name, _GDF_PATTERN, max_len)
    assert len(result) <= max_len
