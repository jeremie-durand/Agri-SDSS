import geopandas as gpd
from sqlalchemy import create_engine
from dotenv import load_dotenv
from shapely.geometry import mapping
from pystac import Item, Asset, Collection, Extent, SpatialExtent, TemporalExtent
from stac_pydantic.item import Item as PydanticItem
from stac_pydantic.collection import Collection as PydanticCollection
from pydantic import ValidationError
from init_postgis import connect_to_postgis, read_data_postgis, get_table_columns
from datetime import datetime, date, timezone
from shapely.geometry import box
import requests
from dateutil.parser import parse

def create_stac_item(row):
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

def create_stac_collection(items, collection_id="my-collection"): #TODO : collection_id à passer en paramètre
    """
    Create a STAC Collection from a list of STAC Items.

    Args:
        items (list): List of pystac.Item objects.
        collection_id (str): Collection identifier.

    Returns:
        pystac.Collection: The generated STAC Collection.
    """
    # Compute spatial and temporal extent from items
    boxes = [box(*item.bbox) for item in items]
    all_bounds = gpd.GeoSeries(boxes).total_bounds
    datetimes = [item.datetime for item in items if item.datetime]
    if not datetimes:
        raise ValueError("Aucun datetime trouvé dans les items pour créer la collection.")
    spatial_extent = SpatialExtent([list(all_bounds)])
    temporal_extent = TemporalExtent([[min(datetimes), max(datetimes)]])
    extent = Extent(spatial=spatial_extent, temporal=temporal_extent)
    collection = Collection(
        id=collection_id,
        description="A STAC Collection generated from PostGIS data.", #TODO: hardcoded description
        extent=extent,
        title="My Collection", #TODO: hardcoded title
        license="proprietary" #TODO: hardcoded license
    )
    return collection

def validate_stac(stac_obj, stac_type="item"):
    """
    Validate a STAC object (item or collection) using pydantic models.

    Args:
        stac_obj (dict): The STAC object as a dictionary.
        stac_type (str): 'item' or 'collection'.

    Raises:
        ValidationError: If the object is not valid.
    """
    try:
        if stac_type == "item":
            PydanticItem(**stac_obj)
        elif stac_type == "collection":
            PydanticCollection(**stac_obj)
        else:
            raise ValueError("stac_type must be 'item' or 'collection'")
        print("STAC validation successful.")
    except ValidationError as e:
        print("STAC validation error:", e)
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

def post_collection_to_stac_api(collection, api_url="http://localhost:8081/collections"):  #TODO: hardcoded API URL
    """
    Post a STAC Collection to the STAC API.

    Args:
        collection (pystac.Collection): The collection to post.
        api_url (str): The STAC API endpoint for collections.

    Returns:
        requests.Response: The HTTP response object.
    """
    collection_json = collection.to_dict()
    response = requests.post(
        api_url,
        headers={"Content-Type": "application/json"},
        json=collection_json
    )
    print("POST /collections status:", response.status_code)
    print("Response:", response.text)
    return response

def post_item_to_stac_api(item, collection_id="my-collection", api_url="http://localhost:8081"): #TODO: hardcoded collection_id and API URL
    """
    Post a STAC Item to the STAC API.

    Args:
        item (pystac.Item): The item to post.
        collection_id (str): The collection ID.
        api_url (str): The STAC API base URL.

    Returns:
        requests.Response: The HTTP response object.
    """
    item_json = item.to_dict()
    url = f"{api_url}/collections/{collection_id}/items"
    response = requests.post(
        url,
        headers={"Content-Type": "application/json"},
        json=item_json
    )
    print(f"POST /collections/{collection_id}/items status:", response.status_code)
    print("Response:", response.text)
    return response

def print_stac_api_summary(api_url="http://localhost:8081"): #TODO: hardcoded API URL
    """
    Print a summary of collections and items from the STAC API.

    Args:
        api_url (str): The STAC API base URL.
    """
    print("\n--- Collections via API ---")
    r = requests.get(f"{api_url}/collections")
    print(r.json())

    print("\n--- Items de my-collection via API ---")
    r = requests.get(f"{api_url}/collections/my-collection/items") #TODO: hardcoded collection name
    print(r.json())