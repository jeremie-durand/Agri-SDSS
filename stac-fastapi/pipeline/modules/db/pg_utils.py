import json
import re
from typing import Mapping, Optional

import geopandas as gpd
import pandas as pd
import sqlalchemy
from geoalchemy2 import Geometry
from pipeline.config import Config
from pipeline.logging_setup import handle_error, setup_logging
from pipeline.mapping import (
    NamingPatterns,
    PostgresDataTypes,
    RasterStacColumns,
    SqlAlchemyTypes,
    VectorPostGISColumns,
)
from pydantic import BaseModel
from shapely.geometry import box
from sqlalchemy.dialects.postgresql import JSONB

logger = setup_logging()


class PostGISManager:
    """Manager class for PostGIS database operations."""

    def __init__(
        self,
        user: str = Config.POSTGRES_USER,
        password: str = Config.POSTGRES_PASSWORD,
        host: str = Config.POSTGRES_HOST,
        port: int = Config.POSTGRES_PORT,
        db: str = Config.POSTGRES_DB,
        engine: Optional[sqlalchemy.engine.Engine] = None,
    ):
        """Initialize PostGIS manager with database connection.

        Args:
            user: Database username.
            password: Database password.
            host: Database host.
            port: Database port.
            db: Database name.
            engine: Optional existing SQLAlchemy engine. If provided, connection params are ignored.
        """
        if engine is not None:
            self.engine = engine
            logger.info("PostGIS manager initialized with existing engine.")
        else:
            try:
                self.engine = sqlalchemy.create_engine(
                    f"postgresql+psycopg://{user}:{password}@{host}:{port}/{db}"
                )
                logger.info(f"Successfully connected to PostGIS database '{db}'")
            except Exception:
                error_msg = f"Error connecting to PostGIS database '{db}'"
                handle_error(logger=logger, error_msg=error_msg, exc_class=RuntimeError)

        # Store connection info for reference
        self.connection_info = {
            "host": host,
            "port": port,
            "database": db,
            "user": user,
        }

        self._check_postgis_extension()
        self._check_postgis_variables()

    def _check_postgis_extension(self) -> None:
        """Check if PostGIS extension is enabled in the database."""
        try:
            with self.engine.connect() as conn:
                result = conn.execute(
                    sqlalchemy.text(
                        "SELECT extname FROM pg_extension WHERE extname = 'postgis';"
                    )
                )
                if result.fetchone() is None:
                    error_msg = "PostGIS extension is not enabled in the database"
                    handle_error(
                        logger=logger, error_msg=error_msg, exc_class=RuntimeError
                    )
                else:
                    logger.info("PostGIS extension is enabled in the database")
        except Exception:
            error_msg = "Error checking PostGIS extension"
            handle_error(logger=logger, error_msg=error_msg, exc_class=RuntimeError)

    def _check_postgis_variables(self) -> None:
        """Check if PostGIS-related configuration variables are valid."""
        try:
            if Config.POSTGRES_MAX_NAME_LENGTH < 7:
                error_msg = (
                    "POSTGRES_MAX_NAME_LENGTH must be greater than or equal to 7"
                )
                handle_error(logger=logger, error_msg=error_msg, exc_class=ValueError)
            if Config.POSTGRES_MAX_NAME_LENGTH >= 63:
                error_msg = "POSTGRES_MAX_NAME_LENGTH must be less than 63"
                handle_error(logger=logger, error_msg=error_msg, exc_class=ValueError)
            logger.info("PostGIS configuration variables are valid")
        except Exception:
            error_msg = "Error checking PostGIS variables"
            handle_error(logger=logger, error_msg=error_msg, exc_class=RuntimeError)

    def close(self) -> None:
        """Close the database connection."""
        self.engine.dispose()
        logger.info("PostGIS database connection closed")

    def __enter__(self):
        """Support for context manager."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.close()

    def _convert_pg_mapping_to_sqlalchemy(self, pg_mapping: dict) -> dict:
        """Convert a Postgres column mapping to a SQLAlchemy column mapping.

        Args:
            pg_mapping: Dictionary mapping column names to Postgres data types.

        Returns:
            Dictionary mapping column names to SQLAlchemy data types/configurations.
        """
        sqlalchemy_mapping = {}

        # For each Postgres type string, try to find the corresponding SqlAlchemyTypes member.
        # Avoid using member.value as a dict key (unhashable). Instead search members.
        for col, pg_type in pg_mapping.items():
            found = False

            for member in SqlAlchemyTypes:
                member_value = getattr(member, "value", None)

                # direct string match (member.value is a string)
                if isinstance(member_value, str) and member_value == pg_type:
                    # prefer returning a dict config when available via indexing
                    try:
                        sqlalchemy_mapping[col] = SqlAlchemyTypes[member.name].value
                    except Exception:
                        sqlalchemy_mapping[col] = member_value
                    found = True
                    break

                # if member.value is a dict, try common keys that might store the Postgres representation
                if isinstance(member_value, dict):
                    if (
                        member_value.get("postgres_type") == pg_type
                        or member_value.get("postgres") == pg_type
                        or member_value.get("pg") == pg_type
                    ):
                        sqlalchemy_mapping[col] = member_value
                        found = True
                        break

                # fallback: match by enum member name (e.g. "TEXT", "INTEGER")
                if member.name == pg_type:
                    sqlalchemy_mapping[col] = member_value
                    found = True
                    break

                # last resort: stringified member value
                if str(member_value) == pg_type:
                    sqlalchemy_mapping[col] = member_value
                    found = True
                    break

            if not found:
                raise ValueError(f"Unknown Postgres type: {pg_type}")

        return sqlalchemy_mapping

    def _create_table_from_mapping(
        self,
        table_name: str,
        column_mapping: dict[str, str],
        schema: Optional[str] = None,
    ) -> None:
        """Create a PostGIS table based on a provided column mapping.

        Args:
            table_name: Name of the PostGIS table to create.
            column_mapping: Dictionary mapping column names to their SQL types.
            schema: Optional schema name (e.g., "public").
        """
        pattern_obj = NamingPatterns.VALID_PG_IDENTIFIER.value
        if isinstance(pattern_obj, str):
            try:
                compiled_pattern = re.compile(pattern_obj)
            except re.error as e:
                error_msg = f"Invalid regex pattern for validating table names: {e}"
                handle_error(logger=logger, error_msg=error_msg, exc_class=ValueError)
        else:
            compiled_pattern = pattern_obj

        if not compiled_pattern.match(table_name):
            # Provide the original pattern string when available for clearer error messages
            pattern_text = getattr(
                NamingPatterns.VALID_PG_IDENTIFIER,
                "value",
                getattr(
                    NamingPatterns.VALID_PG_IDENTIFIER, "pattern", str(compiled_pattern)
                ),
            )
            error_msg = (
                f"Invalid table name '{table_name}'. Must match regex {pattern_text}"
            )
            handle_error(logger=logger, error_msg=error_msg, exc_class=ValueError)

        try:
            metadata = sqlalchemy.MetaData(schema=schema)
            columns = []

            for col_name, col_config in column_mapping.items():

                col_type = col_config["type"]

                # Define SQLAlchemy column based on type
                if col_type == "Integer":
                    column = sqlalchemy.Column(
                        col_name,
                        sqlalchemy.Integer,
                        primary_key=col_config.get("primary_key", False),
                        autoincrement=col_config.get("autoincrement", False),
                    )

                elif col_type == "Text":
                    column = sqlalchemy.Column(
                        col_name,
                        sqlalchemy.Text,
                        primary_key=col_config.get("primary_key", False),
                    )

                elif col_type == "TIMESTAMP":
                    column = sqlalchemy.Column(
                        col_name,
                        sqlalchemy.TIMESTAMP(
                            timezone=col_config.get("timezone", False)
                        ),
                    )

                elif col_type == "JSONB":
                    column = sqlalchemy.Column(col_name, JSONB)

                elif col_type == "ARRAY":
                    item_type = getattr(sqlalchemy, col_config["item_type"])
                    column = sqlalchemy.Column(col_name, sqlalchemy.ARRAY(item_type))

                elif col_type == "Geometry":
                    column = sqlalchemy.Column(
                        col_name,
                        Geometry(
                            geometry_type=col_config["geometry_type"],
                            srid=col_config["srid"],
                        ),
                    )

                else:
                    raise ValueError(f"Unsupported SQLAlchemy type: {col_type}")

                columns.append(column)

            # Create the table
            table = sqlalchemy.Table(table_name, metadata, *columns)
            metadata.create_all(self.engine, tables=[table])

            logger.info(f"Table '{table_name}' created successfully from mapping.")

        except Exception as exc:
            error_msg = f"Error creating table '{table_name}' from mapping: {exc}"
            handle_error(logger=logger, error_msg=error_msg, exc_class=RuntimeError)

    def _build_column_mapping_from_gdf(self, gdf: gpd.GeoDataFrame) -> dict:
        """
        Build a Postgres column mapping for all columns found in the GeoDataFrame.

        The mapping process is as follows:
        - Start from the default STAC-required columns.
        - Infer types for remaining fields:
        datetime -> TIMESTAMP WITH TIME ZONE
        object/dict/list -> JSONB
        float -> TEXT (safe default)
        int -> TEXT (safe default)

        Args:
            gdf: The GeoDataFrame to build the mapping from.

        Returns:
            A dictionary mapping column names to Postgres data types.
        """
        # Create initial mapping
        mapping = {col.name.lower(): col.value for col in VectorPostGISColumns}

        # Normalize incoming column names
        gdf_cols_normalized = {col.lower(): col for col in gdf.columns}

        # Helper: infer a Postgres type from a pandas series
        def infer_pg_type(series: pd.Series):
            dtype = series.dtype

            # Datetime
            if pd.api.types.is_datetime64_any_dtype(dtype):
                return PostgresDataTypes.TIMESTAMP_WITH_TIMEZONE.value

            # Integer → TEXT (safe)
            if pd.api.types.is_integer_dtype(dtype):
                return PostgresDataTypes.TEXT.value

            # Float → TEXT (safe default)
            if pd.api.types.is_float_dtype(dtype):
                return PostgresDataTypes.TEXT.value

            # Object → maybe JSONB ?
            if pd.api.types.is_object_dtype(dtype):
                non_null = series.dropna()
                if non_null.empty:
                    return PostgresDataTypes.TEXT.value

                # % of values that are dict/list
                sample = non_null.head(50).tolist()
                structural = sum(isinstance(x, (dict, list)) for x in sample)
                proportion = structural / len(sample)

                # >70% looks like actual JSON → use JSONB
                if proportion >= 0.7:
                    return PostgresDataTypes.JSONB.value

                return PostgresDataTypes.TEXT.value

            # Fallback
            return PostgresDataTypes.TEXT.value

        # Infer types for other columns
        for norm_col, original_col in gdf_cols_normalized.items():

            # Skip existing defaults
            if norm_col in mapping:
                continue

            # Geometry
            if norm_col == "geometry":
                mapping[norm_col] = PostgresDataTypes.GEOMETRY_4326.value
                continue

            # Infer other data types
            mapping[norm_col] = infer_pg_type(gdf[original_col])

        return mapping

    def insert_gdf(
        self, gdf: gpd.GeoDataFrame, table_name: str, override_method: str = "replace"
    ) -> None:
        """Insert a GeoDataFrame into a PostGIS table.

        Args:
            gdf: The GeoDataFrame to insert.
            table_name: Name of the PostGIS table to insert into.
            override_method: Behavior when the table already exists.
                Options: 'replace', 'append'.
        """
        try:
            if not table_name:
                raise ValueError("Invalid table name")

            inspector = sqlalchemy.inspect(self.engine)

            # If table does not exist, build mapping and create it
            if not inspector.has_table(table_name):
                pg_mapping = self._build_column_mapping_from_gdf(gdf)
                sqlalchemy_mapping = self._convert_pg_mapping_to_sqlalchemy(pg_mapping)
                self._create_table_from_mapping(
                    table_name=table_name, column_mapping=sqlalchemy_mapping
                )

            gdf.to_postgis(name=table_name, con=self.engine, if_exists=override_method)

        except Exception:
            error_msg = "Error inserting GeoDataFrame into PostGIS"
            handle_error(logger=logger, error_msg=error_msg, exc_class=RuntimeError)

    def insert_cog_metadata(self, metadata: dict, table_name: str) -> None:
        """Insert COG metadata into a PostGIS table.

        Args:
            metadata: Dictionary containing COG metadata.
            table_name: Name of the PostGIS table to insert into.
        """
        try:
            # --- normalize metadata to plain dict ------------------------------------------------
            if isinstance(metadata, BaseModel):
                # pydantic v2 -> model_dump, v1 -> dict
                metadata = (
                    metadata.model_dump()
                    if hasattr(metadata, "model_dump")
                    else metadata.dict()
                )
            elif not isinstance(metadata, Mapping):
                # try to build a simple mapping from attributes
                try:
                    metadata = {
                        k: getattr(metadata, k)
                        for k in [
                            "id",
                            "bbox",
                            "file_url",
                            "start_date",
                            "end_date",
                            "metadata",
                            "datetime",
                        ]
                        if hasattr(metadata, k)
                    }
                except Exception:
                    # leave as-is; subsequent validation will raise
                    pass

            # Coerce bbox to a list of floats if present (e.g. tuple, numpy types)
            if "bbox" in metadata and isinstance(metadata["bbox"], (list, tuple)):
                try:
                    metadata["bbox"] = [float(x) for x in metadata["bbox"]]
                except Exception:
                    # keep original and let validation below raise
                    pass

            # Ensure id exists as a primitive
            if "id" in metadata and not isinstance(metadata["id"], (str, int)):
                metadata["id"] = str(metadata["id"])

            # Verify if table exists
            if not sqlalchemy.inspect(self.engine).has_table(table_name):
                logger.info(f"Table '{table_name}' does not exist. Creating it.")
                self._create_table_from_mapping(
                    table_name=table_name,
                    column_mapping=self._convert_pg_mapping_to_sqlalchemy(
                        RasterStacColumns
                    ),
                )

            essential_fields = ["id", "bbox", "file_url"]
            for field in essential_fields:
                if field not in metadata:
                    error_msg = f"Missing required field '{field}' in metadata"
                    handle_error(
                        logger=logger, error_msg=error_msg, exc_class=ValueError
                    )

            datetime = metadata.get("datetime", Config.DEFAULT_DATETIME)

            # Verify bbox format
            if (
                not isinstance(metadata["bbox"], (list, tuple))
                or len(metadata["bbox"]) != 4
            ):
                error_msg = "bbox must be a list/tuple of 4 coordinates [minx, miny, maxx, maxy]"
                handle_error(logger=logger, error_msg=error_msg, exc_class=ValueError)

            with self.engine.begin() as conn:
                insert_stmt = sqlalchemy.text(
                    f"""
                    INSERT INTO {table_name} (gid, datetime, bbox, geometry, file_url, metadata)
                    VALUES (:gid, :datetime, :bbox, ST_GeomFromText(:geometry, 4326), :file_url, :metadata)
                    ON CONFLICT (gid) DO UPDATE
                    SET datetime = EXCLUDED.datetime,
                        bbox = EXCLUDED.bbox,
                        geometry = EXCLUDED.geometry,
                        file_url = EXCLUDED.file_url,
                        metadata = EXCLUDED.metadata;
                    """
                )
                conn.execute(
                    insert_stmt,
                    {
                        "gid": metadata["id"],
                        "datetime": datetime,
                        "bbox": metadata["bbox"],
                        "geometry": box(*metadata["bbox"]).wkt,
                        "file_url": metadata.get("file_url", ""),
                        "metadata": json.dumps(metadata.get("metadata", {})),
                    },
                )

            logger.info(
                f"COG metadata inserted into PostGIS table '{table_name}' successfully."
            )

        except Exception:
            error_msg = "Error inserting COG metadata into PostGIS"
            handle_error(logger=logger, error_msg=error_msg, exc_class=RuntimeError)

    def read_data(self, table_name: str) -> gpd.GeoDataFrame:
        """Read spatial data from a PostGIS table into a GeoDataFrame.

        Args:
            table_name: Name of the table to read.

        Returns:
            GeoDataFrame containing the spatial data.
        """
        try:
            metadata = sqlalchemy.MetaData()
            table = sqlalchemy.Table(table_name, metadata, autoload_with=self.engine)

            stmt = sqlalchemy.select(
                table.c.gid,
                table.c.geometry,
                table.c.datetime,
                table.c.bbox,
                table.c.file_url,
                table.c.metadata,
            )

            gdf = gpd.read_postgis(stmt, self.engine, geom_col="geometry")
            logger.info(f"Data read from PostGIS table '{table_name}' successfully.")
            return gdf
        except Exception:
            error_msg = "Error reading data from PostGIS"
            handle_error(logger=logger, error_msg=error_msg, exc_class=RuntimeError)
