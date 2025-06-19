# Import libraries
import os
from dotenv import load_dotenv

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
RASTER_URL_PREFIX = str(os.getenv("RASTER_URL_PREFIX", "http://host.docker.internal:8001/"))  # Default to local URL if not set
GLOBAL_SRID = int(os.getenv("GLOBAL_SRID", 4326))  # Default to 4326 if not set
STAC_API_URL = str(os.getenv("STAC_API_URL"))
if not STAC_API_URL: 
    raise ValueError("STAC_API_URL n'est pas défini dans l'environnement")

STAC_COLLECTION_ID = "my-collection"  # Hardcoded collection ID for now, can be changed later