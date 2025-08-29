# tests/conftest.py
# import pytest
from os import getenv


# ------------------------------------------
# Test cases for environment variables
# ------------------------------------------
def test_required_env_variables():
    """
    Test if all required environment variables are set.
    """
    # List of required environment variables
    required_vars = [
        "GLOBAL_CRS",
        "STAC_API_URL",
        "PYGEOAPI_API_URL",
        "DUCKDB_API_URL",
        "POSTGRES_USER",
        "POSTGRES_PASSWORD",
        "POSTGRES_HOST",
        "POSTGRES_PORT",
        "POSTGRES_DB",
        "DUCKDB_DATABASE",
        "PROJ_LIB",
    ]
    for var in required_vars:
        value = getenv(var)
        assert value not in (
            None,
            "",
            "None",
        ), f"Required env variable {var} is not set"


def test_optional_env_variables():
    """
    Test if optional environment variables are set.
    Notes:
        Check if optional variables are set, but do not fail the test if they are not
        This allows the test to pass even if some optional variables are not set
        However, we can assert that they are not None if they are set
        This is useful for ensuring that if they are set, they have a value
        and are not empty strings or "None"
    """
    optional_vars = [
        "VECTOR_TABLES",
        "RASTER_PATH",
        "RASTER_VOLUME_PATH",
        "RASTER_SOURCE_PATH",
        "RASTER_HARMONIZED_PATH",
        "RASTER_COG_PATH",
        "MY_DOCKER_IP",
    ]

    for var in optional_vars:
        value = getenv(var)
        if value is not None:
            assert value not in (
                "",
                "None",
            ), f"Optional env variable {var} is set but empty or 'None'"
        else:
            assert f"Optional env variable {var} is not set, which is acceptable for this test"


# ------------------------------------------
# Pytest configuration for environment markers
# ------------------------------------------
# for mocked testing
def pytest_configure(config):
    config.addinivalue_line(
        "markers", "mocked: mark test to run only on mocked environment"
    )


# ------------------------------------------
# API URLs for testing
# ------------------------------------------
# These URLs are used to test the API endpoints in the application
# They differ from the ones in the main application and are used for testing purposes only
stac_api_url = "http://localhost:8081"
raster_api_url = "http://localhost:8082"
vector_api_url = "http://localhost:8083"
stacbrowser_api_url = "http://localhost:8085"
pygeoapi_api_url = "http://localhost:5000"
duckdb_api_url = "http://localhost:8084"
