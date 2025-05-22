import os
import geopandas as gpd
import sqlalchemy
from sqlalchemy import create_engine
from dotenv import load_dotenv
from shapely.geometry import mapping

from init_postgis import connect_to_postgis, read_data_postgis, get_table_columns
from processing_stac import create_stac_item, create_stac_collection, post_item_to_stac_api, post_collection_to_stac_api, print_stac_api_summary, validate_stac

def main():
    """
    POUR L'INSTANT : 
    Main pipeline to read data from PostGIS, create STAC items and collection,
    and post them to a STAC API.
    """
    # Load environment variables from .env at project root
    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
    dotenv_path = os.path.join(project_root, '.env')
    load_dotenv(dotenv_path=dotenv_path)

    user = os.getenv("POSTGRES_USER")
    password = os.getenv("POSTGRES_PASSWORD")
    host = os.getenv("POSTGRES_HOST")
    port = os.getenv("POSTGRES_PORT")
    db = os.getenv("POSTGRES_DB")
    table_name = "bdppad_2024_4326_sample" #TODO: hardcoded table name

    # Columns to ensure exist in the table (add if missing) #TODO: hardcoded
    required_columns = {
    "start_date": "TIMESTAMP",
    "end_date": "TIMESTAMP",
    "file_url": "TEXT",
    "metadata": "JSONB"
    }

    # Mapping from STAC fields to table columns #TODO: hardcoded
    column_mapping = { #TODO hardcode pour parcelle agricole
        "id": "id",            # ou "id" si déjà bon
        "geometry": "geometry",     # ou "geometry"
        "start_date": "start_date",  # ou "start_date"
        "end_date": "end_date",      # ou "end_date"
        "file_url": "file_url",   # ou "file_url"
        "metadata": "metadata"       # ou autre
    }

    # Ensure required columns exist in the table
    engine = connect_to_postgis(user, password, host, port, db)
    with engine.begin() as conn:
        for col_name, col_type in required_columns.items():
            if col_name not in get_table_columns(engine, table_name):
                conn.execute(sqlalchemy.text(
                    f'ALTER TABLE "{table_name}" ADD COLUMN "{col_name}" {col_type};'
                ))

    # Set a dummy date for all rows in start_date
    with engine.begin() as conn:
        conn.execute(sqlalchemy.text(
            f'UPDATE "{table_name}" SET start_date = :date_bidon'
        ), {"date_bidon": "2024-01-01T00:00:00+00:00"})

    # Set a dummy date for all rows in end_date
    with engine.begin() as conn:
        conn.execute(sqlalchemy.text(
            f'UPDATE "{table_name}" SET end_date = :date_bidon'
        ), {"date_bidon": "2024-12-31T00:00:00+00:00"})

    # Read data from PostGIS
    gdf = read_data_postgis(engine, table_name)

    # Build STAC items from table rows
    stac_items = []
    for _, row in gdf.iterrows():
        stac_row = {}
        for stac_col, real_col in column_mapping.items():
            stac_row[stac_col] = getattr(row, real_col, None)
        #print(stac_row)  # Debug print
        if stac_row["geometry"] is None:
            continue
        item = create_stac_item(stac_row)
        if item is not None:
            stac_items.append(item)

    # Create and post the collection before the items
    collection = create_stac_collection(stac_items)
    validate_stac(collection.to_dict(), stac_type="collection")
    post_collection_to_stac_api(collection)

    # Post each item to the API
    for item in stac_items:
        validate_stac(item.to_dict(), stac_type="item")
        post_item_to_stac_api(item, collection_id="my-collection") #TODO: hardcoded collection_id

    # Print a summary of the STAC API contents
    print_stac_api_summary() #TODO: hardcoded 

if __name__ == "__main__":
    main()