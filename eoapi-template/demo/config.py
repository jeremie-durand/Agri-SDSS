# eoapi-template/demo/config.py
from os import getenv
from pathlib import Path

from dotenv import load_dotenv


class Config:
    """Project configuration loaded from environment variables."""

    # Load environment variables from .env at project root
    project_root = Path(__file__).parents[2]
    dotenv_path = project_root / ".env"
    load_dotenv(dotenv_path=dotenv_path)

    # PostgreSQL (PostGIS)
    POSTGRES_USER = getenv("POSTGRES_USER")
    POSTGRES_PASSWORD = getenv("POSTGRES_PASSWORD")
    POSTGRES_HOST = getenv("POSTGRES_HOST")
    POSTGRES_PORT = int(getenv("POSTGRES_PORT", 5432))
    POSTGRES_DB = getenv("POSTGRES_DB")

    # DuckDB
    DUCKDB_DATABASE = getenv("DUCKDB_DATABASE", "data/eoapi.duckdb")
    DUCKDB_DATA_DIR = getenv("DUCKDB_DATA_DIR", "/app/data")
    DUCKDB_API_URL = getenv("DUCKDB_API_URL")

    # Vector tables
    VECTOR_TABLES_RAW = getenv(
        "VECTOR_TABLES", "sud_du_quebec_4326,bdppad_2024_4326_sample_stac"
    )  # Demo data
    if VECTOR_TABLES_RAW:
        VECTOR_TABLES = [
            t.strip() for t in VECTOR_TABLES_RAW.split(",") if t.strip()
        ]  # Split by comma and strip whitespace
    else:
        VECTOR_TABLES = []  # No vector tables defined

    # Raster data
    RASTER_SOURCE_PATH = getenv("RASTER_SOURCE_PATH", "/data")
    RASTER_HARMONIZED_PATH = getenv("RASTER_HARMONIZED_PATH", "/data/raster_harmonized")
    RASTER_COG_PATH = getenv("RASTER_COG_PATH", "/data/raster_cog")
    RASTER_URL_PREFIX = getenv("RASTER_URL_PREFIX", "http://host.docker.internal:8001/")

    # STAC
    MY_DOCKER_IP = getenv("MY_DOCKER_IP", "host.docker.internal")
    STAC_COLLECTION_ID = "my-collection"  # Hardcoded for now
    STAC_API_URL = getenv("STAC_API_URL")

    # pygeoapi
    PYGEOAPI_API_URL = getenv("PYGEOAPI_API_URL")

    # Global properties
    GLOBAL_CRS = int(getenv("GLOBAL_CRS", 4326))  # Default to EPSG:4326 if not set
    PROJ_LIB = getenv("PROJ_LIB", "/usr/share/proj")  # Path to PROJ data directory, used for raster processing
