import re
from dataclasses import dataclass
from enum import Enum
from typing import Dict, Iterable


# ---------------------------------------------------------------
# Pipeline ingestion and processing mappings
# ---------------------------------------------------------------
class SupportedVectorFormats(Enum):
    """Supported vector file formats."""

    SHP = ".shp"
    GEOJSON = ".geojson"
    GPKG = ".gpkg"
    GDB = ".gdb"
    CSV = ".csv"


class SupportedRasterFormats(Enum):
    """Supported raster file formats."""

    TIF = ".tif"
    TIFF = ".tiff"


@dataclass
class ColumnName:
    canonical: str
    alias: Iterable[str] | str | None = None

    def __post_init__(self):
        if isinstance(self.alias, str):
            self.alias = [self.alias]
        if self.alias is None:
            self.alias = []
        self.alias = [a.lower() for a in self.alias]
        self.canonical = self.canonical.lower()

    def all_names(self) -> set[str]:
        """Return the canonical name plus every alias, all lowercase."""
        return {self.canonical, *self.alias}


class ColumnMappings(Enum):
    """Column mappings for various data formats."""

    GID = ColumnName(
        canonical="gid", alias=["id", "id_station", "station_id", "no", "identif"]
    )
    GEOMETRY = ColumnName(canonical="geometry", alias="geom")
    DATETIME = ColumnName(
        canonical="datetime",
        alias=[
            "acq_date",
            "date",
            "timestamp",
            "TIFFTAG_DATETIME",
            "ACQUISITION_DATE",
            "ACQ_DATE",
            "DATE_MAJ",
            "date_maj",
            "an",
        ],
    )
    FILE_URL = ColumnName(canonical="file_url")
    METADATA = ColumnName(canonical="metadata", alias="properties")
    BBOX = ColumnName(canonical="bbox")
    LATITUDE = ColumnName(canonical="latitude", alias=["lat", "y"])
    LONGITUDE = ColumnName(canonical="longitude", alias=["lon", "long", "longi", "x"])
    DESCRIPTION = ColumnName(
        canonical="description", alias=["desc", "reftyppar", "DESCR_SOL"]
    )

    @staticmethod
    def find(norm_col: str) -> "ColumnMappings | None":
        """Find the ColumnMappings member for a given normalized column name.

        Args:
            norm_col (str): The normalized column name to look up.

        Returns:
            ColumnMappings | None: The corresponding ColumnMappings member, or None if not found.
        """
        norm_col = norm_col.lower().strip()

        for mapping in ColumnMappings:
            info = mapping.value

            # Check aliases
            if norm_col in info.alias:
                return mapping

            # Check canonical
            if norm_col == info.canonical:
                return mapping

        return None


class AttributeNullValues(Enum):
    """Null/NA values for normalization."""

    EMPTY_STRING = ""
    NA_LOWER = "na"
    NA_TITLE = "Na"
    NA_UPPER = "NA"
    NA_SLASH_LOWER = "n/a"
    NA_SLASH_UPPER = "N/A"
    NONE = None


class CSVDataRegistryForSourceCRS(Enum):
    """CSV data registry for source CRS."""

    STATIONS_HYDROMETRIQUES = ("stations_hydrometriques", "EPSG:4326")
    RESEAU_AGROMETEO = ("reseau_agrometeo", "EPSG:4326")
    QUEBEC_4326 = ("quebec_4326", "EPSG:4326")  # Test
    QUEBEC_32198 = ("quebec_32198", "EPSG:32198")  # Test


class RasterTargetCRSOverrides(Enum):
    """Per-dataset target CRS overrides for raster reprojection.

    A raster's target CRS defaults to the batch's global CRS. An override applies
    when the raster file stem contains the associated keyword (case-insensitive),
    letting a dataset be harmonized to its own native CRS instead — e.g. SIIGSOL
    is already published in EPSG:32198 (NAD83 / Quebec Lambert), so reprojecting
    it to the global default would force an avoidable resampling pass.
    """

    SIIGSOL = ("siigsol", "EPSG:32198")


