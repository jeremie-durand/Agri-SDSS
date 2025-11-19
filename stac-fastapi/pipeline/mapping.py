from enum import Enum
from typing import Any, Dict, Set, Tuple


# ---------------------------------------------------------------
# Pipeline ingestion
# ---------------------------------------------------------------
class SupportedVectorFormats(Enum):
    """Supported vector file formats."""

    SHP = ".shp"
    GEOJSON = ".geojson"
    GPKG = ".gpkg"

    @classmethod
    def get_extensions(cls) -> Set[str]:
        """Get all supported extensions as a set."""
        return {format.value for format in cls}


class SupportedRasterFormats(Enum):
    """Supported raster file formats."""

    TIF = ".tif"
    TIFF = ".tiff"

    @classmethod
    def get_extensions(cls) -> Set[str]:
        """Get all supported extensions as a set."""
        return {format.value for format in cls}


class StacColumns(Enum):
    """STAC column names."""

    GID = "gid"
    START_DATE = "start_date"
    END_DATE = "end_date"
    FILE_URL = "file_url"
    METADATA = "metadata"
    GEOMETRY = "geometry"
    BBOX = "bbox"


class ColumnAliases(Enum):
    """Column aliases for STAC columns."""

    GID = ("ID", "id")
    START_DATE = ("Date_Acquisition", "date")
    END_DATE = ("Date_Acquisition", "date")
    FILE_URL = ()
    METADATA = ("Metadata", "properties", "Properties")

    @classmethod
    def get_aliases_dict(cls) -> Dict[str, Tuple[str, ...]]:
        """Get aliases as a dictionary for backward compatibility."""
        return {
            StacColumns.GID.value: cls.GID.value,
            StacColumns.START_DATE.value: cls.START_DATE.value,
            StacColumns.END_DATE.value: cls.END_DATE.value,
            StacColumns.FILE_URL.value: cls.FILE_URL.value,
            StacColumns.METADATA.value: cls.METADATA.value,
        }


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


class VectorStacColumns(Enum):
    """Columns required in PostGIS for vector STAC."""

    GID = PostgresDataTypes.INTEGER_PRIMARY_KEY.value
    GEOMETRY = PostgresDataTypes.GEOMETRY_4326.value
    START_DATE = PostgresDataTypes.TIMESTAMP_WITH_TIMEZONE.value
    END_DATE = PostgresDataTypes.TIMESTAMP_WITH_TIMEZONE.value
    FILE_URL = PostgresDataTypes.TEXT.value
    METADATA = PostgresDataTypes.JSONB.value

    @classmethod
    def get_columns_dict(cls) -> Dict[str, str]:
        """Get columns as a dictionary for backward compatibility."""
        return {
            StacColumns.GID.value: cls.GID.value,
            StacColumns.GEOMETRY.value: cls.GEOMETRY.value,
            StacColumns.START_DATE.value: cls.START_DATE.value,
            StacColumns.END_DATE.value: cls.END_DATE.value,
            StacColumns.FILE_URL.value: cls.FILE_URL.value,
            StacColumns.METADATA.value: cls.METADATA.value,
        }


class RasterStacColumns(Enum):
    """Columns required in PostGIS for raster STAC."""

    GID = PostgresDataTypes.TEXT_PRIMARY_KEY.value
    START_DATE = PostgresDataTypes.TIMESTAMP_WITH_TIMEZONE.value
    END_DATE = PostgresDataTypes.TIMESTAMP_WITH_TIMEZONE.value
    BBOX = PostgresDataTypes.FLOAT_ARRAY.value
    GEOMETRY = PostgresDataTypes.POLYGON_4326.value
    FILE_URL = PostgresDataTypes.TEXT.value
    METADATA = PostgresDataTypes.JSONB.value

    @classmethod
    def get_columns_dict(cls) -> Dict[str, str]:
        """Get columns as a dictionary for backward compatibility."""
        return {
            StacColumns.GID.value: cls.GID.value,
            StacColumns.START_DATE.value: cls.START_DATE.value,
            StacColumns.END_DATE.value: cls.END_DATE.value,
            StacColumns.BBOX.value: cls.BBOX.value,
            StacColumns.GEOMETRY.value: cls.GEOMETRY.value,
            StacColumns.FILE_URL.value: cls.FILE_URL.value,
            StacColumns.METADATA.value: cls.METADATA.value,
        }


class VectorColumnsMapping(Enum):
    """Default mapping of GeoDataFrame columns to STAC columns."""

    GID = StacColumns.GID.value
    GEOMETRY = StacColumns.GEOMETRY.value
    START_DATE = StacColumns.START_DATE.value
    END_DATE = StacColumns.END_DATE.value
    FILE_URL = StacColumns.FILE_URL.value
    METADATA = StacColumns.METADATA.value

    @classmethod
    def get_mapping_dict(cls) -> Dict[str, str]:
        """Get mapping as a dictionary for backward compatibility."""
        return {member.name.lower(): member.value for member in cls}


