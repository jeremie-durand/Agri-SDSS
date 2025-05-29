import logging
logger = logging.getLogger(__name__)

import geopandas as gpd
from shapely.geometry import mapping, box, mapping
from pystac import Item, Asset, Collection, Extent, SpatialExtent, TemporalExtent
from stac_pydantic.item import Item as PydanticItem
from stac_pydantic.collection import Collection as PydanticCollection
from pydantic import ValidationError
from datetime import datetime, date, timezone
from shapely.geometry import box
import requests
from dateutil.parser import parse
import rasterio
import os
import xml.etree.ElementTree as ET
import subprocess
import shutil

def create_stac_item_from_vector(row):
    """
    Create a STAC Item from a row of data.

    Args:
        row (dict): Dictionary containing item data.

    Returns:
        pystac.Item or None: The generated STAC Item, or None if not enough data.
    """
    #print("DEBUG start_date:", row.get("start_date"), type(row.get("start_date")))
    geometry = mapping(row["geometry"])
    properties = row.get("metadata") or {}
    start = ensure_datetime_with_tz(row.get("start_date")) if row.get("start_date") else None
    end = ensure_datetime_with_tz(row.get("end_date")) if row.get("end_date") else None

    if start and end and start != end:
        item = Item(
            id=str(row["id"]),
            geometry=geometry,
            bbox=list(gpd.GeoSeries([row["geometry"]]).total_bounds),
            datetime=start,
            properties=properties,
            start_datetime=start,  
            end_datetime=end
        )
    elif start:
        item = Item(
            id=str(row["id"]),
            geometry=geometry,
            bbox=list(gpd.GeoSeries([row["geometry"]]).total_bounds),
            datetime=start,
            properties=properties
        )
    else:
        return None

    if row.get("file_url"):
        item.add_asset(
            "data",
            Asset(href=row["file_url"], media_type="application/octet-stream")
        )
    return item

def create_stac_item_from_raster(raster_path, item_id=None, asset_key="data"):
    """
    Create a STAC Item from a local raster file.

    Args:
        raster_path (str): Path to the raster file.
        item_id (str): Optional ID for the item.
        asset_key (str): Asset key name.

    Returns:
        pystac.Item or None: The generated STAC Item, or None if not enough data.
    """

    #output_cog = "C:/Users/18195/OneDrive - USherbrooke/Bureau/MOS_data/SIIGSOL-100m/corg_fr_siigsol/corg_fr_siigsol_cog.tif"
    #convert_to_cog(raster_path, output_cog)

    # Chekc if raster is in server COG format
    #raster_url = "http://host.docker.internal:8001/corg_fr_siigsol_cog.tif"
    #raster_url = "http://host.docker.internal:8001/corg_fr_siigsol_cog4326.tif"
    raster_url = "http://host.docker.internal:8001/ph_fr_siigsol_cog.tif" #TODO: hardcoded URL

    with rasterio.open(raster_path) as src:
        bounds = src.bounds
        geometry = mapping(box(*bounds))
        bbox = [bounds.left, bounds.bottom, bounds.right, bounds.top]
        dt_str = src.tags().get("TIFFTAG_DATETIME")
        if dt_str:
            try:
                dt = ensure_datetime_with_tz(dt_str)
            except Exception:
                dt = datetime.utcnow().replace(tzinfo=timezone.utc)
        else:
            dt = datetime.utcnow().replace(tzinfo=timezone.utc)

        epsg = src.crs.to_epsg() if src.crs and src.crs.to_epsg() else 4326 #TODO: hardcoded EPSG
        properties = {
            "raster:bands": src.count,
            "proj:epsg": epsg,
        }

        aux_path = raster_path.replace(".tif", ".tif.aux.xml")
        if os.path.exists(aux_path):
            properties.update(parse_aux_xml(aux_path))

    print("EPSG trouvé :", src.crs.to_epsg())
    print("Chemin aux.xml :", aux_path, "Existe ?", os.path.exists(aux_path))
    print("Méta aux.xml :", parse_aux_xml(aux_path) if os.path.exists(aux_path) else "Pas de aux.xml")
    print("Propriétés finales :", properties)
    item = Item(
        id=item_id or os.path.splitext(os.path.basename(raster_path))[0],
        geometry=geometry,
        bbox=bbox,
        datetime=dt,
        properties=properties
    )

    # Add the raster asset
    item.add_asset(
        asset_key,
        Asset(href=raster_url, media_type="image/tiff; application=geotiff")
    )

    # Add a tiles asset for the COG
    item.add_asset(
        "tiles",
        Asset(
            href=f"http://localhost:8082/cog/tiles/{{z}}/{{x}}/{{y}}.png?url={raster_url}",
            media_type="image/png",
            roles=["tiles"]
        )
    )
    return item

def create_stac_collection(items, collection_id, title="My Collection"): # default license="proprietary"
    """
    Create a STAC Collection from a list of pystac.Item objects.

    Args:
        items (list): List of pystac.Item objects.
        collection_id (str): Collection identifier.
        title (str): Title of the collection (default: "My Collection").

    Returns:
        pystac.Collection: The generated STAC Collection.

    Raises:
        ValueError: If no datetime found in items.
    """
    logger.info(f"Creating STAC Collection with ID: {collection_id}, Title: {title}")

    if not items:
        logger.error("La liste d'items est vide.")
        raise ValueError("La liste d'items est vide.")

    # Compute spatial extent
    boxes = []
    # Check if all items have a valid bbox
    for item in items:
        if not hasattr(item, "bbox") or not item.bbox:
            logger.error(f"L'item {item.id} n'a pas de bbox valide.")
            raise ValueError(f"L'item {item.id} n'a pas de bbox valide.")
        boxes.append(box(*item.bbox))
    all_bounds = gpd.GeoSeries(boxes).total_bounds

    # Compute temporal extent
    datetimes = [item.datetime for item in items if getattr(item, "datetime", None)]
    if not datetimes:
        logger.error("Aucun datetime trouvé dans les items pour créer la collection.")
        raise ValueError("Aucun datetime trouvé dans les items pour créer la collection.")

    spatial_extent = SpatialExtent([list(all_bounds)])
    temporal_extent = TemporalExtent([[min(datetimes), max(datetimes)]])
    extent = Extent(spatial=spatial_extent, temporal=temporal_extent)

    collection = Collection(
        id=collection_id,
        description="A STAC Collection generated from Python",
        extent=extent,
        title=title,
    )

    logger.info(f"Collection {collection_id} created with {len(items)} items.")
    return collection

