# demo/processing_stac.py
import logging

logger = logging.getLogger(__name__)

import xml.etree.ElementTree as ET
from datetime import date, datetime, timezone
from pathlib import Path

import geopandas as gpd
import rasterio
import requests
from dateutil.parser import parse
from demo.config import Config
from demo.init_postgis import read_data_postgis
from demo.mapping import vector_columns_mapping
from pydantic import ValidationError
from pystac import Asset, Collection, Extent, Item, SpatialExtent, TemporalExtent
from shapely.geometry import box, mapping
from stac_pydantic.collection import Collection as PydanticCollection
from stac_pydantic.item import Item as PydanticItem
import sqlalchemy


def create_stac_item_from_vector(row: dict) -> Item:
    """Create a STAC Item from a row of data.

    Args:
        row: Dictionary containing item data.

    Returns:
        pystac.Item or None: The generated STAC Item, or None if not enough data.

    Notes:
        - This function expects the row to contain a geometry and metadata.
        - It also ensures that the datetime fields are timezone-aware.
    """
    # Check if the row has a geometry and metadata
    geometry = mapping(row["geom"])
    properties = row.get("metadata") or {}  # Use metadata if available in a dict format

    # Ensure datetime fields are timezone-aware
    start = (
        ensure_datetime_with_tz(row.get("start_date"))
        if row.get("start_date") is not None
        else None
    )
    end = (
        ensure_datetime_with_tz(row.get("end_date"))
        if row.get("end_date") is not None
        else None
    )

    # Create the STAC Item
    if start is not None and end is not None and start <= end:
        item = Item(
            id=str(row["gid"]),
            geometry=geometry,
            bbox=list(gpd.GeoSeries([row["geom"]]).total_bounds),
            datetime=start,
            properties=properties,
            start_datetime=start,
            end_datetime=end,
        )
    elif start is not None:
        item = Item(
            id=str(row["gid"]),
            geometry=geometry,
            bbox=list(gpd.GeoSeries([row["geom"]]).total_bounds),
            datetime=start,
            properties=properties,
        )
    else:
        return None

    # Add the asset if file_url is present
    if row.get("file_url"):
        item.add_asset(
            "data", Asset(href=row["file_url"], media_type="application/octet-stream")
        )
    return item


def build_stac_items_from_table(
    engine: sqlalchemy.engine.Engine, table: str
) -> list[Item]:
    """Build STAC items from a PostGIS table.

    Args:
        engine: SQLAlchemy engine connected to the database.
        table: Name of the PostGIS table to read.

    Returns:
        list: List of STAC items created from the table data.
    """
    logger.info(f"Building STAC items from table '{table}'...")
    data_vector = read_data_postgis(engine, table)
    item_vector = []
    for _, row in data_vector.iterrows():
        stac_row = {}
        for stac_col, real_col in vector_columns_mapping.items():
            stac_row[stac_col] = getattr(row, real_col, None)
        item = create_stac_item_from_vector(stac_row)
        if item is not None:
            item_vector.append(item)
    return item_vector


def create_stac_item_from_raster(
    raster_path: Path, item_id: str = None, asset_key: str = "data"
) -> Item:
    """Create a STAC Item from a local raster file.

    Args:
        raster_path: Path to the raster file.
        item_id: Optional ID for the item.
        asset_key: Asset key name. e.g. "ndvi", "classification", "DEM", "soil".

    Returns:
        pystac.Item or None: The generated STAC Item, or None if not enough data.
    """
    if not raster_path or not Path(raster_path).exists():
        raise ValueError(f"Raster file {raster_path} does not exist.")

    raster_filename = Path(raster_path).name  # Get the filename
    if asset_key == "" or asset_key.replace(" ", "") == "":
        asset_key = "data"
    raster_url = f"{Config.RASTER_URL_PREFIX.rstrip('/')}/{raster_filename}"  # Construct the URL for the raster file

    # Open the raster file
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

        # Extract metadata from raster
        # If not available, raise a warning
        if not src.crs:
            logger.warning(
                f"The raster file {raster_path} does not have a spatial reference system (CRS) defined. EPSG 4326 will be used by default."
            )
        epsg = src.crs.to_epsg() if src.crs and src.crs.to_epsg() else 4326
        properties = {
            "raster:bands": src.count,
            "proj:epsg": epsg,
        }

        aux_path = raster_path.with_suffix(raster_path.suffix + ".aux.xml")
        if aux_path.exists():
            properties.update(parse_aux_xml(str(aux_path)))

    logger.info(f"Found EPSG: {src.crs.to_epsg()}")
    logger.info(
        f"aux.xml meta: {parse_aux_xml(aux_path)}"
        if aux_path.exists()
        else "No aux.xml"
    )

    logger.info(f"Final properties: {properties}")
    if item_id is None:
        item_id = raster_filename

    item = Item(
        id=item_id,
        geometry=geometry,
        bbox=bbox,
        datetime=dt,
        properties=properties,
    )

    # Add the raster asset
    item.add_asset(
        asset_key, Asset(href=raster_url, media_type="image/tiff; application=geotiff")
    )

    # Add a tiles asset for the COG
    item.add_asset(
        "tiles",
        Asset(
            href=f"http://localhost:8082/cog/tiles/{{z}}/{{x}}/{{y}}.png?url={raster_url}",
            media_type="image/png",
            roles=["tiles"],
        ),
    )
    return item


