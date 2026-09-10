import os

import pytest


@pytest.fixture(scope="session")
def pygeoapi_api_url_fixture():
    return os.getenv("PYGEOAPI_API_URL", "http://localhost:5000")
