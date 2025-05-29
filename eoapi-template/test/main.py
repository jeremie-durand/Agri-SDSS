from logging_setup import setup_logging
setup_logging()

import os
import sys
import sqlalchemy
from dotenv import load_dotenv
import logging
import traceback
from pydantic import ValidationError

# Load environment variables from .env at project root
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
dotenv_path = os.path.join(project_root, '.env')
load_dotenv(dotenv_path=dotenv_path)

# Get environment variables
POSTGRES_USER = str(os.getenv("POSTGRES_USER"))
POSTGRES_PASSWORD = str(os.getenv("POSTGRES_PASSWORD"))
POSTGRES_HOST = str(os.getenv("POSTGRES_HOST"))
POSTGRES_PORT = int(os.getenv("POSTGRES_PORT")) 
POSTGRES_DB = str(os.getenv("POSTGRES_DB"))
VECTOR_TABLES = str(os.getenv("VECTOR_TABLES"))
RASTER_PATH = str(os.getenv("RASTER_PATH"))
GLOBAL_SRID = int(os.getenv("GLOBAL_SRID", 4326))  # Default to 4326 if not set
STAC_API_URL = str(os.getenv("STAC_API_URL"))
if not STAC_API_URL: 
    raise ValueError("STAC_API_URL n'est pas défini dans l'environnement")

STAC_COLLECTION_ID = "my-collection"  # Hardcoded collection ID for now, can be changed later

# Imports des modules internes
from init_postgis import (
    connect_to_postgis, 
    read_data_postgis, 
    get_table_columns,
    ensure_columns_exist
)
from processing_stac import (
    create_stac_item_from_vector, 
    create_stac_item_from_raster, 
    create_stac_collection, 
    post_item_to_stac_api, 
    post_collection_to_stac_api, 
    print_stac_api_summary, 
    validate_stac, 
    delete_item_from_stac_api, 
    convert_to_cog
)

logger = logging.getLogger(__name__)

