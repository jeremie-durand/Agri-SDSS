"""Configuration and constants for Vector API.

This module centralizes endpoint paths and configuration to reduce duplication
and maintenance costs across the application and documentation.
"""

import os

# Endpoint prefixes
POSTGIS_PREFIX = "/postgis"
PARQUET_PREFIX = "/parquet"

# Collection endpoint paths
COLLECTIONS_PATH = "/collections"
POSTGIS_COLLECTIONS = f"{POSTGIS_PREFIX}{COLLECTIONS_PATH}"
PARQUET_COLLECTIONS = f"{PARQUET_PREFIX}{COLLECTIONS_PATH}"

# API metadata
API_TITLE = "Vector API"
API_VERSION = "1.0.0"
API_DESCRIPTION = "Combined OGC API Features for PostGIS and GeoParquet data sources"

# Set TiPg settings before it is imported anywhere.
os.environ.setdefault("TIPG_NAME", API_TITLE)
os.environ.setdefault("TIPG_ROOT_PATH", POSTGIS_PREFIX)

# Data source descriptions
POSTGIS_DESCRIPTION = "Traditional database-backed collections via TiPg"
PARQUET_DESCRIPTION = "File-based collections with auto-discovery"

# CORS configuration
_raw_cors_origins = os.getenv("VECTOR_API_CORS_ORIGINS", "")
CORS_ORIGINS: list[str] = [
    origin.strip() for origin in _raw_cors_origins.split(",") if origin.strip()
]
# Credentials can only be sent when explicit origins are configured;
# the wildcard "*" origin is incompatible with credentials per the CORS spec.
CORS_ALLOW_CREDENTIALS: bool = bool(CORS_ORIGINS) and "*" not in CORS_ORIGINS

# Parquet collections materialized into a persistent, RTree-indexed on-disk
# DuckDB table (see vector_api/materialize.py and docs/DEPLOYMENT.md). A
# collection only takes the materialized path once its .duckdb file has
# actually been built by scripts/build_duckdb_spatial_index.py --
# DuckDBManager falls back to read_parquet() otherwise, so listing a
# collection here ahead of the first build is safe.
_raw_materialized_collections = os.getenv("PARQUET_MATERIALIZED_COLLECTIONS", "")
PARQUET_MATERIALIZED_COLLECTIONS: frozenset[str] = frozenset(
    c.strip() for c in _raw_materialized_collections.split(",") if c.strip()
)

# Endpoint documentation
ENDPOINTS = {
    "postgis": {
        "prefix": POSTGIS_PREFIX,
        "collections": POSTGIS_COLLECTIONS,
        "description": POSTGIS_DESCRIPTION,
        "title": "PostGIS Collections API",
        "long_description": "OGC API Features style endpoints for PostGIS database tables",
    },
    "parquet": {
        "prefix": PARQUET_PREFIX,
        "collections": PARQUET_COLLECTIONS,
        "description": PARQUET_DESCRIPTION,
        "title": "Parquet Collections API",
        "long_description": "OGC API Features style endpoints for GeoParquet files",
    },
}
