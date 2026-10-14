from datetime import datetime as dt
from datetime import timezone
from pathlib import Path
from typing import Optional
from urllib.parse import quote

import yaml
from gis_pipeline.core.exceptions import ConfigurationError
from pydantic_settings import BaseSettings, SettingsConfigDict

config_paths = [
    Path(__file__).resolve().parents[2] / "config.yaml",  # Docker context
    Path(__file__).resolve().parents[3] / "config.yaml",  # Local context
]
CONFIG_PATH = None
for path in config_paths:
    if path.exists():
        CONFIG_PATH = path
        break

if CONFIG_PATH is None:
    raise ConfigurationError(
        f"config.yaml not found in: {[str(p) for p in config_paths]}"
    )

with CONFIG_PATH.open(mode="r") as f:
    cfg = yaml.safe_load(f)


# ---------------------------------------------------------------------------
# Environment-variable settings — validated at import time via pydantic-settings.
# POSTGRES_PASS is the only required field; all others carry Docker-friendly defaults.
# ---------------------------------------------------------------------------


class _DatabaseSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="")

    POSTGRES_USER: str = "agri_sdss"
    POSTGRES_PASS: str  # required — container refuses to start without it
    POSTGRES_HOST: str = "database"
    POSTGRES_PORT: int = 5432
    POSTGRES_DBNAME: str = "agri_sdss"


class _ApiSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="")

    STAC_API_URL: Optional[str] = None
    VECTOR_API_URL: Optional[str] = None
    STAC_API_PORT: int = 8081
    RASTER_API_PORT: int = 8082
    VECTOR_API_PORT: int = 8083
    PROCESS_API_PORT: int = 5000
    FRONTEND_PORT: int = 8085
    HOST_PROTOCOL: str = "http"
    HOST_URL: str = "localhost"


class _StorageSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="")

    DUCKDB_DATABASE: str = "/data/duckdb/eoapi.duckdb"
    DUCKDB_DATA_DIR: str = "/data/duckdb"


_db = _DatabaseSettings()
_api = _ApiSettings()
_storage = _StorageSettings()

# Public route serving COG files (home nginx, static, byte-range capable).
COG_ROUTE = "/cog"

# Public route proxying TiTiler, which renders the same COGs on demand.
RASTER_API_ROUTE = "/raster-api"

# Path the COG directory is mounted at inside the raster-api container; this is
# what TiTiler expects in its ``url`` query parameter.
RASTER_API_DATA_DIR = "/data"

# Tile grid identifier TiTiler 2.x requires in the TileJSON path.
TILE_MATRIX_SET = "WebMercatorQuad"


def public_base_url() -> str:
    """Return the deployment's public origin, without a trailing slash."""
    api = _ApiSettings()
    return f"{api.HOST_PROTOCOL}://{api.HOST_URL}".rstrip("/")


def public_cog_url(cog_path: str | Path) -> str:
    """Return the public, absolute URL of a COG file.

    Accepts local paths only and is deliberately not idempotent over URLs it
    has already built, unlike the process-api builders: not unquoting keeps
    filenames containing a literal ``%`` intact.

    Args:
        cog_path: Local path to the COG; only its basename is used.
    """
    return f"{public_base_url()}{COG_ROUTE}/{quote(Path(cog_path).name)}"


def _raster_api_url(cog_path: str | Path) -> str:
    """Return the ``url`` query value TiTiler resolves a COG against."""
    return f"{RASTER_API_DATA_DIR}/{quote(Path(cog_path).name)}"


def _render_query(rescale: str | None, bidx: int | None) -> str:
    """Return the query suffix telling TiTiler how to render a COG."""
    suffix = f"&bidx={bidx}" if bidx else ""
    return f"{suffix}&rescale={rescale}" if rescale else suffix


def public_preview_url(
    cog_path: str | Path, rescale: str | None = None, bidx: int | None = None
) -> str:
    """Return the public TiTiler PNG preview URL of a COG.

    Args:
        cog_path: Local path to the COG; only its basename is used.
        rescale: Optional ``min,max`` pair for a raster whose values are not
            already in a displayable range.
        bidx: Optional 1-based band to render, required for a COG TiTiler
            cannot encode whole (see ``GeoprocessingRaster._render_params``).
    """
    return (
        f"{public_base_url()}{RASTER_API_ROUTE}/cog/preview.png"
        f"?url={_raster_api_url(cog_path)}{_render_query(rescale, bidx)}"
    )


def public_tilejson_url(
    cog_path: str | Path, rescale: str | None = None, bidx: int | None = None
) -> str:
    """Return the public TiTiler TileJSON URL of a COG.

    Args:
        cog_path: Local path to the COG; only its basename is used.
        rescale: Optional ``min,max`` pair, carried into the tile URLs the
            TileJSON advertises so tiles match the preview.
        bidx: Optional 1-based band, carried into the tile URLs for the same
            reason, so tiles and preview show the same band.
    """
    return (
        f"{public_base_url()}{RASTER_API_ROUTE}/cog/{TILE_MATRIX_SET}"
        f"/tilejson.json?url={_raster_api_url(cog_path)}"
        f"{_render_query(rescale, bidx)}"
    )


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
    HASH_HEX_LENGTH = 6  # Number of hex characters taken from the MD5 hexdigest (6 chars = 24-bit collision resistance).
    HASH_SEPARATOR = "_"  # Character inserted between the truncated identifier and its hash suffix (e.g. 'my_table_a3f9c1').
    HASH_SUFFIX_LENGTH = HASH_HEX_LENGTH + len(
        HASH_SEPARATOR
    )  # Chars reserved for suffix when truncating DB identifiers.

    # Logs
    LOG_DIR = cfg["paths"]["LOG_DIR"]

    # API URLs
    STAC_API_URL = _api.STAC_API_URL
    VECTOR_API_URL = _api.VECTOR_API_URL

    # Data acquisition
    INPUT_DATA_PATH = cfg["paths"]["INPUT_DATA_PATH"]
    RASTER_COG_PATH = cfg["paths"]["RASTER_COG_PATH"]

    # PostgreSQL (PostGIS)
    POSTGRES_USER = _db.POSTGRES_USER
    POSTGRES_PASSWORD = _db.POSTGRES_PASS
    POSTGRES_HOST = _db.POSTGRES_HOST
    POSTGRES_PORT = _db.POSTGRES_PORT
    POSTGRES_DB = _db.POSTGRES_DBNAME
    POSTGRES_MAX_NAME_LENGTH = 50  # Value should be >= 7, and < 63

    # DuckDB
    DUCKDB_DATABASE = _storage.DUCKDB_DATABASE
    DUCKDB_DATA_DIR = _storage.DUCKDB_DATA_DIR

    # Ports
    PROCESS_API_PORT = _api.PROCESS_API_PORT
    STAC_API_PORT = _api.STAC_API_PORT
    RASTER_API_PORT = _api.RASTER_API_PORT
    VECTOR_API_PORT = _api.VECTOR_API_PORT
    FRONTEND_PORT = _api.FRONTEND_PORT
