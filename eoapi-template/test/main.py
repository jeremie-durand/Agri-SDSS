from logging_setup import setup_logging
setup_logging()

# Import libraries
import logging

# Import env variables
from config import (
    VECTOR_TABLES,
    RASTER_PATH,
    STAC_API_URL,
    STAC_COLLECTION_ID,
)

# Import internal modules
from processing_stac import print_stac_api_summary

from geoprocessing_pipeline import (
    geoprocessing_vector, 
    geoprocessing_raster
)

logger = logging.getLogger(__name__)

def main():
    """
    Main function to run the geoprocessing pipeline.
    vector : Process vector data from PostGIS and upload to STAC API.
    raster : Process raster data from local file system and upload to STAC API.
    """
    logger.info("Démarrage du pipeline...")
    geoprocessing_vector(vector_tables=VECTOR_TABLES, 
                         api_url=STAC_API_URL, 
                         collection_id=STAC_COLLECTION_ID)
    
    geoprocessing_raster(raster_path=RASTER_PATH, 
                         api_url=STAC_API_URL, 
                         collection_id=STAC_COLLECTION_ID)
    
    #logger.info("Validation et résumé de l'API STAC...")
    #print_stac_api_summary(api_url=STAC_API_URL, collection_id=STAC_COLLECTION_ID)

if __name__ == "__main__":
    main()