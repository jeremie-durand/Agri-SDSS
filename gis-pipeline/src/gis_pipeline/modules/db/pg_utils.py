import json
import re
from typing import Mapping, Optional

import geopandas as gpd
import pandas as pd
import sqlalchemy
import structlog
from geoalchemy2 import Geometry
from gis_pipeline.core.config import Config
from gis_pipeline.core.logging_setup import handle_error
from gis_pipeline.services.mapping import (
    NamingPatterns,
    PostgresDataTypes,
    RasterStacColumns,
    SqlAlchemyTypes,
    VectorPostGISColumns,
)
from pydantic import BaseModel
from shapely.geometry import box
from sqlalchemy.dialects.postgresql import JSONB

logger = structlog.get_logger()


class ConnectionManager:
    """Owns the SQLAlchemy engine and validates PostGIS startup conditions."""

    def __init__(
        self,
        user: str = Config.POSTGRES_USER,
        password: str = Config.POSTGRES_PASSWORD,
        host: str = Config.POSTGRES_HOST,
        port: int = Config.POSTGRES_PORT,
        db: str = Config.POSTGRES_DB,
        engine: Optional[sqlalchemy.engine.Engine] = None,
    ):
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


class GIDValidator:
    """Validates and repairs the gid column in GeoDataFrames."""

    @staticmethod
    def _repair_null_gids(gid_numeric: pd.Series) -> pd.Series:
        """Replace null entries in a numeric GID series with conflict-free integers.

        Args:
            gid_numeric: Numeric series that may contain NaN for invalid entries.

        Returns:
            Series with nulls replaced by unique int64 values not already present.
        """
        # Collect the set of already-valid integer IDs to avoid conflicts
        valid_ids: set[int] = set(gid_numeric.dropna().astype("int64").tolist())
        # Start new IDs above the current maximum (or from 1 if all are null)
        next_id = int(gid_numeric.max()) + 1 if valid_ids else 1
        new_gids = gid_numeric.copy()
        for idx in gid_numeric[gid_numeric.isnull()].index:
            while next_id in valid_ids:
                next_id += 1
            new_gids.at[idx] = float(next_id)
            valid_ids.add(next_id)
            next_id += 1
        return new_gids.astype("int64")

    @staticmethod
    def _validate_gid_column(gdf: gpd.GeoDataFrame) -> None:
        """Validate that the gid column contains unique, valid integer values.

        Args:
            gdf: GeoDataFrame to validate.

        Raises:
            ValueError: If gid column is missing, has duplicates, null values, or non-integer values.
        """
        if "gid" not in gdf.columns:
            error_msg = "GID column is missing from GeoDataFrame. Ensure _ensure_gid_column() is called before validation."
            handle_error(logger=logger, error_msg=error_msg, exc_class=ValueError)

        gid_series = gdf["gid"]

        # Check for null values
        if gid_series.isnull().any():
            null_count = gid_series.isnull().sum()
            error_msg = f"GID column contains {null_count} null value(s). All GID values must be non-null."
            handle_error(logger=logger, error_msg=error_msg, exc_class=ValueError)

        # Check for duplicates
        duplicates = gid_series[gid_series.duplicated()]
        if not duplicates.empty:
            dup_values = duplicates.unique().tolist()[:10]
            dup_values_str = ", ".join(
                map(str, dup_values)
            )  # Convert to string for logging
            error_msg = f"GID column contains duplicate values: {dup_values_str}... ({len(duplicates)} total duplicates)"
            handle_error(logger=logger, error_msg=error_msg, exc_class=ValueError)

        # Check for non-integer values
        try:
            gid_as_int = pd.to_numeric(gid_series, errors="raise")
            if not pd.api.types.is_integer_dtype(gid_as_int):
                # Check if float values are actually integers (e.g., 1.0, 2.0)
                if not (gid_as_int == gid_as_int.astype(int)).all():
                    error_msg = "GID column contains non-integer values. All GID values must be integers."
                    handle_error(
                        logger=logger, error_msg=error_msg, exc_class=ValueError
                    )

            # Check for negative values
            if (gid_as_int < 0).any():
                error_msg = "GID column contains negative values. All GID values must be positive integers."
                handle_error(logger=logger, error_msg=error_msg, exc_class=ValueError)
        except (ValueError, TypeError) as e:
            error_msg = f"GID column contains invalid values that cannot be converted to integers: {e}"
            handle_error(logger=logger, error_msg=error_msg, exc_class=ValueError)

        logger.info(f"GID validation passed: {len(gdf)} unique GID values.")

    @staticmethod
    def _ensure_gid_column(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
        """Ensure GeoDataFrame has a valid gid column.

        Priority order for GID source:
        1. Existing 'gid' column (after column renaming)
        2. DataFrame index if it's a valid integer sequence
        3. Generate sequential integers starting from 1

        Args:
            gdf: GeoDataFrame to process.

        Returns:
            GeoDataFrame with valid gid column.
        """
        # If gid column already exists (from column renaming), validate and use it
        if "gid" in gdf.columns:
            try:
                # Convert to numeric first, check for nulls before casting to int
                gid_numeric = pd.to_numeric(gdf["gid"], errors="coerce")
                if gid_numeric.isnull().any():
                    null_count = int(gid_numeric.isnull().sum())
                    logger.warning(
                        f"Existing gid column contains {null_count} invalid value(s). "
                        "Preserving valid IDs and generating unique IDs for invalid entries."
                    )
                    gdf["gid"] = GIDValidator._repair_null_gids(gid_numeric)
                    logger.info(
                        f"GID column repaired: {null_count} missing value(s) filled "
                        "with unique IDs while preserving existing valid IDs."
                    )
                else:
                    gdf["gid"] = gid_numeric.astype("int64")
                    logger.info("Using existing gid column from source data.")
            except Exception as e:
                logger.warning(
                    f"Could not convert existing gid column: {e}. Generating sequential IDs."
                )
                gdf["gid"] = range(1, len(gdf) + 1)
        # Check if index could be used as gid
        elif isinstance(gdf.index, pd.RangeIndex) and gdf.index.start >= 0:
            if gdf.index.start == 0:
                logger.info("Using 0-based DataFrame index as gid.")
                gdf["gid"] = gdf.index + 1  # Start from 1 instead of 0
            else:
                logger.info(
                    "Using non-zero-based DataFrame index as gid without shifting values."
                )
                gdf["gid"] = gdf.index
        else:
            # Generate sequential integers
            logger.info("Generating sequential gid values starting from 1.")
            gdf["gid"] = range(1, len(gdf) + 1)

        GIDValidator._validate_gid_column(gdf)

        return gdf


class TypeMapper:
    """Converts between Postgres and SQLAlchemy type representations."""

    @staticmethod
    def _create_sqlalchemy_column(
        col_name: str, sa_config: dict | object
    ) -> sqlalchemy.Column:
        """Create a SQLAlchemy column from a type configuration.

        Args:
            col_name: Name of the column.
            sa_config: Configuration dict or SqlAlchemyTypeConfig object.

        Returns:
            A SQLAlchemy Column instance.

        Raises:
            ValueError: If the SQLAlchemy type is not supported.
        """
        if hasattr(sa_config, "to_dict"):
            config_dict = sa_config.to_dict()
        elif isinstance(sa_config, dict):
            config_dict = sa_config
        else:
            raise ValueError(f"Invalid config type: {type(sa_config)}")

        col_type = config_dict.get("sa_type")

        if col_type is None:
            raise ValueError(
                f"Missing 'sa_type' in column configuration: {config_dict}"
            )

        # Dynamically select SQLAlchemy type based on sa_type
        type_handlers = {
            "Integer": lambda cfg: sqlalchemy.Integer,
            "Text": lambda cfg: sqlalchemy.Text,
            "TIMESTAMP": lambda cfg: sqlalchemy.TIMESTAMP(
                timezone=cfg.get("timezone", True)
            ),
            "JSONB": lambda cfg: JSONB,
            "ARRAY": lambda cfg: sqlalchemy.ARRAY(
                getattr(sqlalchemy, cfg["item_type"])
            ),
            "Geometry": lambda cfg: Geometry(
                geometry_type=cfg.get("geometry_type", "GEOMETRY"),
                srid=cfg.get("srid", Config.GLOBAL_CRS),
            ),
        }

        handler = type_handlers.get(col_type) or type_handlers.get(
            col_type.lower() if col_type.lower() == "geometry" else None
        )

        if handler is None:
            raise ValueError(f"Unsupported SQLAlchemy type: {col_type}")

        column_type = handler(config_dict)

        # Build column kwargs
        column_kwargs = {}
        if "primary_key" in config_dict:
            column_kwargs["primary_key"] = True
            # For primary keys, use explicit autoincrement value from config if present,
            # otherwise default to False to preserve user-provided IDs (e.g. gid).
            column_kwargs["autoincrement"] = config_dict.get("autoincrement", False)
        elif "autoincrement" in config_dict:
            column_kwargs["autoincrement"] = config_dict["autoincrement"]

        return sqlalchemy.Column(col_name, column_type, **column_kwargs)

    @staticmethod
    def _convert_pg_mapping_to_sqlalchemy(pg_mapping: dict) -> dict:
        """Convert a Postgres column mapping to a SQLAlchemy column mapping.

        Args:
            pg_mapping: Dictionary mapping column names to Postgres data types.

        Returns:
            Dictionary mapping column names to SQLAlchemy data types/configurations.
        """
        sqlalchemy_mapping = {}

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

                # if member.value is a SqlAlchemyTypeConfig object
                if hasattr(member_value, "postgres_type"):
                    if member_value.postgres_type == pg_type:
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

    @staticmethod
    def _build_column_mapping_from_gdf(gdf: gpd.GeoDataFrame) -> dict:
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

            # Special handling for gid column
            if norm_col == "gid":
                # Check if GeoDataFrame has actual gid data (not auto-generated)
                if "gid" in gdf.columns and not gdf["gid"].isnull().all():
                    # Use default VectorPostGISColumns.GID config (will disable auto-increment in table creation)
                    logger.info("Detected existing gid data. Will preserve source IDs.")
                else:
                    # Keep default with auto-increment
                    pass
                continue

            # Skip other existing defaults
            if norm_col in mapping:
                continue

            if norm_col == "geometry":
                mapping[norm_col] = PostgresDataTypes.GEOMETRY_4326.value
                continue

            # Infer other data types
            mapping[norm_col] = infer_pg_type(gdf[original_col])

        return mapping


class SchemaBuilder:
    """Handles DDL operations: table creation, schema validation, primary key management."""

    def __init__(self, engine: sqlalchemy.engine.Engine) -> None:
        self.engine = engine

    @staticmethod
    def _validate_and_split_table_name(table_name: str) -> tuple[str, str]:
        """Validate table name and split into schema and table components.

        Validates both schema and table name against PostgreSQL identifier pattern
        to prevent SQL injection attacks.

        Args:
            table_name: Name of the table (optionally schema-qualified, e.g., 'public.my_table').

        Returns:
            Tuple of (schema, table) where schema defaults to 'public' if not specified.

        Raises:
            ValueError: If table name or schema name is invalid.
        """
        # Compile the validation pattern
        pattern_obj = NamingPatterns.VALID_PG_IDENTIFIER.value
        if isinstance(pattern_obj, str):
            try:
                compiled_pattern = re.compile(pattern_obj)
            except re.error as e:
                error_msg = f"Invalid regex pattern for validating table names: {e}"
                handle_error(logger=logger, error_msg=error_msg, exc_class=ValueError)
        else:
            compiled_pattern = pattern_obj

        # Extract schema and table name for individual validation
        schema, table = (
            table_name.split(".", 1) if "." in table_name else ("public", table_name)
        )

        # Validate both schema and table name
        pattern_text = NamingPatterns.VALID_PG_IDENTIFIER.value
        for name, identifier in [("schema", schema), ("table", table)]:
            if not compiled_pattern.match(identifier):
                error_msg = f"Invalid {name} name '{identifier}'. Must match regex {pattern_text}"
                handle_error(logger=logger, error_msg=error_msg, exc_class=ValueError)

        return schema, table

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
                # Use the dynamic column factory
                column = TypeMapper._create_sqlalchemy_column(col_name, col_config)
                columns.append(column)

            # Create the table
            table = sqlalchemy.Table(table_name, metadata, *columns)
            metadata.create_all(self.engine, tables=[table])

            logger.info(f"Table '{table_name}' created successfully from mapping.")

        except Exception as exc:
            error_msg = f"Error creating table '{table_name}' from mapping: {exc}"
            handle_error(logger=logger, error_msg=error_msg, exc_class=RuntimeError)

    def _add_primary_key_constraint(self, table_name: str) -> None:
        """Add PRIMARY KEY constraint on gid column for a PostGIS table.

        This ensures TiPg can detect gid as the primary key for clean feature IDs.
        The operation is idempotent - existing PRIMARY KEY constraints are dropped first.

        Args:
            table_name: Name of the table (optionally schema-qualified, e.g., 'public.my_table').

        Raises:
            Warning: If PRIMARY KEY constraint cannot be added (logged, does not raise).
        """
        # Validate table name to prevent SQL injection
        schema, table = SchemaBuilder._validate_and_split_table_name(table_name)

        try:
            # Build qualified table name for SQL statements
            qualified_table_sql = (
                f'"{schema}"."{table}"' if "." in table_name else f'"{table}"'
            )
            constraint_name = f"{table}_pkey"

            # Use a fresh connection to avoid transaction issues
            with self.engine.begin() as conn:
                # Step 1: Drop existing PRIMARY KEY if any (idempotent)
                drop_pk = sqlalchemy.text(f"""
                    ALTER TABLE {qualified_table_sql}
                    DROP CONSTRAINT IF EXISTS "{constraint_name}" CASCADE
                    """)
                conn.execute(drop_pk)

                # Step 2: Ensure gid column is NOT NULL (required for PRIMARY KEY)
                set_not_null = sqlalchemy.text(f"""
                    ALTER TABLE {qualified_table_sql}
                    ALTER COLUMN gid SET NOT NULL
                    """)
                conn.execute(set_not_null)
                logger.info(f"Set gid column to NOT NULL for table '{table_name}'.")

                # Step 3: Add PRIMARY KEY constraint with explicit name
                add_pk = sqlalchemy.text(f"""
                    ALTER TABLE {qualified_table_sql}
                    ADD CONSTRAINT "{constraint_name}" PRIMARY KEY (gid)
                    """)
                conn.execute(add_pk)
                logger.info(
                    f"Added PRIMARY KEY constraint '{constraint_name}' on gid for table '{table_name}'."
                )

        except sqlalchemy.exc.SQLAlchemyError as pk_error:
            logger.warning(
                f"Could not add PRIMARY KEY to table '{table_name}': {pk_error}"
            )

    def add_fk_constraints(self, fk_defs: list[dict]) -> None:
        """Add UNIQUE + FK constraints derived from a GeoPackage FK schema.

        For each definition:
        1. Adds a UNIQUE constraint on the referenced column (required by PostgreSQL
           for any FK target that is not a primary key).
        2. Adds the FK constraint itself with NOT VALID so that pre-existing orphaned
           rows in the data do not abort ingestion.

        Both steps are idempotent: duplicate_object errors (pgcode 42710) are silently
        skipped. Other failures are logged as warnings per-constraint so one bad FK
        never blocks the rest.

        Args:
            fk_defs: List of {from_table, from_col, to_table, to_col} dicts, as
                returned by extract_gpkg_fk_schema().
        """
        for fk in fk_defs:
            from_table = fk["from_table"]
            from_col = fk["from_col"]
            to_table = fk["to_table"]
            to_col = fk["to_col"]

            uq_name = f"uq_{to_table}_{to_col}"[:63]
            fk_name = f"fk_{from_table}_{from_col}"[:63]

            # Step 1: UNIQUE constraint on referenced column
            try:
                with self.engine.begin() as conn:
                    conn.execute(
                        sqlalchemy.text(
                            f'ALTER TABLE "{to_table}" '
                            f'ADD CONSTRAINT "{uq_name}" UNIQUE ("{to_col}")'
                        )
                    )
                logger.info("gpkg_fk_unique_added", constraint=uq_name, table=to_table)
            except (
                sqlalchemy.exc.ProgrammingError,
                sqlalchemy.exc.IntegrityError,
            ) as exc:
                pgcode = getattr(exc.orig, "pgcode", None)
                if pgcode == "42710":
                    logger.debug("gpkg_fk_unique_already_exists", constraint=uq_name)
                elif pgcode == "23505":
                    logger.warning(
                        "gpkg_fk_unique_skipped_duplicate_data",
                        constraint=uq_name,
                        table=to_table,
                    )
                    continue
                else:
                    logger.warning(
                        "gpkg_fk_unique_failed",
                        constraint=uq_name,
                        table=to_table,
                        error=str(exc),
                    )
                    continue  # Cannot add FK without UNIQUE on the referenced column

            # Step 2: FK constraint NOT VALID
            try:
                with self.engine.begin() as conn:
                    conn.execute(
                        sqlalchemy.text(
                            f'ALTER TABLE "{from_table}" '
                            f'ADD CONSTRAINT "{fk_name}" '
                            f'FOREIGN KEY ("{from_col}") '
                            f'REFERENCES "{to_table}" ("{to_col}") '
                            f"NOT VALID"
                        )
                    )
                logger.info("gpkg_fk_constraint_added", constraint=fk_name)
            except sqlalchemy.exc.ProgrammingError as exc:
                if getattr(exc.orig, "pgcode", None) == "42710":
                    logger.debug("gpkg_fk_already_exists", constraint=fk_name)
                else:
                    logger.warning(
                        "gpkg_fk_constraint_failed",
                        constraint=fk_name,
                        from_table=from_table,
                        error=str(exc),
                    )


class DataInserter:
    """Handles data insertion and retrieval for PostGIS tables."""

    def __init__(self, engine: sqlalchemy.engine.Engine) -> None:
        self.engine = engine

    def _drop_incoming_fk_constraints(self, table_name: str) -> None:
        """Drop FK constraints on child tables that reference this table.

        Called before DROP TABLE (if_exists="replace") to prevent
        DependentObjectsStillExist errors on pipeline re-runs.
        """
        try:
            qualified = f"public.{table_name}"
            with self.engine.begin() as conn:
                rows = conn.execute(
                    sqlalchemy.text("""
                        SELECT c.conname,
                               quote_ident(n.nspname) || '.' || quote_ident(r.relname)
                                 AS child_table_quoted
                        FROM pg_constraint c
                        JOIN pg_class r ON r.oid = c.conrelid
                        JOIN pg_namespace n ON n.oid = r.relnamespace
                        WHERE c.confrelid = to_regclass(:qualified)
                          AND c.contype = 'f'
                    """),
                    {"qualified": qualified},
                ).fetchall()
            for conname, child_table_quoted in rows:
                with self.engine.begin() as conn:
                    conn.execute(
                        sqlalchemy.text(
                            f"ALTER TABLE {child_table_quoted}"
                            f' DROP CONSTRAINT IF EXISTS "{conname}"'
                        )
                    )
                logger.debug(
                    "fk_dropped_before_replace",
                    constraint=conname,
                    child_table=child_table_quoted,
                    target_table=table_name,
                )
        except Exception as exc:
            logger.warning(
                "fk_drop_before_replace_failed", table=table_name, error=str(exc)
            )

    def _insert_geodataframe(
        self, gdf: gpd.GeoDataFrame, table_name: str, override_method: str
    ) -> None:
        """Insert a GeoDataFrame into PostGIS.

        Args:
            gdf: GeoDataFrame to insert (must have valid gid column).
            table_name: Name of the table in PostGIS.
            override_method: 'replace', 'append', or 'fail' behavior if table exists.

        Note:
            This method expects gdf to already have a valid gid column.
            Use insert_table_data() for automatic gid handling.
        """
        if override_method == "replace":
            self._drop_incoming_fk_constraints(table_name)

        if gdf.crs is None:
            logger.warning(
                f"GeoDataFrame for table '{table_name}' has no CRS defined. Fallback to DataFrame insertion."
            )
            # Convert to normal DataFrame
            df = gdf.copy()
            df["geometry"] = df["geometry"].apply(
                lambda geom: geom.wkt if geom is not None else None
            )
            # Insert as plain DataFrame
            df.to_sql(
                name=table_name,
                con=self.engine,
                if_exists=override_method,
                index=False,
            )
            logger.info(
                f"Fallback DataFrame inserted into PostGIS table '{table_name}'."
            )
            return

        if gdf.empty:
            logger.warning(
                f"GeoDataFrame for table '{table_name}' is empty. Creating empty table in PostGIS."
            )

        # Cast float64 columns whose non-null values are all whole numbers to
        # nullable Int64. This prevents type mismatches when appending chunks:
        # chunk 0 may have no NULLs (int64 → INTEGER table), while chunk 1+ may
        # have NULLs (float64 → "3.0" sent to INTEGER column → psycopg error).
        geom_col = gdf.geometry.name
        for col in gdf.select_dtypes(include=["float64"]).columns:
            if col == geom_col:
                continue
            non_null = gdf[col].dropna()
            if non_null.empty or (non_null % 1 == 0).all():
                gdf[col] = gdf[col].astype("Int64")

        logger.info(f"Inserting {len(gdf)} rows into PostGIS table '{table_name}'...")
        gdf.to_postgis(
            name=table_name,
            con=self.engine,
            if_exists=override_method,
            index=False,  # Explicitly use gid column, not DataFrame index
            chunksize=5000,
        )
        logger.info(
            f"GeoDataFrame inserted into PostGIS table '{table_name}' with preserved GID values."
        )

    def _insert_dataframe(
        self, df: pd.DataFrame, table_name: str, override_method: str
    ) -> None:
        """Insert a DataFrame into PostGIS.

        Args:
            df: DataFrame to insert.
            table_name: Name of the table in PostGIS.
            override_method: 'replace', 'append', or 'fail' behavior if table exists.
        """
        if override_method == "replace":
            self._drop_incoming_fk_constraints(table_name)

        if df.empty:
            logger.warning(
                f"Non-spatial DataFrame for table '{table_name}' is empty. Creating empty table in PostGIS."
            )

        df.to_sql(
            name=table_name,
            con=self.engine,
            if_exists=override_method,
            index=False,
        )
        logger.info(
            f"Non-spatial DataFrame inserted into PostGIS table '{table_name}'."
        )

    @staticmethod
    def _normalize_cog_metadata(metadata) -> dict:
        """Coerce metadata to a plain dict with normalized bbox and id types.

        Args:
            metadata: Raw metadata — BaseModel, Mapping, or attribute-bearing object.

        Returns:
            dict: Normalized metadata dict.
        """
        if isinstance(metadata, BaseModel):
            metadata = (
                metadata.model_dump()
                if hasattr(metadata, "model_dump")
                else metadata.dict()
            )
        elif not isinstance(metadata, Mapping):
            try:
                metadata = vars(metadata)
            except TypeError:
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

        return metadata

    @staticmethod
    def _validate_cog_metadata(metadata: dict) -> None:
        """Check that all required COG metadata fields are present and valid.

        Args:
            metadata: Normalized metadata dict.

        Raises:
            ValueError: If a required field is missing or bbox has wrong shape.
        """
        essential_fields = ["id", "bbox", "file_url"]
        for field in essential_fields:
            if field not in metadata:
                error_msg = f"Missing required field '{field}' in metadata"
                handle_error(logger=logger, error_msg=error_msg, exc_class=ValueError)

        # Verify bbox format
        if (
            not isinstance(metadata["bbox"], (list, tuple))
            or len(metadata["bbox"]) != 4
        ):
            error_msg = (
                "bbox must be a list/tuple of 4 coordinates [minx, miny, maxx, maxy]"
            )
            handle_error(logger=logger, error_msg=error_msg, exc_class=ValueError)

    def _ensure_cog_table(self, table_name: str) -> None:
        """Create the COG metadata table if it does not already exist.

        Args:
            table_name: Qualified or unqualified table name.
        """
        if not sqlalchemy.inspect(self.engine).has_table(table_name):
            logger.info(f"Table '{table_name}' does not exist. Creating it.")
            SchemaBuilder(self.engine)._create_table_from_mapping(
                table_name=table_name,
                column_mapping=TypeMapper._convert_pg_mapping_to_sqlalchemy(
                    RasterStacColumns
                ),
            )

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
        except Exception as exc:
            error_msg = f"Error reading data from PostGIS: {exc}"
            handle_error(logger=logger, error_msg=error_msg, exc_class=RuntimeError)


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
        self._conn = ConnectionManager(user, password, host, port, db, engine)
        self.engine = self._conn.engine
        self.connection_info = self._conn.connection_info
        self._schema = SchemaBuilder(self.engine)
        self._inserter = DataInserter(self.engine)

    def close(self) -> None:
        """Close the database connection."""
        self._conn.close()

    def __enter__(self):
        """Support for context manager."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.close()

    # --- Shims: delegate to helper classes, preserve patch.object compatibility ---

    @staticmethod
    def _validate_gid_column(gdf: gpd.GeoDataFrame) -> None:
        return GIDValidator._validate_gid_column(gdf)

    def _ensure_gid_column(self, gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
        return GIDValidator._ensure_gid_column(gdf)

    def _create_sqlalchemy_column(
        self, col_name: str, sa_config: dict | object
    ) -> sqlalchemy.Column:
        return TypeMapper._create_sqlalchemy_column(col_name, sa_config)

    def _convert_pg_mapping_to_sqlalchemy(self, pg_mapping: dict) -> dict:
        return TypeMapper._convert_pg_mapping_to_sqlalchemy(pg_mapping)

    def _build_column_mapping_from_gdf(self, gdf: gpd.GeoDataFrame) -> dict:
        return TypeMapper._build_column_mapping_from_gdf(gdf)

    def _create_table_from_mapping(
        self,
        table_name: str,
        column_mapping: dict[str, str],
        schema: Optional[str] = None,
    ) -> None:
        return self._schema._create_table_from_mapping(
            table_name, column_mapping, schema
        )

    @staticmethod
    def _validate_and_split_table_name(table_name: str) -> tuple[str, str]:
        return SchemaBuilder._validate_and_split_table_name(table_name)

    def _add_primary_key_constraint(self, table_name: str) -> None:
        return self._schema._add_primary_key_constraint(table_name)

    def apply_foreign_keys(self, fk_defs: list[dict]) -> None:
        """Apply FK constraints extracted from a GeoPackage to PostgreSQL tables.

        Args:
            fk_defs: List of {from_table, from_col, to_table, to_col} dicts,
                as returned by extract_gpkg_fk_schema().
        """
        self._schema.add_fk_constraints(fk_defs)

    def stamp_gee_flags(self, table_name: str, gee_field_ids: set[int]) -> None:
        """Ensure has_gee_data column exists and stamp TRUE for fields with GEE data.

        Idempotent: safe to call on every pipeline run. Runs ADD COLUMN +
        two UPDATEs in a single transaction. If gee_field_ids is empty, all
        rows get has_gee_data=FALSE.

        Args:
            table_name: Target PostGIS table (e.g. 'som_field_boundaries').
            gee_field_ids: Set of integer gid values that have GEE Sentinel-2 data.
        """
        try:
            with self.engine.begin() as conn:
                conn.execute(
                    sqlalchemy.text(
                        f'ALTER TABLE "{table_name}" '
                        "ADD COLUMN IF NOT EXISTS has_gee_data BOOLEAN DEFAULT FALSE"
                    )
                )
                conn.execute(
                    sqlalchemy.text(f'UPDATE "{table_name}" SET has_gee_data = FALSE')
                )
                if gee_field_ids:
                    conn.execute(
                        sqlalchemy.text(
                            f'UPDATE "{table_name}" SET has_gee_data = TRUE '
                            "WHERE gid = ANY(:ids)"
                        ),
                        {"ids": list(gee_field_ids)},
                    )
            logger.info(
                "gee_flags_stamped", table=table_name, flagged=len(gee_field_ids)
            )
        except sqlalchemy.exc.SQLAlchemyError as exc:
            logger.error("gee_flags_stamp_failed", table=table_name, error=str(exc))
            raise RuntimeError(f"Failed to stamp GEE flags on '{table_name}'") from exc

    def _insert_geodataframe(
        self, gdf: gpd.GeoDataFrame, table_name: str, override_method: str
    ) -> None:
        return self._inserter._insert_geodataframe(gdf, table_name, override_method)

    def _insert_dataframe(
        self, df: pd.DataFrame, table_name: str, override_method: str
    ) -> None:
        return self._inserter._insert_dataframe(df, table_name, override_method)

    @staticmethod
    def _normalize_cog_metadata(metadata) -> dict:
        return DataInserter._normalize_cog_metadata(metadata)

    @staticmethod
    def _validate_cog_metadata(metadata: dict) -> None:
        return DataInserter._validate_cog_metadata(metadata)

    def _ensure_cog_table(self, table_name: str) -> None:
        if not sqlalchemy.inspect(self.engine).has_table(table_name):
            logger.info(f"Table '{table_name}' does not exist. Creating it.")
            self._create_table_from_mapping(
                table_name=table_name,
                column_mapping=self._convert_pg_mapping_to_sqlalchemy(
                    RasterStacColumns
                ),
            )

    # --- Public API ---

    def insert_table_data(
        self, gdf, table_name, override_method="replace", gid_offset: int = 0
    ):
        """
        Insert a GeoDataFrame or DataFrame into PostGIS.

        Args:
            gdf: GeoDataFrame or DataFrame to insert.
            table_name: Name of the table in PostGIS.
            override_method: 'replace', 'append', or 'fail' behavior if table exists.
            gid_offset: Value added to each generated GID. Used for chunked ingestion to
                keep GIDs globally unique across chunks (chunk N uses offset = N * CHUNK_SIZE).

        Notes:
            - If the table does not exist, it will be created based on the GeoDataFrame/DataFrame schema.
            - For GeoDataFrames without a defined CRS, a warning is logged and data is inserted as a regular DataFrame with WKT geometries.
            - Function handles GeoDataFrames first and falls back to DataFrames.
        """
        with structlog.contextvars.bound_contextvars(table=table_name):
            try:
                # Ensure gid column exists for GeoDataFrames before creating table schema
                gdf_with_gid = gdf
                if isinstance(gdf, gpd.GeoDataFrame):
                    gdf_with_gid = self._ensure_gid_column(gdf)
                    if gid_offset > 0:
                        gdf_with_gid["gid"] = gdf_with_gid["gid"] + gid_offset

                # Insert data with to_postgis (handles PostGIS metadata correctly)
                if isinstance(gdf, gpd.GeoDataFrame):
                    self._insert_geodataframe(gdf_with_gid, table_name, override_method)
                elif isinstance(gdf, pd.DataFrame):
                    self._insert_dataframe(gdf, table_name, override_method)
                else:
                    error_msg = (
                        f"Input must be a GeoDataFrame or DataFrame, got {type(gdf)}"
                    )
                    handle_error(
                        logger=logger, error_msg=error_msg, exc_class=ValueError
                    )

                # Add PRIMARY KEY constraint on gid after data insertion
                # This ensures TiPg can detect gid as the primary key for clean IDs
                if isinstance(gdf, gpd.GeoDataFrame):
                    self._add_primary_key_constraint(table_name)

            except Exception as e:
                # Reset engine state to avoid invalid transaction errors
                try:
                    self.engine.dispose()
                except Exception as dispose_exc:
                    logger.warning(
                        f"Failed to dispose SQLAlchemy engine during error handling: {dispose_exc}"
                    )

                error_msg = f"Error inserting GeoDataFrame/DataFrame into PostGIS: {e}"
                handle_error(logger=logger, error_msg=error_msg, exc_class=RuntimeError)

    def insert_cog_metadata(self, metadata: dict, table_name: str) -> None:
        """Insert COG metadata into a PostGIS table.

        Args:
            metadata: Dictionary containing COG metadata.
            table_name: Name of the PostGIS table to insert into.
        """
        # Validate table name to prevent SQL injection
        schema, table = self._validate_and_split_table_name(table_name)

        # Build qualified table name for SQL statements
        qualified_table_sql = (
            f'"{schema}"."{table}"' if "." in table_name else f'"{table}"'
        )

        try:
            metadata = self._normalize_cog_metadata(metadata)
            self._ensure_cog_table(table_name)
            self._validate_cog_metadata(metadata)

            datetime = metadata.get("datetime", Config.DEFAULT_DATETIME)

            with self.engine.begin() as conn:
                insert_stmt = sqlalchemy.text(f"""
                    INSERT INTO {qualified_table_sql} (gid, datetime, bbox, geometry, file_url, metadata)
                    VALUES (:gid, :datetime, :bbox, ST_GeomFromText(:geometry, 4326), :file_url, :metadata)
                    ON CONFLICT (gid) DO UPDATE
                    SET datetime = EXCLUDED.datetime,
                        bbox = EXCLUDED.bbox,
                        geometry = EXCLUDED.geometry,
                        file_url = EXCLUDED.file_url,
                        metadata = EXCLUDED.metadata;
                    """)
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
        return self._inserter.read_data(table_name)
