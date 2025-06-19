import logging
logger = logging.getLogger(__name__)

# Import libraries
import os
import requests
import traceback

import sqlalchemy
from pydantic import ValidationError

# Import env variables
from config import (
    POSTGRES_USER,
    POSTGRES_PASSWORD,
    POSTGRES_HOST,
    POSTGRES_PORT,
    POSTGRES_DB,
    GLOBAL_SRID
)

# Import internal modules
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
    validate_stac, 
    delete_item_from_stac_api, 
    convert_to_cog
)

from mapping import (
    vector_stac_columns, 
    vector_columns_mapping
)

def geoprocessing_vector(vector_tables, api_url, collection_id):
    """
    """
    logger.info("-------------------------------------------------------------") 
    logger.info("Démarrage du traitement des données vectorielles")
    logger.info("-------------------------------------------------------------")

    try:
        # if vector_tables is not defined, pass to the next step
        if not vector_tables:
            logger.warning("Aucune table vectorielle définie. Passer à la suite...")
            return False
        
        vector_tables = [t.strip() for t in vector_tables.split(",") if t.strip()] # Split and clean the vector_tables variable

        # Connect to PostGIS database
        try:
            engine = connect_to_postgis(POSTGRES_USER, POSTGRES_PASSWORD, POSTGRES_HOST, POSTGRES_PORT, POSTGRES_DB) # Create SQLAlchemy engine
            logger.info(f"Connexion à la base de données PostGIS '{POSTGRES_DB}' réussie.")
        except Exception as e:
            logger.error(f"Erreur de connexion à la base de données PostGIS : {e}")
            raise RuntimeError("Erreur critique lors de la connexion à la base de données PostGIS")

        # Loop through each vector table defined in the environment variable
        for table in vector_tables:
            if not table:  # Check if the table name is provided
                logger.warning(f"Table vectorielle vide trouvée dans {vector_tables} Passer à la suite...")
                continue
            
            logger.info(f"Vérification et ajout des colonnes STAC dans la table '{table}'...")
            ensure_columns_exist(engine, table, vector_stac_columns) # Ensure the required columns exist in the specified table

            # Check if the required columns exist in the table for STAC standards, if not, add them
            logger.info(f"Vérification des colonnes requises dans la table '{table}'...")
            with engine.begin() as conn: 
                for col_name, col_type in vector_stac_columns.items(): # Iterate over required columns
                    if col_name not in get_table_columns(engine, table): # Check if column exists
                        conn.execute(sqlalchemy.text(
                            f'ALTER TABLE "{table}" ADD COLUMN "{col_name}" {col_type};' # Add column if it doesn't exist
                        ))

            # Set a dummy date for all rows in start_date
            logger.info(f"Initialisation des dates de début et de fin dans la table '{table}'...")
            try:
                with engine.begin() as conn:
                    conn.execute(sqlalchemy.text(
                        f'UPDATE "{table}" SET start_date = :date_bidon'
                    ), {"date_bidon": "2024-01-01T00:00:00+00:00"})

                # Set a dummy date for all rows in end_date
                with engine.begin() as conn:
                    conn.execute(sqlalchemy.text(
                        f'UPDATE "{table}" SET end_date = :date_bidon'
                    ), {"date_bidon": "2024-12-31T00:00:00+00:00"})
            
            except Exception as e:
                logger.error(f"Erreur lors de l'initialisation des dates dans la table '{table}': {e}")
                raise RuntimeError("Erreur critique lors de l'initialisation des dates dans la table PostGIS")
            
            # Read data from PostGIS
            data_vector = read_data_postgis(engine, table) # Read data from the specified table

            # Build STAC items from table rows 
            item_vector = []
            for _, row in data_vector.iterrows(): # Iterate over each row in the GeoDataFrame
                stac_row = {}
                for stac_col, real_col in vector_columns_mapping.items(): # Map STAC fields to table columns
                    if real_col not in data_vector.columns:
                        logger.error(f"Colonne '{real_col}' manquante dans la table '{table}'.")
                        continue
                    stac_row[stac_col] = getattr(row, real_col, None)
                
                if stac_row["geometry"] is None: # Skip if geometry is None
                    continue

                item = create_stac_item_from_vector(stac_row) # Create STAC item from row
                if item is not None:
                    item_vector.append(item)

                if not item_vector:
                    logger.warning(f"Aucun item STAC généré pour la table '{table}'. Passage à la suite.")
                    continue

            # Create a unique collection ID based on the table name
            collection_id_table = f"{collection_id}_{table}"

            # Create the STAC collection and post it to the STAC API before posting items
            logger.info("Création de la collection vectorielle STAC...")
            collection = create_stac_collection(item_vector, collection_id=collection_id_table, title=collection_id_table) # Create STAC collection from items

            # Validate the collection before posting
            try:
                validate_stac(collection.to_dict(), stac_type="collection")
            except ValueError as ve:
                logger.error(f"Erreur de validation STAC pour la collection : {ve}")
                raise RuntimeError("Erreur critique lors de la validation de la collection STAC")

            # Post the collection to the STAC API
            logger.info("Post de la collection vectorielle dans l'API STAC...")
            post_collection_to_stac_api(collection, api_url=api_url)

            # Post each item to the STAC API
            logger.info("Post des items vectoriels dans l'API STAC...")
            for item in item_vector:
                item_id = item.id

                # Validate the item
                try:
                    validate_stac(item.to_dict(), stac_type="item")
                except ValueError as ve:
                    logger.error(f"Erreur de validation STAC pour l'item {item_id}: {ve}")
                    continue
                except ValidationError as ve:
                    logger.error(f"Erreur de validation STAC pour l'item {item_id}: {ve}")
                    continue

                # Delete the item if it exists to refresh it
                get_url = f"{api_url}/collections/{collection_id_table}/items/{item_id}"
                r = requests.get(get_url)
                if r.status_code == 404:
                    logger.info(f"L'item {item_id} n'existe pas dans l'API")
                elif r.status_code == 200:
                    logger.info(f"L'item {item_id} existe déjà dans l'API, on va le supprimer pour le rafraîchir")
                    deleted = delete_item_from_stac_api(item_id, api_url=api_url, collection_id=collection_id_table)
                    if not deleted:
                        logger.warning(f"Problème lors de la tentative de suppression de l'item {item_id}, mais on continue...")
                elif r.status_code == 500:
                    logger.error(f"Erreur 500 lors de la vérification de l'item {item_id} dans l'API. On va essayer de le supprimer quand même.")
                    deleted = delete_item_from_stac_api(item_id, api_url=api_url, collection_id=collection_id_table)
                    if not deleted:
                        logger.warning(f"Problème lors de la tentative de suppression de l'item vecteur {item_id}, mais on continue...")
                else:
                    logger.error(f"Erreur inattendue lors de la vérification de l'item {item_id} dans l'API. Code de statut : {r.status_code}")

                # Post the item to the STAC API
                post_item_to_stac_api(item, api_url=api_url, collection_id=collection_id_table)

        logger.info("Traitement des données vectorielles terminé avec succès.")
        return True
    
    except Exception as e:
        logger.error(f"Erreur lors du traitement des données vectorielles : {e}")
        logger.error(traceback.format_exc())
        return False

