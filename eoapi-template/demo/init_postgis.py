import logging

logger = logging.getLogger(__name__)

import re

import geopandas as gpd
import sqlalchemy


def connect_to_postgis(
    user: str, password: str, host: str, port: int, db: str
) -> sqlalchemy.engine.Engine:
    """Create a SQLAlchemy engine for connecting to a PostGIS database.

    Args:
        user: Database username.
        password: Database password.
        host: Database host.
        port: Database port.
        db: Database name.

    Returns:
        sqlalchemy.engine.Engine: SQLAlchemy engine instance.
    """
    try:
        engine = sqlalchemy.create_engine(
            f"postgresql+psycopg2://{user}:{password}@{host}:{port}/{db}"
        )
        logger.info(f"Successfully connected to PostGIS database '{db}'.")
        return engine
    except Exception as e:
        logger.error(f"Error connecting to PostGIS database: {e}")
        raise RuntimeError("Critical error while connecting to the PostGIS database")


def insert_gdf_to_postgis(
    engine: sqlalchemy.engine.Engine,
    gdf: gpd.GeoDataFrame,
    table_name: str,
    override_method: str = "replace",
):
    """Insert a GeoDataFrame into a PostGIS table.

    Args:
        engine: SQLAlchemy engine connected to the PostGIS database.
        gdf: The GeoDataFrame to insert.
        table_name: Name of the PostGIS table to insert into.
        override_method: Behavior when the table already exists.
            Options: 'replace', 'append'.
    """
    # Verify if table exists
    if not sqlalchemy.inspect(engine).has_table(table_name):
        logger.info(f"Table '{table_name}' does not exist. Creating it.")
        create_table_postgis(engine=engine, table_name=table_name)

    # Detect geometry column
    geometry_column = None
    for col in ["geom", "geometry"]:
        if col in gdf.columns:
            geometry_column = col
            break
    if geometry_column is None:
        raise ValueError("GeoDataFrame must contain a 'geom' or 'geometry' column")

    # Optionally, rename geometry column to 'geom' for consistency
    if geometry_column != "geom":
        gdf = gdf.rename(columns={geometry_column: "geom"})
        geometry_column = "geom"

    # Check for 'gid' column (optional, depends on your schema)
    if "gid" not in gdf.columns:
        logger.warning(
            "GeoDataFrame does not contain a 'gid' column. Proceeding without it."
        )

    # Write the GeoDataFrame to PostGIS
    gdf.to_postgis(
        name=table_name,
        con=engine,
        if_exists=override_method,
        index=False,
    )


def read_data_postgis(
    engine: sqlalchemy.engine.Engine, table_name: str
) -> gpd.GeoDataFrame:
    """Read spatial data from a PostGIS table into a GeoDataFrame.

    Args:
        engine: SQLAlchemy engine connected to the database.
        table_name: Name of the table to read.

    Returns:
        GeoDataFrame containing the spatial data.
    """
    # Validate table name: must contain only letters, numbers or underscores
    if not re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*$", table_name):
        logger.error(f"Invalid table name: {table_name}")
        raise ValueError("Invalid table name.")

    # SQL query to select and alias columns for STAC processing, plain text for readability
    sql = f"""
        SELECT 
            gid,
            geom,
            start_date,
            end_date,
            file_url,
            metadata
        FROM {table_name}
    """
    data = gpd.read_postgis(sql, engine, geom_col="geom")
    return data


def get_table_columns(engine: sqlalchemy.engine.Engine, table_name: str) -> list:
    """Retrieve the list of column names from a given table.

    Args:
        engine: SQLAlchemy engine connected to the database.
        table_name: Name of the table.

    Returns:
        List of column names in the table.
    """
    insp = sqlalchemy.inspect(engine)
    return [col["name"] for col in insp.get_columns(table_name)]


def ensure_columns_exist(engine: sqlalchemy.engine.Engine, table_name: str, columns):
    """Ensure that each column exists in the given table. Adds it if missing.

    Args:
        engine: SQLAlchemy engine connected to the database.
        table_name: Name of the table.

    Notes:
        - This function will add columns that do not exist in the table.
        - It assumes that the column types are provided in a format compatible with SQLAlchemy.
        - If a column already exists, it will not be modified.
    """
    logger.info(f"Ensuring columns exist in table '{table_name}'...")
    existing_columns = get_table_columns(engine=engine, table_name=table_name)
    with engine.begin() as conn:
        for col_name, col_type in columns.items():
            if col_name not in existing_columns:
                conn.execute(
                    sqlalchemy.text(
                        f'ALTER TABLE "{table_name}" ADD COLUMN "{col_name}" {col_type};'
                    )
                )


def create_table_postgis(engine: sqlalchemy.engine.Engine, table_name: str):
    """Create a PostGIS table for storing raster COG metadata.

    Args:
        engine: SQLAlchemy engine connected to the PostGIS database.
        table_name: Name of the PostGIS table to create.
    """
    with engine.begin() as conn:
        conn.execute(
            sqlalchemy.text(
                f"""
                CREATE TABLE IF NOT EXISTS {table_name} (
                    id TEXT PRIMARY KEY,
                    datetime TIMESTAMP WITH TIME ZONE,
                    bbox FLOAT8[],
                    geometry GEOMETRY(Polygon, 4326),
                    cog_url TEXT,
                    stac_metadata JSONB
                );
            """
            )
        )


def set_dummy_date_for_table(engine: sqlalchemy.engine.Engine, table: str):
    """This function sets a dummy date for all rows in the specified table.

    Args:
        engine: SQLAlchemy engine connected to the database.
        table: Name of the PostGIS table to update.

    Notes:
        This is a temporary solution to ensure that the start_date and end_date columns are not null for STAC processing.
        It should be replaced with actual date initialization logic in the future.
    """
    logger.info(f"Initializing start and end dates in table '{table}'...")
    try:
        with engine.begin() as conn:
            conn.execute(
                sqlalchemy.text(f'UPDATE "{table}" SET start_date = :dummy_date'),
                {"dummy_date": "2024-01-01T00:00:00+00:00"},
            )
            conn.execute(
                sqlalchemy.text(f'UPDATE "{table}" SET end_date = :dummy_date'),
                {"dummy_date": "2024-12-31T00:00:00+00:00"},
            )
    except Exception as e:
        logger.error(f"Error while initializing dates in table '{table}': {e}")
        raise RuntimeError(
            "Critical error while initializing dates in the PostGIS table"
        )
