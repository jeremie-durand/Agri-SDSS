from datetime import datetime as dt
from datetime import timezone
from os import getenv
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).parents[1]  # stac-fastapi/

# Load YAML config
with open(PROJECT_ROOT / "config.yaml") as f:
    cfg = yaml.safe_load(f)


class Config:
    """Project configuration loaded from environment variables and YAML config."""

    # Pipeline properties
    GLOBAL_CRS = cfg["pipeline"]["GLOBAL_CRS"]
    PROJ_LIB = cfg["pipeline"]["PROJ_LIB"]
    STAC_COLLECTION_ID = cfg["pipeline"]["STAC_COLLECTION_ID"]
    DEFAULT_DATETIME = dt(1950, 1, 1, tzinfo=timezone.utc)  # Fallback datetime
    NOW_DATETIME = dt.now(tz=timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    HASH_HEX_LENGTH = 6  # number of hex chars taken from md5 hexdigest
    HASH_SEPARATOR = "_"  # separator between truncated name and hash
    HASH_SUFFIX_LENGTH = HASH_HEX_LENGTH + len(HASH_SEPARATOR)  # total length of suffix

    # API URLs
    STAC_API_URL = getenv("STAC_API_URL")
    PYGEOAPI_API_URL = getenv("PYGEOAPI_API_URL")

    # Demo vector tables
    VECTOR_TABLES = getenv("VECTOR_TABLES")
    DEMO_VECTOR_TABLES = cfg["demo"]["DEMO_VECTOR_TABLES"]
    if VECTOR_TABLES is None:
        VECTOR_TABLES = [t.strip() for t in DEMO_VECTOR_TABLES.split(",") if t.strip()]

    # Data acquisition
    INPUT_DATA_PATH = cfg["paths"]["INPUT_DATA_PATH"]

    RASTER_COG_PATH = cfg["paths"]["RASTER_COG_PATH"]

    # PostgreSQL (PostGIS)
    POSTGRES_USER = getenv("POSTGRES_USER")
    POSTGRES_PASSWORD = getenv("POSTGRES_PASS")
    POSTGRES_HOST = getenv("POSTGRES_HOST")
    POSTGRES_PORT = int(getenv("POSTGRES_PORT", 5432))
    POSTGRES_DB = getenv("POSTGRES_DBNAME")
    POSTGRES_MAX_NAME_LENGTH = 50  # Value should be >= 7, and < 63

    # DuckDB
    DUCKDB_DATABASE = getenv("DUCKDB_DATABASE", "/data/duckdb/eoapi.duckdb")
    DUCKDB_DATA_DIR = getenv("DUCKDB_DATA_DIR", "/data/duckdb")

    # Ports
    PYGEOAPI_API_PORT = int(getenv("PYGEOAPI_API_PORT", 5000))
    STAC_API_PORT = int(getenv("STAC_API_PORT", 8081))
    RASTER_API_PORT = int(getenv("RASTER_API_PORT", 8082))
    VECTOR_API_PORT = int(getenv("VECTOR_API_PORT", 8083))
    FRONTEND_PORT = int(getenv("FRONTEND_PORT", 8085))