class AttributeNullValues(Enum):
    """Null/NA values for normalization."""

    EMPTY_STRING = ""
    NA_LOWER = "na"
    NA_TITLE = "Na"
    NA_UPPER = "NA"
    NA_SLASH_LOWER = "n/a"
    NA_SLASH_UPPER = "N/A"
    NONE = None

    @classmethod
    def get_null_mapping(cls) -> Dict[Any, None]:
        """Get null mapping as a dictionary for backward compatibility."""
        return {member.value: None for member in cls}


class SqlAlchemyTypes(Enum):
    """SQLAlchemy type mappings."""

    INTEGER_PRIMARY_KEY = {
        "type": "Integer",
        "primary_key": True,
        "autoincrement": True,
    }
    TEXT_PRIMARY_KEY = {"type": "Text", "primary_key": True}
    TEXT = {"type": "Text"}
    TIMESTAMP = {"type": "TIMESTAMP", "timezone": False}
    TIMESTAMP_WITH_TIMEZONE = {"type": "TIMESTAMP", "timezone": True}
    JSONB = {"type": "JSONB"}
    FLOAT_ARRAY = {"type": "ARRAY", "item_type": "Float"}
    FLOAT8_ARRAY = {"type": "ARRAY", "item_type": "Float"}
    GEOMETRY_4326 = {
        "type": "Geometry",
        "geometry_type": "GEOMETRY",
        "srid": 4326,
    }
    POLYGON_4326_UPPER = {
        "type": "Geometry",
        "geometry_type": "POLYGON",
        "srid": 4326,
    }
    POLYGON_4326 = {
        "type": "Geometry",
        "geometry_type": "POLYGON",
        "srid": 4326,
    }

    @classmethod
    def get_type_mapping(cls) -> Dict[str, Dict[str, Any]]:
        """Get type mapping as a dictionary for backward compatibility."""
        return {
            PostgresDataTypes.INTEGER_PRIMARY_KEY.value: cls.INTEGER_PRIMARY_KEY.value,
            PostgresDataTypes.TEXT_PRIMARY_KEY.value: cls.TEXT_PRIMARY_KEY.value,
            PostgresDataTypes.TEXT.value: cls.TEXT.value,
            PostgresDataTypes.TIMESTAMP.value: cls.TIMESTAMP.value,
            PostgresDataTypes.TIMESTAMP_WITH_TIMEZONE.value: cls.TIMESTAMP_WITH_TIMEZONE.value,
            PostgresDataTypes.JSONB.value: cls.JSONB.value,
            PostgresDataTypes.FLOAT_ARRAY.value: cls.FLOAT_ARRAY.value,
            PostgresDataTypes.FLOAT8_ARRAY.value: cls.FLOAT8_ARRAY.value,
            PostgresDataTypes.GEOMETRY_4326.value: cls.GEOMETRY_4326.value,
            PostgresDataTypes.POLYGON_4326_UPPER.value: cls.POLYGON_4326_UPPER.value,
            PostgresDataTypes.POLYGON_4326.value: cls.POLYGON_4326.value,
        }


# ---------------------------------------------------------------
# STAC templates and defaults
# ---------------------------------------------------------------
STAC_ITEM_TEMPLATE = {
    "stac_version": "1.0.0",
    "type": "Feature",
    "geometry": None,
    "bbox": None,
    "datetime": None,
    "properties": {
        "datetime": None,
        "created": None,
        "updated": None,
        "title": None,
        "data_type": None,
        "source": None,
    },
}


STAC_COLLECTION_TEMPLATE = {
    "id": None,
    "description": "No description provided",
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
# Constants
# ---------------------------------------------------------------


class NamingPatterns(Enum):
    """Naming convention patterns."""

    PATTERN_GDF_NAME = r"[^0-9a-zA-Z_]+"
    PATTERN_DUCKDB_NAME = r"^[A-Za-z0-9_]+$"
    PATTERN_RASTER_NAME = r"[^0-9a-zA-Z_]+"
    VALID_PG_IDENTIFIER = r"^[A-Za-z_][A-Za-z0-9_]*$"


class DefaultMetadata(Enum):
    """Default metadata values."""

    SOURCE = "unknown"
    DESCRIPTION = "No description provided"

    @classmethod
    def get_defaults(cls) -> Dict[str, str]:
        """Get default metadata as a dictionary."""
        return {
            "source": cls.SOURCE.value,
            "description": cls.DESCRIPTION.value,
        }
