import sqlalchemy
import geopandas as gpd
from dotenv import load_dotenv

def connect_to_postgis(user, password, host, port, db):
    """
    Create a SQLAlchemy engine for connecting to a PostGIS database.

    Args:
        user (str): Database username.
        password (str): Database password.
        host (str): Database host.
        port (int or str): Database port.
        db (str): Database name.

    Returns:
        sqlalchemy.engine.Engine: SQLAlchemy engine instance.
    """
    url = f"postgresql+psycopg2://{user}:{password}@{host}:{port}/{db}"
    engine = sqlalchemy.create_engine(url)
    return engine

def read_data_postgis(engine, table_name):
    """
    Read spatial data from a PostGIS table into a GeoDataFrame.

    Args:
        engine (sqlalchemy.engine.Engine): SQLAlchemy engine connected to the database.
        table_name (str): Name of the table to read.

    Returns:
        geopandas.GeoDataFrame: DataFrame containing the spatial data.
    """
    # SQL query to select and alias columns for STAC processing
    sql = f"""
        SELECT 
            gid AS id,
            geom AS geometry,
            start_date,
            end_date,
            file_url,
            metadata
        FROM {table_name}
    """
    gdf = gpd.read_postgis(sql, engine, geom_col='geometry')
    return gdf

def get_table_columns(engine, table_name):
    """
    Retrieve the list of column names from a given table.

    Args:
        engine (sqlalchemy.engine.Engine): SQLAlchemy engine connected to the database.
        table_name (str): Name of the table.

    Returns:
        list: List of column names in the table.
    """
    insp = sqlalchemy.inspect(engine)
    return [col['name'] for col in insp.get_columns(table_name)]