def create_stac_collection(
    items: list[Item], collection_id: str, title: str
) -> Collection:  # default license="proprietary"
    """Create a STAC Collection from a list of pystac.Item objects.

    Args:
        items: List of pystac.Item objects.
        collection_id: Collection identifier.
        title: Title of the collection (default: "My Collection").

    Returns:
        pystac.Collection: The generated STAC Collection.
    """
    logger.info(f"Creating STAC Collection with ID: {collection_id}, Title: {title}")

    if not items:
        logger.error("The list of items is empty.")
        raise ValueError("The list of items is empty.")

    # Compute spatial extent
    boxes = []
    # Check if all items have a valid bbox
    for item in items:
        if not hasattr(item, "bbox") or not item.bbox:
            logger.error(f"Item {item.id} does not have a valid bbox.")
            raise ValueError(f"Item {item.id} does not have a valid bbox.")
        boxes.append(box(*item.bbox))
    all_bounds = gpd.GeoSeries(boxes).total_bounds

    # Compute temporal extent
    datetimes = [item.datetime for item in items if getattr(item, "datetime", None)]
    if not datetimes:
        logger.error("No datetime found in items to create the collection.")
        raise ValueError("No datetime found in items to create the collection.")

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


def validate_stac(stac_obj: dict, stac_type: str):
    """Validate a STAC object (item or collection) using Pydantic models.

    Args:
        stac_obj: The STAC object as a dictionary.
        stac_type: Either 'item' or 'collection'.

    Raises:
        ValidationError: If the STAC object does not conform to the expected schema.
        ValueError: If stac_type is not 'item' or 'collection'.
    """
    try:
        if stac_type == "item":
            PydanticItem(**stac_obj)
        elif stac_type == "collection":
            PydanticCollection(**stac_obj)
        else:
            raise ValueError(
                f"stac_type must be either 'item' or 'collection'. It is currently: {stac_type}"
            )
        logger.info(f"STAC {stac_type} validation successful.")
    except ValidationError as e:
        logger.error(f"STAC {stac_type} validation failed: {e}")
        raise


def ensure_datetime_with_tz(dt: str | datetime | date) -> datetime:
    """Ensure a datetime object is timezone-aware (UTC).

    Args:
        dt: The input date or datetime.

    Returns:
        Timezone-aware datetime object.
    """
    if isinstance(dt, str):
        dt = parse(dt)
    if isinstance(dt, date) and not isinstance(dt, datetime):
        return datetime(dt.year, dt.month, dt.day, tzinfo=timezone.utc)
    elif isinstance(dt, datetime):
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    return dt


def parse_aux_xml(aux_path: str) -> dict:
    """Parse the aux.xml file to extract band descriptions.

    Args:
        aux_path: Path to the aux.xml file.

    Returns:
        Dictionary with band descriptions.
    """
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
        logger.error(f"Reading error aux.xml: {e}")
    return properties


