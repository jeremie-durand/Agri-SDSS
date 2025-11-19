import json
import re
from datetime import datetime, timezone
from typing import Mapping, Optional

import geopandas as gpd
import sqlalchemy
from geoalchemy2 import Geometry
from pipeline.config import Config
from pipeline.logging_setup import handle_error, setup_logging
from pipeline.mapping import (
    NamingPatterns,
    RasterStacColumns,
    SqlAlchemyTypes,
    VectorStacColumns,
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
        return False

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

            for col_name, sql_type in column_mapping.items():
                col_config = SqlAlchemyTypes.get_type_mapping().get(sql_type)
                if not col_config:
                    error_msg = f"Unknown SQL type: {sql_type}"
                    handle_error(
                        logger=logger, error_msg=error_msg, exc_class=ValueError
                    )

                # Construire la colonne selon le type
                if col_config["type"] == "Integer":
                    column = sqlalchemy.Column(
                        col_name,
                        sqlalchemy.Integer,
                        primary_key=col_config.get("primary_key", False),
                        autoincrement=col_config.get("autoincrement", False),
                    )
                elif col_config["type"] == "Text":
                    column = sqlalchemy.Column(
                        col_name,
                        sqlalchemy.Text,
                        primary_key=col_config.get("primary_key", False),
                    )
                elif col_config["type"] == "TIMESTAMP":
                    column = sqlalchemy.Column(
                        col_name,
                        sqlalchemy.TIMESTAMP(
                            timezone=col_config.get("timezone", False)
                        ),
                    )
                elif col_config["type"] == "JSONB":
                    column = sqlalchemy.Column(col_name, JSONB)
                elif col_config["type"] == "ARRAY":
                    item_type = getattr(sqlalchemy, col_config["item_type"])
                    column = sqlalchemy.Column(col_name, sqlalchemy.ARRAY(item_type))
                elif col_config["type"] == "Geometry":
                    column = sqlalchemy.Column(
                        col_name,
                        Geometry(
                            geometry_type=col_config["geometry_type"],
                            srid=col_config["srid"],
                        ),
                    )
                else:
                    error_msg = f"Unsupported column type: {col_config['type']}"
                    handle_error(
                        logger=logger, error_msg=error_msg, exc_class=ValueError
                    )

                columns.append(column)

            table = sqlalchemy.Table(table_name, metadata, *columns)
            metadata.create_all(self.engine, tables=[table])
            logger.info(f"Table '{table_name}' created successfully from mapping.")

        except Exception:
            error_msg = f"Error creating table '{table_name}' from mapping"
            handle_error(logger=logger, error_msg=error_msg, exc_class=RuntimeError)

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
            # Verify if table exists
            if not sqlalchemy.inspect(self.engine).has_table(table_name):
                logger.warning(f"Table '{table_name}' does not exist. Creating it.")
                self._create_table_from_mapping(
                    table_name=table_name,
                    column_mapping=VectorStacColumns.get_columns_dict(),
                )

            # Detect geometry column
            geometry_column = None
            for col in ["geometry"]:
                if col in gdf.columns:
                    geometry_column = col
                    break
            if geometry_column is None:
                error_msg = "GeoDataFrame must contain a 'geometry' column"
                handle_error(logger=logger, error_msg=error_msg, exc_class=ValueError)

            if "gid" not in gdf.columns:
                gdf = gdf.reset_index(drop=True)
                gdf["gid"] = gdf.index + 1

            # Write the GeoDataFrame to PostGIS
            gdf.to_postgis(
                name=table_name,
                con=self.engine,
                if_exists=override_method,
                index=False,
            )
            logger.info(
                f"GeoDataFrame inserted into PostGIS table '{table_name}' successfully."
            )
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
                    column_mapping=RasterStacColumns.get_columns_dict(),
                )

            essential_fields = ["id", "bbox", "file_url"]
            for field in essential_fields:
                if field not in metadata:
                    error_msg = f"Missing required field '{field}' in metadata"
                    handle_error(
                        logger=logger, error_msg=error_msg, exc_class=ValueError
                    )

            start_date = metadata.get("start_date")
            end_date = metadata.get("end_date")

            if not start_date and "datetime" in metadata:
                start_date = metadata["datetime"]
            if not end_date and "datetime" in metadata:
                end_date = metadata["datetime"]

            if not start_date:
                start_date = datetime.now(timezone.utc)
            if not end_date:
                end_date = datetime.now(timezone.utc)

            if hasattr(start_date, "isoformat"):
                start_date = start_date.isoformat()
            if hasattr(end_date, "isoformat"):
                end_date = end_date.isoformat()

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
                    INSERT INTO {table_name} (gid, start_date, end_date, bbox, geometry, file_url, metadata)
                    VALUES (:gid, :start_date, :end_date, :bbox, ST_GeomFromText(:geometry, 4326), :file_url, :metadata)
                    ON CONFLICT (gid) DO UPDATE
                    SET start_date = EXCLUDED.start_date,
                        end_date = EXCLUDED.end_date,
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
                        "start_date": start_date,
                        "end_date": end_date,
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
                table.c.start_date,
                table.c.end_date,
                table.c.file_url,
                table.c.metadata,
            )

            gdf = gpd.read_postgis(stmt, self.engine, geom_col="geometry")
            logger.info(f"Data read from PostGIS table '{table_name}' successfully.")
            return gdf
        except Exception:
            error_msg = "Error reading data from PostGIS"
            handle_error(logger=logger, error_msg=error_msg, exc_class=RuntimeError)