def main():
    """
    POUR L'INSTANT : 
    Main pipeline to read data from PostGIS, create STAC items and collection,
    and post them to a STAC API.
    """
    logging.info("Démarrage du pipeline de traitement STAC...")

    # -------------------------------------------------------------
    # VECTOR 
    # -------------------------------------------------------------
    try:
        # Columns to ensure exist in the VECTOR_TABLE (add if missing) #TODO: hardcoded, à adapter selon les données
        # Define the columns required for STAC items in the vector table
        stac_columns = {
            "gid": "INTEGER PRIMARY KEY", 
            "geom": "geometry(Geometry, 4326)",
            "start_date": "TIMESTAMP",
            "end_date": "TIMESTAMP",
            "file_url": "TEXT",
            "metadata": "JSONB"
        }
        # Mapping of STAC fields to table columns
        columns_mapping = {
            "id": "id",
            "geometry": "geometry", 
            "start_date": "start_date",
            "end_date": "end_date",
            "file_url": "file_url",
            "metadata": "metadata"
        }

        # if vector_tables is not defined, pass to the next step
        if not VECTOR_TABLES:
            print("Aucune table vectorielle définie dans le fichier .env. Passer à la suite...")
            return
        logging.info("Traitement des données vectorielles...")
        vector_tables = [t.strip() for t in VECTOR_TABLES.split(",") if t.strip()] # Split and clean the VECTOR_TABLES variable
        
        # Loop through each vector table defined in the environment variable
        for table in vector_tables:
            if not table:  # Check if the table name is provided
                logging.warning("Table vectorielle vide trouvée dans VECTOR_TABLES. Passer à la suite...")
                continue
        
            # Ensure required columns exist in the table
            try:
                engine = connect_to_postgis(POSTGRES_USER, POSTGRES_PASSWORD, POSTGRES_HOST, POSTGRES_PORT, POSTGRES_DB) # Create SQLAlchemy engine
                logging.info(f"Connexion à la base de données PostGIS '{POSTGRES_DB}' réussie.")
            except Exception as e:
                logging.error(f"Erreur de connexion à la base de données PostGIS : {e}")
                raise RuntimeError("Erreur critique lors de la connexion à la base de données PostGIS")
            
            logging.info(f"Vérification et ajout des colonnes STAC dans la table '{table}'...")
            ensure_columns_exist(engine, table, stac_columns) # Ensure the required columns exist in the specified table

            # Check if the required columns exist in the table for STAC standards, if not, add them
            logging.info(f"Vérification des colonnes requises dans la table '{table}'...")
            with engine.begin() as conn: 
                for col_name, col_type in stac_columns.items(): # Iterate over required columns
                    if col_name not in get_table_columns(engine, table): # Check if column exists
                        conn.execute(sqlalchemy.text(
                            f'ALTER TABLE "{table}" ADD COLUMN "{col_name}" {col_type};' # Add column if it doesn't exist
                        ))

            # Set a dummy date for all rows in start_date
            logging.info(f"Initialisation des dates de début et de fin dans la table '{table}'...")
            try:
                with engine.begin() as conn:
                    conn.execute(sqlalchemy.text(
                        f'UPDATE "{table}" SET start_date = :date_bidon'
                    ), {"date_bidon": "2024-01-01T00:00:00+00:00"}) #TODO: hardcoded date for testing purposes

                # Set a dummy date for all rows in end_date
                with engine.begin() as conn:
                    conn.execute(sqlalchemy.text(
                        f'UPDATE "{table}" SET end_date = :date_bidon'
                    ), {"date_bidon": "2024-12-31T00:00:00+00:00"})  #TODO: hardcoded date for testing purposes
            
            except Exception as e:
                logging.error(f"Erreur lors de l'initialisation des dates dans la table '{table}': {e}")
                raise RuntimeError("Erreur critique lors de l'initialisation des dates dans la table PostGIS")
            
            # Read data from PostGIS
            data_vector = read_data_postgis(engine, table) # Read data from the specified table

            # Build STAC items from table rows 
            item_vector = []
            item = None
            for _, row in data_vector.iterrows(): # Iterate over each row in the GeoDataFrame
                stac_row = {}
                for stac_col, real_col in columns_mapping.items(): # Map STAC fields to table columns
                    if real_col not in data_vector.columns:
                        logging.error(f"Colonne '{real_col}' manquante dans la table '{table}'.")
                        continue
                    stac_row[stac_col] = getattr(row, real_col, None)
                
                if stac_row["geometry"] is None: # Skip if geometry is None
                    continue
                item = create_stac_item_from_vector(stac_row) # Create STAC item from row
                if item is not None:
                    item_vector.append(item)

        # Post each vector item to the API
        if item_vector:
            # Create the STAC collection and post it to the STAC API before posting items
            logging.info("Création de la collection vectorielle STAC...")
            collection = create_stac_collection(item_vector, collection_id=STAC_COLLECTION_ID) # Create STAC collection from items

            # Validate the collection before posting
            try:
                validate_stac(collection.to_dict(), stac_type="collection")
            except ValueError as ve:
                logging.error(f"Erreur de validation STAC pour la collection : {ve}")
                raise RuntimeError("Erreur critique lors de la validation de la collection STAC")

            # Post the collection to the STAC API
            logging.info("Post de la collection vectorielle dans l'API STAC...")
            post_collection_to_stac_api(collection, api_url=STAC_API_URL)

            # Post each item to the STAC API
            logging.info("Post des items vectoriels dans l'API STAC...")
            for item in item_vector:
                item_id = item.id

                # Delete the item if it exists to refresh it
                deleted = delete_item_from_stac_api(item_id, api_url=STAC_API_URL, collection_id=STAC_COLLECTION_ID)
                if not deleted:
                    print(f"Problème lors de la tentative de suppression de l'item vecteur {item_id}, mais on continue...")

                # Validate the item
                try:
                    validate_stac(item.to_dict(), stac_type="item")
                except ValueError as ve:
                    logging.error(f"Erreur de validation STAC pour l'item {item_id}: {ve}")
                    continue
                except ValidationError as ve:
                    logging.error(f"Erreur de validation STAC pour l'item {item_id}: {ve}")
                    continue

                # Post the item to the STAC API
                post_item_to_stac_api(item, api_url=STAC_API_URL, collection_id=STAC_COLLECTION_ID)
    except Exception as e:
        logging.error(f"Erreur lors du traitement des données vectorielles : {e}")
        logging.error(traceback.format_exc())
        raise RuntimeError("Erreur critique")
    
    # -------------------------------------------------------------
    # RASTER 
    # -------------------------------------------------------------
    try:
        if not RASTER_PATH:
            print("Aucun chemin RASTER_PATH défini dans le fichier .env. Passer à la suite...")
            return
        
        logging.info("Traitement des données raster...")
        if not os.path.exists(RASTER_PATH):
            print(f"Erreur : Le chemin RASTER_PATH '{RASTER_PATH}' n'existe pas.")
            sys.exit(1)

        item_raster = []
        item = None
        all_files = os.listdir(RASTER_PATH)
        sources = [f for f in all_files if f.endswith(".tif") or f.endswith(".tiff")]
        # On ne garde que les fichiers qui ne sont pas déjà des COG
        sources_no_cog = [f for f in sources if not (f.endswith("_cog.tif") or f.endswith("_cog.tiff"))]

        # Pour garder la liste des item_ids déjà ajoutés
        item_ids_seen = set()

        # Traite d'abord tous les fichiers source (non-COG)
        for file in sources_no_cog:
            raster_file = os.path.join(RASTER_PATH, file)
            base, ext = os.path.splitext(file)
            cog_file = os.path.join(RASTER_PATH, f"{base}_cog{ext}")
            item_id = f"{base}_cog"  # <-- toujours underscore

            if not os.path.exists(cog_file):
                success = convert_to_cog(raster_file, cog_file, GLOBAL_SRID)
                if not success or not os.path.exists(cog_file):
                    print(f"Erreur : le fichier COG {cog_file} n'a pas été créé. Vérifiez les logs de gdalwarp.")
                    sys.exit(1)

            if item_id not in item_ids_seen:
                item = create_stac_item_from_raster(cog_file, item_id)
                if item is not None:
                    item_raster.append(item)
                    item_ids_seen.add(item_id)
                else:
                    print(f"Attention : impossible de créer l'item STAC pour {cog_file}")

        # Ensuite, traite les COG qui n'ont pas de source associé
        for file in sources:
            if file.endswith("_cog.tif") or file.endswith("_cog.tiff"):
                base, ext = os.path.splitext(file)
                base_cog = file.replace("_cog.tif", ".tif").replace("_cog.tiff", ".tiff")
                item_id = base  # ex: ph_fr_siigsol_cog

                if base_cog in sources_no_cog:
                    continue  # On a déjà traité ce raster via le source

                if item_id not in item_ids_seen:
                    raster_file = os.path.join(RASTER_PATH, file)
                    item = create_stac_item_from_raster(raster_file, item_id)
                    if item is not None:
                        item_raster.append(item)
                        item_ids_seen.add(item_id)

        # Post the raster item to the API
        if item_raster:
            # Create the STAC collection and post it to the STAC API before posting items
            collection = create_stac_collection(item_raster, collection_id=STAC_COLLECTION_ID)

            # Validate the collection before posting
            try:
                validate_stac(collection.to_dict(), stac_type="collection")
            except ValueError as ve:
                logging.error(f"Erreur de validation STAC pour la collection : {ve}")
                raise RuntimeError("Erreur critique lors de la validation de la collection STAC")

            # Post the collection to the STAC API
            logging.info("Post de la collection raster dans l'API STAC...")
            post_collection_to_stac_api(collection, api_url=STAC_API_URL)
        
            for item in item_raster:
                item_id = item.id

                # Delete the item if it exists to refresh it
                deleted = delete_item_from_stac_api(item_id, api_url=STAC_API_URL, collection_id=STAC_COLLECTION_ID)
                if not deleted:
                    logger.warning(f"Problème lors de la tentative de suppression de l'item {item_id}, mais on continue...")

                # Validate the item
                try:
                    validate_stac(item.to_dict(), stac_type="item")
                except ValueError as ve:
                    logging.error(f"Erreur de validation STAC pour l'item {item_id}: {ve}")
                    continue
                except ValidationError as ve:
                    logging.error(f"Erreur de validation STAC pour l'item {item_id}: {ve}")
                    continue

                # Post the item to the STAC API
                post_item_to_stac_api(item, api_url=STAC_API_URL, collection_id=STAC_COLLECTION_ID) #TODO item 
    except Exception as e:
        logging.error(f"Erreur lors du traitement des données raster : {e}")
        logging.error(traceback.format_exc())
        raise RuntimeError("Erreur critique")
    
    # -------------------------------------------------------------
    # VALIDATION 
    # -------------------------------------------------------------
    # Print a summary of the STAC API contents
    logging.info("Validation et résumé de l'API STAC...")
    print_stac_api_summary(api_url=STAC_API_URL, collection_id=STAC_COLLECTION_ID)

if __name__ == "__main__":
    main()