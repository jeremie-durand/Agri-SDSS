"""Environment configuration for mos-pygeoapi processes.

All environment variables consumed by this service are declared here as typed
pydantic-settings classes so that missing or mis-typed values are caught at
startup rather than at the first affected request.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class DatabaseConfig(BaseSettings):
    """PostGIS connection parameters.

    POSTGRES_PASS is the only required field — the container will refuse to
    start if it is absent. All other fields have Docker-compose-friendly
    defaults.
    """

    model_config = SettingsConfigDict(env_prefix="")

    POSTGRES_HOST: str = "database"
    POSTGRES_PORT: int = 5432
    POSTGRES_USER: str = "agri_sdss"
    POSTGRES_PASS: str
    POSTGRES_DBNAME: str = "agri_sdss"

    def to_conn_params(self) -> dict:
        """Return a dict suitable for passing to psycopg.connect()."""
        return {
            "host": self.POSTGRES_HOST,
            "port": self.POSTGRES_PORT,
            "dbname": self.POSTGRES_DBNAME,
            "user": self.POSTGRES_USER,
            "password": self.POSTGRES_PASS,
        }


class FarmConfig(BaseSettings):
    """PostGIS farm table schema."""

    model_config = SettingsConfigDict(env_prefix="")

    FARM_TABLE_NAME: str = "public.bdppad_2024_4326_sample_stac"
    FARM_GEOMETRY_COLUMN: str = "geom"
    FARM_ID_COLUMN: str = "gid"


class ApiConfig(BaseSettings):
    """URLs for downstream internal service APIs."""

    model_config = SettingsConfigDict(env_prefix="")

    STAC_API_URL: str = "http://stac-api:8081"
    RASTER_API_PORT: int = 8082


class StorageConfig(BaseSettings):
    """File-system paths for mounted data volumes."""

    model_config = SettingsConfigDict(env_prefix="")

    DUCKDB_DATA_DIR: str = "/data/duckdb"
    LIDAR_OUTPUT_DIR: str = "/data"