# ---------------------------------------------------------------
# Layers to skip during data ingestion
# ---------------------------------------------------------------
class QGISInternalLayers(Enum):
    """QGIS internal layer names to skip during ingestion."""

    LAYER_STYLES = "layer_styles"
    QGIS_PROJECTS = "qgis_projects"


# ---------------------------------------------------------------
# Pipeline processing limits
# ---------------------------------------------------------------
CHUNK_SIZE = 50_000


# ---------------------------------------------------------------
# Database and data storage harmonization
# ---------------------------------------------------------------


class PostgresDataTypes(Enum):
    """PostgreSQL data types for STAC columns."""

    INTEGER_PRIMARY_KEY = "INTEGER PRIMARY KEY"
    TEXT_PRIMARY_KEY = "TEXT PRIMARY KEY"
    TEXT = "TEXT"
    TIMESTAMP = "TIMESTAMP"
    TIMESTAMP_WITH_TIMEZONE = "TIMESTAMP WITH TIME ZONE"
    JSONB = "JSONB"
    FLOAT_ARRAY = "FLOAT[]"
    FLOAT8_ARRAY = "FLOAT8[]"
    GEOMETRY_4326 = "geometry(Geometry, 4326)"
    POLYGON_4326 = "geometry(Polygon, 4326)"
    POLYGON_4326_UPPER = "geometry(POLYGON, 4326)"


class VectorPostGISColumns(Enum):
    """Columns required in PostGIS for vector data."""

    GID = PostgresDataTypes.INTEGER_PRIMARY_KEY.value
    GEOMETRY = PostgresDataTypes.GEOMETRY_4326.value
    DATETIME = PostgresDataTypes.TIMESTAMP_WITH_TIMEZONE.value
    METADATA = PostgresDataTypes.JSONB.value


class RasterStacColumns(Enum):
    """Columns required in PostGIS for raster STAC."""

    GID = PostgresDataTypes.TEXT_PRIMARY_KEY.value
    DATETIME = PostgresDataTypes.TIMESTAMP_WITH_TIMEZONE.value
    BBOX = PostgresDataTypes.FLOAT_ARRAY.value
    GEOMETRY = PostgresDataTypes.POLYGON_4326.value
    FILE_URL = PostgresDataTypes.TEXT.value
    METADATA = PostgresDataTypes.JSONB.value


class SqlAlchemyTypeConfig:
    """Configuration for SQLAlchemy type mappings."""

    def __init__(self, postgres_type: str, sa_type: str, **kwargs):
        self.postgres_type = postgres_type
        self.sa_type = sa_type
        for key, value in kwargs.items():
            setattr(self, key, value)

    def to_dict(self) -> dict:
        """Convert to dictionary representation."""
        return {
            "postgres_type": self.postgres_type,
            "sa_type": self.sa_type,
            **{
                k: v
                for k, v in self.__dict__.items()
                if k not in ("postgres_type", "sa_type")
            },
        }