def geoprocessing_raster(raster_path, api_url, collection_id):
    """
    """
    logger.info("-------------------------------------------------------------") 
    logger.info("Démarrage du traitement des données raster")
    logger.info("-------------------------------------------------------------")

    try:
        if not raster_path:
            logger.error("Aucun chemin raster_path défini. Passer à la suite...")
            return False
        
        if not os.path.exists(raster_path):
            logger.error(f"Erreur : Le chemin raster_path '{raster_path}' n'existe pas.")
            return False

        item_raster = []
        all_files = os.listdir(raster_path)
        sources = [f for f in all_files if f.endswith(".tif") or f.endswith(".tiff")] # List all raster files in the directory
        sources_no_cog = [f for f in sources if not (f.endswith("_cog.tif") or f.endswith("_cog.tiff"))] # List all raster files that are not COGs
        item_ids_seen = set()

        # Traite d'abord tous les fichiers source (non-COG)
        logger.info(f"Nombre de fichiers raster trouvés : {len(sources)}")
        for file in sources_no_cog:
            raster_file = os.path.join(raster_path, file)
            base, ext = os.path.splitext(file)
            cog_file = os.path.join(raster_path, f"{base}_cog{ext}")
            item_id = f"{base}_cog" # ex: ph_fr_siigsol_cog

            # Vérifie si le COG existe déjà et qu’aucun traitement n’est nécessaire
            cog_exists = os.path.exists(cog_file)
            if cog_exists:
                logger.info(f"[SKIP] Le fichier {cog_file} et ses dérivés existent déjà, traitement ignoré.")
            else:
                logger.info(f"[PROCESS] Génération du COG et fichiers dérivés pour : {raster_file}")
                success = convert_to_cog(raster_file, cog_file, GLOBAL_SRID)
                if not success or not os.path.exists(cog_file):
                    logger.error(f"Erreur : le fichier COG {cog_file} n'a pas été créé. Vérifiez les logs de gdalwarp.")
                    return False

            if item_id not in item_ids_seen:
                item = create_stac_item_from_raster(cog_file, item_id)
                if item is not None:
                    item_raster.append(item)
                    item_ids_seen.add(item_id)
                else:
                    logger.error(f"Attention : impossible de créer l'item STAC pour {cog_file}")

        # Ensuite, traite les COG qui n'ont pas de source associé
        logger.info(f"Nombre de fichiers COG trouvés : {len(sources_no_cog)}")
        for file in sources:
            if file.endswith("_cog.tif") or file.endswith("_cog.tiff"):
                base, ext = os.path.splitext(file)
                base_cog = file.replace("_cog.tif", ".tif").replace("_cog.tiff", ".tiff")
                item_id = base  # ex: ph_fr_siigsol_cog

                if base_cog in sources_no_cog:
                    continue  # On a déjà traité ce raster via le source

                if item_id not in item_ids_seen:
                    raster_file = os.path.join(raster_path, file)
                    item = create_stac_item_from_raster(raster_file, item_id)
                    if item is not None:
                        item_raster.append(item)
                        item_ids_seen.add(item_id)

        # Check if any items were created
        logger.info(f"Nombre d'items raster créés : {len(item_raster)}")
        if not item_raster:
            logger.error("Aucun item raster créé.")
            return False                    

        # Create a unique collection ID based on the table name
        collection_id_raster = f"{collection_id}_raster"

        # Create the STAC collection
        collection = create_stac_collection(item_raster, collection_id=collection_id_raster, title="Collection Raster")

        # Validate the collection before posting
        try:
            validate_stac(collection.to_dict(), stac_type="collection")
        except ValueError as ve:
            logger.error(f"Erreur de validation STAC pour la collection : {ve}")
            raise RuntimeError("Erreur critique lors de la validation de la collection STAC")

        # Post the collection to the STAC API
        logger.info("Post de la collection raster dans l'API STAC...")
        post_collection_to_stac_api(collection, api_url=api_url)
    
        for item in item_raster:
            item_id = item.id

            # Validate the item
            try:
                validate_stac(item.to_dict(), stac_type="item")
            except ValueError as ve:
                logger.error(f"Erreur de validation STAC pour l'item {item_id}: {ve}")
                continue
            except ValidationError as ve:
                logger.error(f"Erreur de validation STAC pour l'item {item_id}: {ve}")
                continue

            # Delete the item if it exists to refresh it
            get_url = f"{api_url}/collections/{collection_id_raster}/items/{item_id}"
            r = requests.get(get_url)
            if r.status_code == 404:
                logger.info(f"L'item {item_id} n'existe pas dans l'API")
            elif r.status_code == 200:
                logger.info(f"L'item {item_id} existe déjà dans l'API, on va le supprimer pour le rafraîchir")
                deleted = delete_item_from_stac_api(item_id, api_url=api_url, collection_id=collection_id_raster)
                if not deleted:
                    logger.warning(f"Problème lors de la tentative de suppression de l'item {item_id}, mais on continue...")
            elif r.status_code == 500:
                logger.error(f"Erreur 500 lors de la vérification de l'item {item_id} dans l'API. On va essayer de le supprimer quand même.")
                deleted = delete_item_from_stac_api(item_id, api_url=api_url, collection_id=collection_id_raster)
                if not deleted:
                    logger.warning(f"Problème lors de la tentative de suppression de l'item vecteur {item_id}, mais on continue...")
            else:
                logger.error(f"Erreur inattendue lors de la vérification de l'item {item_id} dans l'API. Code de statut : {r.status_code}")
                
            # Post the item to the STAC API
            post_item_to_stac_api(item, api_url=api_url, collection_id=collection_id_raster)
    
        logger.info("Traitement des données raster terminé avec succès.")
        return True
    
    except Exception as e:
        logger.error(f"Erreur lors du traitement des données raster : {e}")
        logger.error(traceback.format_exc())
        return False

def geoprocessing_web_services():
    """
    Placeholder function for web services geoprocessing.
    This function should be implemented to handle web service data processing.
    """
    pass


def geoprocessing_other():
    """
    Placeholder function for other geoprocessing tasks.
    This function should be implemented to handle non-vector/raster data processing.
    """
    pass