def validate_stac(stac_obj: dict, stac_type: str) -> None:
    """
    Validate a STAC object (item or collection) using Pydantic models.

    Args:
        stac_obj (dict): The STAC object as a dictionary.
        stac_type (str): Either 'item' or 'collection'.

    Raises:
        ValueError: If an invalid stac_type is provided.
        ValidationError: If the object is not valid according to STAC specification.
    """
    try:
        if stac_type == "item":
            PydanticItem(**stac_obj)
        elif stac_type == "collection":
            PydanticCollection(**stac_obj)
        else:
            raise ValueError("stac_type must be 'item' or 'collection'")
        logger.info(f"STAC {stac_type} validation successful.")
    except ValidationError as e:
        logger.error(f"STAC {stac_type} validation failed: {e}")
        raise

def ensure_datetime_with_tz(dt):
    """
    Ensure a datetime object is timezone-aware (UTC).

    Args:
        dt (str, datetime, or date): The input date or datetime.

    Returns:
        datetime: Timezone-aware datetime object.
    """
    if isinstance(dt, str):
        dt = parse(dt)
    if isinstance(dt, date) and not isinstance(dt, datetime):
        return datetime(dt.year, dt.month, dt.day, tzinfo=timezone.utc)
    elif isinstance(dt, datetime):
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    return dt

def parse_aux_xml(aux_path):
    properties = {}
    try:
        tree = ET.parse(aux_path)
        root = tree.getroot()
        # Pour chaque bande, extraire la description
        for band in root.findall(".//PAMRasterBand"):
            band_num = band.attrib.get("band")
            desc_elem = band.find("Description")
            if band_num and desc_elem is not None and desc_elem.text:
                properties[f"band_{band_num}_description"] = desc_elem.text
    except Exception as e:
        print("Erreur lecture aux.xml:", e)
    return properties

def convert_to_cog(input_path, output_path, epsg=4326):
    # Vérifie si gdalwarp est disponible dans le PATH
    if shutil.which("gdalwarp") is None:
        print("Erreur : gdalwarp n'est pas trouvé dans le PATH système. Veuillez installer GDAL et/ou ajouter gdalwarp au PATH.")
        return False

    cmd = [
        "gdalwarp",
        "-t_srs", f"EPSG:{epsg}",       # Reprojection
        "-of", "COG",                   # Format output: COG
        "-co", "COMPRESS=DEFLATE",     # Compression
        input_path,
        output_path
    ]

    env = os.environ.copy()
    env['PROJ_LIB'] = '/usr/share/proj'  # Path to PROJ proj files

    try:
        print("Création du COG avec la commande :", " ".join(cmd))
        subprocess.run(cmd, check=True, env=env)
        return True
    except subprocess.CalledProcessError as e:
        print(f"Erreur lors de l'exécution de gdalwarp : {e}")
        return False

def post_collection_to_stac_api(collection, api_url):
    """
    Post a STAC Collection to the STAC API.
    """
    url = f"{api_url}/collections"
    collection_json = collection.to_dict()
    response = requests.post(
        url,
        headers={"Content-Type": "application/json"},
        json=collection_json
    )
    print("POST /collections status:", response.status_code)
    print("Response:", response.text)
    return response

def post_item_to_stac_api(item, api_url, collection_id):
    """
    Post a STAC Item to the STAC API.
    """
    url = f"{api_url}/collections/{collection_id}/items"
    item_json = item.to_dict()
    response = requests.post(
        url,
        headers={"Content-Type": "application/json"},
        json=item_json
    )
    print(f"POST /collections/{collection_id}/items status:", response.status_code)
    print("Response:", response.text)
    return response

def delete_item_from_stac_api(item_id, api_url, collection_id):
    """
    Delete a STAC Item from the STAC API.
    Returns True if item was deleted or didn't exist, False on other errors.
    """
    try:
        if not item_id or not isinstance(item_id, str):
            print("Aucun item_id valide fourni pour la suppression.")
            return False

        url = f"{api_url}/collections/{collection_id}/items/{item_id}"
        response = requests.delete(url)
        
        if response.status_code == 204:
            print(f"Item {item_id} supprimé avec succès.")
            return True
        elif response.status_code == 404:
            print(f"Item {item_id} n'existe pas, rien à supprimer (OK).")
            return True  # Considéré comme réussi : pas besoin de supprimer ce qui n'existe pas
        else:
            print(f"Échec de la suppression de l'item {item_id}. Code HTTP: {response.status_code}")
            return False

    except requests.RequestException as e:
        print(f"Erreur réseau lors de la suppression de l'item {item_id} : {e}")
        return False

def print_stac_api_summary(api_url, collection_id):
    """
    Print a summary of collections and items from the STAC API.
    """
    print("\n--- Collections via API ---")
    r = requests.get(f"{api_url}/collections")
    print(r.json())

    print(f"\n--- Items {collection_id} via API ---")
    r = requests.get(f"{api_url}/collections/{collection_id}/items")
    print(r.json())