class StacApiClient:
    def __init__(self, api_url: str):
        """Initialize the STAC API client with the base URL."""
        self.api_url = api_url

    def post_collection(self, collection: Collection) -> requests.Response:
        """Post a STAC collection to the API.

        Args:
            collection: The STAC collection to post.

        Returns:
            The HTTP response from the API.
        """
        url = f"{self.api_url}/collections"
        response = requests.post(
            url, headers={"Content-Type": "application/json"}, json=collection.to_dict()
        )
        logger.info(f"POST /collections status: {response.status_code}")
        return response

    def post_item(self, item: Item, collection_id: str) -> requests.Response:
        """Post a STAC item to the API.

        Args:
            item: The STAC item to post.
            collection_id: The ID of the collection to which the item belongs.

        Returns:
            The HTTP response from the API.
        """
        url = f"{self.api_url}/collections/{collection_id}/items"
        if not hasattr(item, "to_dict"):
            logger.error(f"item is not a STAC Item: {type(item)}")
            raise ValueError("STAC item must be a pystac.Item object.")
        response = requests.post(
            url, headers={"Content-Type": "application/json"}, json=item.to_dict()
        )
        logger.info(
            f"POST /collections/{collection_id}/items status: {response.status_code}"
        )
        return response

    def delete_item(self, item_id: str, collection_id: str) -> bool:
        """Delete a STAC item from the API.

        Args:
            item_id: The ID of the item to delete.
            collection_id: The ID of the collection to which the item belongs.

        Returns:
            True if the item was deleted successfully, False otherwise.
        """
        if not item_id or not isinstance(item_id, str):
            logger.error("No valid item_id provided for deletion.")
            return False

        url = f"{self.api_url}/collections/{collection_id}/items/{item_id}"
        try:
            response = requests.delete(url)
            if response.status_code in [200, 204]:
                logger.info(f"Item {item_id} deleted successfully.")
                return True
            elif response.status_code == 404:
                logger.info(f"Item {item_id} does not exist, nothing deleted.")
                return True
            else:
                logger.error(
                    f"Failed to delete item {item_id}. HTTP code: {response.status_code}"
                )
                return False
        except requests.RequestException as e:
            logger.error(f"Network error while deleting item {item_id}: {e}")
            return False

    @staticmethod
    def create_and_validate_collection(items: list, collection_id: str):
        """Create a STAC collection from a list of items and validate it.

        Args:
            items: The list of STAC items to include in the collection.
            collection_id: The ID of the collection to create.

        Returns:
            The created and validated STAC collection.
        """
        logger.info("Starting the creation of the STAC collection...")
        collection = create_stac_collection(
            items, collection_id=collection_id, title=collection_id
        )
        try:
            validate_stac(collection.to_dict(), stac_type="collection")
        except ValueError as ve:
            logger.error(f"STAC validation error for the collection: {ve}")
            raise RuntimeError("Critical error during STAC collection validation")
        return collection

    def post_items(self, items: list, collection_id: str):
        """Post a list of STAC items to the API.

        Args:
            items: The list of STAC items to post.
            collection_id: The ID of the collection to which the items belong.

        Raises:
            ValueError: If any item is invalid.
        """
        logger.info("Posting vector items to the STAC API...")
        for item in items:
            try:
                validate_stac(item.to_dict(), stac_type="item")
            except (ValueError, ValidationError) as ve:
                logger.error(f"STAC validation error for item {item.id}: {ve}")
            else:
                self.refresh_and_post_item(item, collection_id)

    def refresh_and_post_item(self, item: Item, collection_id: str):
        """Refresh and post a STAC item to the API.

        Args:
            item: The STAC item to post.
            collection_id: The ID of the collection to which the item belongs.

        Notes:
            This function will first check if the item exists in the API. If it does,
            it will attempt to delete it before posting the updated item.
        """
        logger.info(f"Refreshing and posting item {item.id} to the STAC API...")
        item_id = item.id
        r = requests.get(f"{self.api_url}/collections/{collection_id}/items/{item_id}")
        if r.status_code in [200, 500]:
            logger.info(
                f"Item {item_id} exists or server error, attempting to delete..."
            )
            self.delete_item(item_id, collection_id)
        elif r.status_code == 404:
            logger.info(f"Item {item_id} does not exist in the API")
        else:
            logger.error(
                f"Unexpected error while checking item {item_id} in the API. Status code: {r.status_code}"
            )
        self.post_item(item, collection_id)