class SqlAlchemyTypes(Enum):
    """SQLAlchemy type mappings."""

    INTEGER_PRIMARY_KEY = SqlAlchemyTypeConfig(
        postgres_type=PostgresDataTypes.INTEGER_PRIMARY_KEY.value,
        sa_type="Integer",
        primary_key=True,
        autoincrement=False,
    )
    TEXT_PRIMARY_KEY = SqlAlchemyTypeConfig(
        postgres_type=PostgresDataTypes.TEXT_PRIMARY_KEY.value,
        sa_type="Text",
        primary_key=True,
    )
    TEXT = SqlAlchemyTypeConfig(
        postgres_type=PostgresDataTypes.TEXT.value,
        sa_type="Text",
    )
    TIMESTAMP = SqlAlchemyTypeConfig(
        postgres_type=PostgresDataTypes.TIMESTAMP.value,
        sa_type="TIMESTAMP",
        timezone=False,
    )
    TIMESTAMP_WITH_TIMEZONE = SqlAlchemyTypeConfig(
        postgres_type=PostgresDataTypes.TIMESTAMP_WITH_TIMEZONE.value,
        sa_type="TIMESTAMP",
        timezone=True,
    )
    JSONB = SqlAlchemyTypeConfig(
        postgres_type=PostgresDataTypes.JSONB.value,
        sa_type="JSONB",
    )
    FLOAT_ARRAY = SqlAlchemyTypeConfig(
        postgres_type=PostgresDataTypes.FLOAT_ARRAY.value,
        sa_type="ARRAY",
        item_type="Float",
    )
    FLOAT8_ARRAY = SqlAlchemyTypeConfig(
        postgres_type=PostgresDataTypes.FLOAT8_ARRAY.value,
        sa_type="ARRAY",
        item_type="Float",
    )
    GEOMETRY_4326 = SqlAlchemyTypeConfig(
        postgres_type=PostgresDataTypes.GEOMETRY_4326.value,
        sa_type="Geometry",
        geometry_type="GEOMETRY",
        srid=4326,
    )
    POLYGON_4326_UPPER = SqlAlchemyTypeConfig(
        postgres_type=PostgresDataTypes.POLYGON_4326_UPPER.value,
        sa_type="Geometry",
        geometry_type="POLYGON",
        srid=4326,
    )
    POLYGON_4326 = SqlAlchemyTypeConfig(
        postgres_type=PostgresDataTypes.POLYGON_4326.value,
        sa_type="Geometry",
        geometry_type="POLYGON",
        srid=4326,
    )


# ---------------------------------------------------------------
# STAC templates
# ---------------------------------------------------------------
STAC_ITEM_TEMPLATE = {
    "type": "Feature",
    "stac_version": "1.0.0",
    "stac_extensions": [],
    "id": None,
    "geometry": None,
    "bbox": None,
    "properties": {
        "datetime": None,
        "created": None,
        "updated": None,
        "title": None,
        "data_type": None,
        "source": None,
    },
    "links": [],
    "assets": {},
    "collection": None,
}


STAC_COLLECTION_TEMPLATE = {
    "id": None,
    "description": "No description provided for this collection.",
    "extent": {
        "spatial": {
            "bbox": [[-180.0, -90.0, 180.0, 90.0]],
        },
        "temporal": {
            "interval": [[None, None]],
        },
    },
    "title": None,
    "license": "na",
}


# ---------------------------------------------------------------
# Constants and defaults
# ---------------------------------------------------------------


class NamingPatterns(Enum):
    """Naming convention patterns."""

    PATTERN_GDF_NAME = r"[^0-9a-zA-Z_]+"
    PATTERN_DUCKDB_NAME = r"^[A-Za-z0-9_]+$"
    PATTERN_RASTER_NAME = r"[^0-9a-zA-Z_]+"
    VALID_PG_IDENTIFIER = r"^[A-Za-z_][A-Za-z0-9_]*$"


class DatePatterns(Enum):
    PATTERNS = [
        re.compile(r"(?P<ymdhms>\d{8}[_T-]?\d{6})"),
        re.compile(r"(?P<ymd>\d{8})"),
    ]
    YEAR_PATTERN = re.compile(r"(?P<year>(19|20)\d{2})(?!\d)")


class DefaultMetadata(Enum):
    """Default metadata values."""

    SOURCE = "unknown"
    DESCRIPTION = "No description provided"
    DATETIME = "1970-01-01T00:00:00Z"

    @classmethod
    def get_defaults(cls) -> Dict[str, str]:
        """Get default metadata as a dictionary."""
        return {
            "source": cls.SOURCE.value,
            "description": cls.DESCRIPTION.value,
        }
