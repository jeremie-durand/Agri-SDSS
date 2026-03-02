from os import getenv

import pytest

REQUIRED_VARS = [
    "STAC_API_URL",
    "PYGEOAPI_API_URL",
    "POSTGRES_USER",
    "POSTGRES_PASSWORD",
    "POSTGRES_HOST",
    "POSTGRES_PORT",
    "POSTGRES_DB",
    "DUCKDB_DATA_DIR",
    "DUCKDB_DATABASE",
]


def check_required_env_variables():
    for var in REQUIRED_VARS:
        value = getenv(var)
        error_msg = f"Required env variable {var} is not set"
        if value is None:
            raise AssertionError(error_msg)

        stripped_value = value.strip()
        if stripped_value == "" or stripped_value.lower() == "none":
            raise AssertionError(error_msg)


def _clear_required_env(monkeypatch):
    for var in REQUIRED_VARS:
        monkeypatch.delenv(var, raising=False)


def _set_all_valid(monkeypatch):
    for var in REQUIRED_VARS:
        monkeypatch.setenv(var, f"valid_value_for_{var}")


def test_required_env_vars_all_unset(monkeypatch):
    """Test that missing required environment variables are detected."""
    _clear_required_env(monkeypatch)

    with pytest.raises(AssertionError) as excinfo:
        check_required_env_variables()
    assert "is not set" in str(excinfo.value)


def test_required_env_vars_all_set(monkeypatch):
    """Test that all required environment variables set passes the check."""
    _set_all_valid(monkeypatch)

    check_required_env_variables()


def test_required_env_vars_some_unset(monkeypatch):
    """Test that some missing required environment variables are detected."""
    _set_all_valid(monkeypatch)

    monkeypatch.delenv("POSTGRES_PASSWORD", raising=False)
    monkeypatch.delenv("DUCKDB_DATABASE", raising=False)

    with pytest.raises(AssertionError) as excinfo:
        check_required_env_variables()
    assert "is not set" in str(excinfo.value)


def test_required_env_vars_empty_values(monkeypatch):
    """Test that empty string values for required environment variables are detected."""
    _set_all_valid(monkeypatch)

    monkeypatch.setenv("STAC_API_URL", "")
    monkeypatch.setenv("POSTGRES_USER", "")

    with pytest.raises(AssertionError) as excinfo:
        check_required_env_variables()
    assert "is not set" in str(excinfo.value)


def test_required_env_vars_none_string(monkeypatch):
    """Test that 'None' string values for required environment variables are detected."""
    _set_all_valid(monkeypatch)

    monkeypatch.setenv("PYGEOAPI_API_URL", "None")
    monkeypatch.setenv("DUCKDB_DATA_DIR", "None")

    with pytest.raises(AssertionError) as excinfo:
        check_required_env_variables()
    assert "is not set" in str(excinfo.value)


def test_required_env_vars_none_value(monkeypatch):
    """Test that None values for required environment variables are detected."""
    _set_all_valid(monkeypatch)

    monkeypatch.delenv("POSTGRES_HOST", raising=False)
    monkeypatch.delenv("POSTGRES_DB", raising=False)

    with pytest.raises(AssertionError) as excinfo:
        check_required_env_variables()
    assert "is not set" in str(excinfo.value)


def test_required_env_vars_whitespace_values(monkeypatch):
    """Test that whitespace string values for required environment variables are detected."""
    _set_all_valid(monkeypatch)

    monkeypatch.setenv("POSTGRES_PORT", "   ")
    monkeypatch.setenv("DUCKDB_DATABASE", "\t")

    with pytest.raises(AssertionError) as excinfo:
        check_required_env_variables()
    assert "is not set" in str(excinfo.value)
