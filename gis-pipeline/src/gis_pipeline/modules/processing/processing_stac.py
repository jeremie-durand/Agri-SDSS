from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from collections import OrderedDict
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

import geopandas as gpd
import numpy as np
import structlog
from dateutil.parser import parse
from gis_pipeline.core.config import Config
from gis_pipeline.core.logging_setup import handle_error
from gis_pipeline.services.mapping import (
    STAC_COLLECTION_TEMPLATE,
    STAC_ITEM_TEMPLATE,
    ColumnMappings,
    DatePatterns,
    DefaultMetadata,
)
from pydantic import BaseModel, Field, ValidationError
from pystac import Asset, Collection, Extent, Item, SpatialExtent, TemporalExtent
from requests import RequestException, Session
from requests.adapters import HTTPAdapter, Retry
from shapely.geometry import box
from stac_pydantic.collection import Collection as PydanticCollection
from stac_pydantic.item import Item as PydanticItem

logger = structlog.get_logger()


# ---------------------------------------
# Precomputed constants
# ---------------------------------------
# precompute datetime keys and their case variants once
_DATETIME_KEYS = ColumnMappings.DATETIME.value.alias + [
    ColumnMappings.DATETIME.value.canonical
]

_DATETIME_KEY_VARIANTS = []

for k in _DATETIME_KEYS:
    _DATETIME_KEY_VARIANTS.extend([k, k.upper(), k.lower()])

# preserve order, remove duplicates
_DATETIME_KEY_VARIANTS = list(OrderedDict.fromkeys(_DATETIME_KEY_VARIANTS))

_DATETIME_KEYS_LOWER = {k.lower() for k in _DATETIME_KEYS}


# ---------------------------------------
# Helper functions
# ---------------------------------------
def _ensure_datetime_with_tz(dt: str | datetime | date) -> datetime:
    """Ensure a datetime object is timezone-aware (UTC).

    Args:
        dt: The input date or datetime.

    Returns:
        Timezone-aware datetime object.

    Notes:
        STAC requires datetime fields to be timezone-aware.
    """
    if isinstance(dt, str):
        try:
            dt = parse(dt)
        except Exception:
            return None

    # Handle date and datetime objects
    if isinstance(dt, date) and not isinstance(dt, datetime):
        return datetime(dt.year, dt.month, dt.day, tzinfo=timezone.utc)

    if isinstance(dt, datetime):
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)

    logger.debug("Invalid datetime value: %r", dt)
    return None


def _clean_metadata(obj) -> dict:
    """Recursively clean metadata for STAC compliance.

    Args:
        obj: The input metadata object (dict, list, or primitive).

    Returns:
        Cleaned metadata object.
    """
    # If given a numpy scalar at top level, convert it to native Python type
    if isinstance(obj, np.generic):
        try:
            obj = obj.item()
        except Exception:
            # Fallback: leave as-is if conversion unexpectedly fails
            pass
    if isinstance(obj, dict):  # Recursively clean dictionary values
        return {k: _clean_metadata(v) for k, v in obj.items()}
    elif isinstance(obj, list):  # Recursively clean list elements
        return [_clean_metadata(v) for v in obj]
    elif isinstance(obj, float) and (
        np.isnan(obj) or np.isinf(obj)
    ):  # Handle NaN and Inf
        return None
    elif isinstance(obj, (date, datetime)):  # Convert dates/datetimes to ISO strings
        return obj.isoformat().replace("+00:00", "Z")
    else:
        return obj


def _parse_xml_metadata(xml_path: Path) -> dict:
    """Parse XML metadata from a file into a dictionary.

    Args:
        xml_path: Path to the XML metadata file.

    Returns:
        Parsed metadata as a dictionary.
    """
    logger.info("Parsing XML metadata from file.")

    properties = {}

    try:
        if not xml_path.exists():
            logger.warning(f"aux.xml file {xml_path} does not exist.")
            return DefaultMetadata.get_defaults()

        if not xml_path.is_file():
            logger.warning(f"aux.xml path {xml_path} is not a file.")
            return DefaultMetadata.get_defaults()

        # Parse the XML file
        tree = ET.parse(xml_path)
        root = tree.getroot()

        # Find all band elements and extract their descriptions
        for band in root.findall(".//PAMRasterBand"):
            band_num = band.attrib.get("band")
            desc_elem = band.find("Description")
            if band_num and desc_elem is not None and desc_elem.text:
                properties[f"band_{band_num}_description"] = desc_elem.text

        logger.info(f"Extracted band descriptions: {properties}")

    except ET.ParseError as e:
        logger.error(f"XML parsing error for {xml_path}: {e}")
        return DefaultMetadata.get_defaults()
    except FileNotFoundError as e:
        logger.error(f"File not found: {xml_path} - {e}")
        return DefaultMetadata.get_defaults()
    except PermissionError as e:
        logger.error(f"Permission denied reading {xml_path}: {e}")
        return DefaultMetadata.get_defaults()
    except Exception as e:
        logger.error(f"Unexpected error reading aux.xml {xml_path}: {e}")
        return DefaultMetadata.get_defaults()

    if not properties:
        logger.warning(f"No band descriptions found in {xml_path}.")
        return DefaultMetadata.get_defaults()

    return properties


def _extract_datetime_from_metadata(metadata: dict | None) -> datetime | None:
    """Extract datetime from metadata only.

    Args:
        metadata: Metadata dictionary.
    """
    if not metadata:
        return None

    # 1) explicit keys and common raster tag keys (case-insensitive)
    meta_lc = (
        {k.lower(): v for k, v in metadata.items()}
        if isinstance(metadata, dict)
        else {}
    )

    for key_lc in _DATETIME_KEYS_LOWER:
        if key_lc in meta_lc:
            val = meta_lc[key_lc]
            logger.debug(
                "Found datetime in metadata key/tag (normalized) '%s': %r", key_lc, val
            )
            dt = _ensure_datetime_with_tz(val)
            if dt is not None:
                return dt

    # 2) shallow nested values
    for v in metadata.values():
        if isinstance(v, (str, date, datetime)):
            dt = _ensure_datetime_with_tz(v)
            if dt is not None:
                return dt

    return None


def _extract_datetime_from_filename(filename: str | None) -> datetime | None:
    """Extract datetime from filename using fast regex + manual parsing.

    Args:
        filename: Filename string.
    """
    if not filename:
        return None

    # 1) full timestamp or date
    for pat in DatePatterns.PATTERNS.value:
        m = re.search(pat, filename)
        if not m:
            continue

        val = m.group(0)
        cleaned = re.sub(r"[_T-]", "", val)

        # Full timestamp = 14 digits
        if len(cleaned) == 14 and cleaned.isdigit():
            try:
                y = int(cleaned[0:4])
                mo = int(cleaned[4:6])
                d = int(cleaned[6:8])
                hh = int(cleaned[8:10])
                mm = int(cleaned[10:12])
                ss = int(cleaned[12:14])
                return datetime(y, mo, d, hh, mm, ss, tzinfo=timezone.utc)
            except ValueError:
                pass

        # Pure date YYYYMMDD
        if len(val) == 8 and val.isdigit():
            try:
                y = int(val[0:4])
                mo = int(val[4:6])
                d = int(val[6:8])
                return datetime(y, mo, d, 0, 0, 0, tzinfo=timezone.utc)
            except ValueError:
                pass

    # 2) fallback: year-only
    m = re.search(DatePatterns.YEAR_PATTERN.value, filename)
    if m:
        try:
            year = int(m.group("year"))
            return datetime(year, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        except ValueError:
            pass

    return None


def _extract_datetime_from_sources(
    metadata: Optional[dict] = None,
    filename: Optional[str] = None,
) -> Optional[datetime]:
    """Try metadata first, then filename, else fallback."""

    # 1. Try metadata
    dt = _extract_datetime_from_metadata(metadata)
    if dt:
        return dt

    # 2. Try filename
    dt = _extract_datetime_from_filename(filename)
    if dt:
        return dt

    # 3. Final fallback
    return Config.DEFAULT_DATETIME


# ---------------------------------------
# STAC Item processing
# ---------------------------------------
def _create_stac_item_from_raster(
    raster_dict: dict, unique_id: str, asset_key: str = "data"
) -> Item:
    """Create a STAC Item from raster data.

    Args:
        raster_dict: Dictionary containing raster metadata and properties.
        unique_id: Unique identifier for the item.
        asset_key: Asset key name. e.g. "ndvi", "classification", "DEM", "soil".

    Returns:
        pystac.Item: The generated STAC Item.

    Notes:
        This function expects the raster_dict to contain geometry, bbox, datetime, and properties.
    """
    # Validate required fields
    geometry = raster_dict.get("geometry")
    if geometry is None:
        error_msg = "Raster data does not contain geometry information."
        handle_error(logger=logger, error_msg=error_msg, exc_class=ValueError)

    bbox = raster_dict.get("bbox")
    if bbox is None:
        error_msg = "Raster data does not contain bbox information."
        handle_error(logger=logger, error_msg=error_msg, exc_class=ValueError)

    # Prepare properties using template
    template = STAC_ITEM_TEMPLATE.copy()
    properties = template["properties"].copy()

    # Update with raster data
    raster_props = raster_dict.get("properties", {})
    if "metadata" in raster_dict:
        raster_props.update(raster_dict.get("metadata", {}))
    else:
        # Attempt to parse aux.xml for additional metadata
        file_url = raster_dict.get("file_url")
        if file_url:
            aux_path = Path(file_url).with_suffix(".aux.xml")
            aux_metadata = _parse_xml_metadata(aux_path)
            raster_props.update(aux_metadata)

    dt_raw = raster_dict.get("datetime")
    if dt_raw is None:
        dt_raw = _extract_datetime_from_sources(
            metadata=raster_dict.get("properties", {}) or raster_dict.get("tags", {}),
            filename=raster_dict.get("file_url"),
        )

    dt_value = _ensure_datetime_with_tz(dt_raw)

    # Fallback to default if still None
    if dt_value is None:
        dt_value = Config.DEFAULT_DATETIME

    # Update properties
    properties.update(_clean_metadata(raster_props))
    properties.update(
        {
            "datetime": dt_value,
            "updated": Config.NOW_DATETIME,
            "title": unique_id,
            "source": "cog_processing",
            "data_type": "raster",
            "description": raster_dict.get("description"),
        }
    )

    # Create item
    item = Item(
        id=unique_id,
        geometry=geometry,
        bbox=bbox,
        datetime=dt_value,
        properties=properties,
        stac_extensions=template.get("stac_extensions", []),
    )

    # Add main asset
    file_url = raster_dict.get("file_url")
    if file_url:
        item.add_asset(
            asset_key,
            Asset(
                href=file_url,
                media_type="image/tiff; application=geotiff",
                roles=["data"],
            ),
        )

    return item


def _build_single_stac_item(raster_dict: dict, idx: int, source_name: str) -> Item:
    """Build one STAC Item from a raster metadata dict.

    Args:
        raster_dict: Metadata for a single raster.
        idx: Loop index used to generate a fallback item ID.
        source_name: Source label attached to the item properties.

    Returns:
        A pystac.Item built from the raster metadata.

    Raises:
        ValueError: If ``raster_dict`` is not a dict or the item cannot be created.
    """
    if not isinstance(raster_dict, dict):
        error_msg = f"Raster data {idx} is not a dictionary: {type(raster_dict)}"
        handle_error(logger=logger, error_msg=error_msg, exc_class=ValueError)

    # Generate unique ID
    unique_id = raster_dict.get("id", f"{source_name}_{idx}")
    logger.debug(f"Processing raster data {idx}: {unique_id}")

    # Create the STAC item
    item = _create_stac_item_from_raster(raster_dict=raster_dict, unique_id=unique_id)

    if not isinstance(item, Item):
        error_msg = f"Failed to create valid Item object: {type(item)}"
        handle_error(logger=logger, error_msg=error_msg, exc_class=ValueError)

    item.properties.update({"source": source_name, "data_type": "raster"})
    logger.debug(f"Successfully created item {unique_id}")
    return item


def _validate_stac_items(items: list[Item]) -> None:
    """Validate each STAC item against the pystac schema.

    Args:
        items: List of pystac.Item objects to validate.
    """
    for item in items:
        if hasattr(item, "to_dict"):
            validate_stac(item.to_dict(), stac_type="item")
        else:
            validate_stac(item, stac_type="item")


def build_stac_items_from_cog(
    raster_metadata_list: list[dict], source_name: str = "Python gis_pipeline"
) -> list[Item]:
    """Build STAC items from a list of raster metadata dictionaries.

    Args:
        raster_metadata_list: List of dictionaries containing raster metadata.
        source_name: Name of the source for provenance tracking.

    Returns:
        list: List of STAC items created from the raster metadata.
    """
    logger.info(
        f"Building STAC items from {len(raster_metadata_list)} raster metadata entries"
    )

    items = []
    errors = []

    for idx, raster_dict in enumerate(raster_metadata_list):
        try:
            items.append(_build_single_stac_item(raster_dict, idx, source_name))
        except Exception as e:
            error_msg = f"Error creating STAC item {idx}: {e}"
            logger.error(error_msg)
            errors.append(error_msg)
            continue

    if not items and errors:
        error_msg = f"Failed to create any STAC items. Errors: {errors}"
        handle_error(logger=logger, error_msg=error_msg, exc_class=RuntimeError)

    if errors:
        logger.warning(f"Created {len(items)} items with {len(errors)} errors")

    logger.info(f"Created {len(items)} STAC items from raster metadata")

    # Validate all STAC items
    _validate_stac_items(items)
    return items


# ---------------------------------------
# STAC Collection processing
# ---------------------------------------
def _compute_spatial_extent(items: list[Item]) -> SpatialExtent:
    """Compute the bounding box for a list of STAC items.

    Args:
        items: List of pystac.Item objects, each with a valid ``bbox``.

    Returns:
        SpatialExtent covering all items.

    Raises:
        ValueError: If any item is missing a valid bbox.
    """
    boxes = []
    # Check if all items have a valid bbox
    for item in items:
        if not hasattr(item, "bbox") or not item.bbox:
            error_msg = f"Item {item.id} does not have a valid bbox."
            handle_error(logger=logger, error_msg=error_msg, exc_class=ValueError)
        boxes.append(box(*item.bbox))
    all_bounds = gpd.GeoSeries(boxes).total_bounds
    return SpatialExtent([list(all_bounds)])


def _compute_temporal_extent(items: list[Item]) -> TemporalExtent:
    """Compute the datetime range for a list of STAC items.

    Args:
        items: List of pystac.Item objects.

    Returns:
        TemporalExtent spanning the earliest and latest item datetimes.

    Raises:
        ValueError: If no items carry a datetime value.
    """
    datetimes = [item.datetime for item in items if getattr(item, "datetime", None)]
    if not datetimes:
        error_msg = "No datetime found in items to create the collection."
        handle_error(logger=logger, error_msg=error_msg, exc_class=ValueError)
    return TemporalExtent([[min(datetimes), max(datetimes)]])


def build_stac_collection_from_items(
    items: list[Item], collection_id: str
) -> Collection:  # default license="proprietary"
    """Create a STAC Collection from a list of pystac.Item objects.

    Args:
        items: List of pystac.Item objects.
        collection_id: Collection identifier.

    Returns:
        pystac.Collection: The generated STAC Collection.
    """
    for i, item in enumerate(items):
        logger.info(f"Item {i}: type={type(item)}, is_Item={isinstance(item, Item)}")
        if hasattr(item, "id"):
            logger.info(f"Item {i}: id={item.id}")
    logger.info("=== END DEBUG ===")
    logger.info(
        f"Creating STAC Collection with ID: {collection_id}, Title: {collection_id}"
    )

    if not items:
        error_msg = "The list of items is empty."
        handle_error(logger=logger, error_msg=error_msg, exc_class=ValueError)

    spatial_extent = _compute_spatial_extent(items)
    temporal_extent = _compute_temporal_extent(items)
    extent = Extent(spatial=spatial_extent, temporal=temporal_extent)

    template = STAC_COLLECTION_TEMPLATE.copy()
    template["id"] = collection_id
    template["description"] = "A STAC Collection generated from Python"
    template["extent"] = extent
    template["title"] = collection_id

    collection = Collection(**template)
    logger.info(f"Collection {collection_id} created with {len(items)} items.")

    # Validate STAC collection
    if hasattr(collection, "to_dict"):
        validate_stac(stac_obj=collection.to_dict(), stac_type="collection")
    else:
        validate_stac(stac_obj=collection, stac_type="collection")
    return collection


# ---------------------------------------
# STAC API interaction functions
# ---------------------------------------
def validate_stac(stac_obj: dict, stac_type: str):
    """Validate a STAC object (item or collection) using Pydantic models.

    Args:
        stac_obj: The STAC object as a dictionary.
        stac_type: Either 'item' or 'collection'.
    """
    if stac_type not in ("item", "collection"):
        error_msg = (
            "stac_type must be either 'item' or 'collection'. "
            f"It is currently: {stac_type}"
        )
        handle_error(logger=logger, error_msg=error_msg, exc_class=ValueError)

    try:
        if stac_type == "item":
            PydanticItem(**stac_obj)
        else:
            PydanticCollection(**stac_obj)
        logger.info(f"STAC {stac_type} validation successful.")
    except ValidationError as e:
        error_msg = f"STAC {stac_type} validation error: {str(e)}"
        handle_error(logger=logger, error_msg=error_msg, exc_class=ValueError)
    except Exception as e:
        error_msg = f"Unexpected error during STAC {stac_type} validation: {str(e)}"
        handle_error(logger=logger, error_msg=error_msg, exc_class=ValueError)


class StacApiResponse(BaseModel):
    """Structured and validated response for STAC API operations."""

    success: bool = Field(..., description="Whether the operation succeeded")
    status_code: int = Field(..., description="HTTP status code")
    message: str = Field(..., description="Informative message about the result")
    data: Optional[Any] = Field(
        None, description="Payload data (JSON or pystac object)"
    )


class StacApiClient:
    def __init__(
        self,
        api_url: str,
        collection_id: str,
        stac_collection: Collection,  # pystac.Collection
        stac_items: list[Item],  # list of pystac.Item
        retries: int = 3,
        backoff_factor: float = 0.3,
        logger: Optional[Any] = None,
    ):
        """Initialize the STAC API client with the base URL."""
        self.api_url = api_url
        self.collection_id = collection_id
        self.stac_collection = stac_collection
        self.stac_items = stac_items

        self.logger = logger if logger is not None else structlog.get_logger()

        self.session = Session()
        retry_strategy = Retry(
            total=retries,
            backoff_factor=backoff_factor,
            status_forcelist=[500, 502, 503, 504],
            allowed_methods=["GET", "POST", "DELETE", "PUT"],
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)

    def _request(
        self, method: str, endpoint: str, payload: Optional[Dict[str, Any]] = None
    ) -> StacApiResponse:
        """Generic HTTP request wrapper with retries and structured response.

        Args:
            method: HTTP method (e.g., GET, POST, DELETE, PUT).
            endpoint: API endpoint (e.g., '/collections').
            payload: JSON payload for POST/PUT requests.

        Returns:
            StacApiResponse: Structured response object.
        """
        url = f"{self.api_url}{endpoint}"
        self.logger.info(f"Making {method} request to {url} with payload: {payload}")

        try:
            response = self.session.request(
                method=method.upper(),
                url=url,
                headers={"Content-Type": "application/json"},
                json=_clean_metadata(payload),
                timeout=30,
            )
            self.logger.info(
                f"Received response: {response.status_code} {response.text}"
            )

            # Build response model
            data = None
            if response.content:
                try:
                    data = response.json()
                except ValueError:
                    data = response.text

            return StacApiResponse(
                success=response.ok,
                status_code=response.status_code,
                message=(
                    "Success"
                    if response.ok
                    else f"Error {response.status_code}: {response.text}"
                ),
                data=data,
            )

        except RequestException as e:
            self.logger.error(f"RequestException during {method} to {url}: {e}")
            return StacApiResponse(
                success=False, status_code=0, message=f"Network error: {e}"
            )

    def post_collection(self) -> StacApiResponse:
        """Post a STAC collection to the API.

        Returns:
            StacApiResponse: Structured response object.
        """
        self.logger.info(f"Posting collection {self.collection_id} to STAC API.")
        collection_dict = _clean_metadata(self.stac_collection.to_dict())
        resp = self._request(
            method="POST",
            endpoint="/collections",
            payload=collection_dict,
        )

        resp.message = (
            f"Collection {self.collection_id} created successfully."
            if resp.success
            else resp.message
        )
        return resp

    def _upsert_single_item(self, item_dict: dict, item_id: str) -> tuple[bool, str]:
        """POST one STAC item; fall back to PUT on 409 Conflict.

        Args:
            item_dict: STAC item payload as a plain dict.
            item_id: Unique item identifier (used in the PUT URL and log messages).

        Returns:
            ``(success, result_str)`` where ``result_str`` is ``"success"`` or an
            error description.
        """
        endpoint = f"/collections/{self.collection_id}/items"
        self.logger.info(
            f"Posting item {item_id} to collection {self.collection_id} (POST)"
        )

        resp = self._request(method="POST", endpoint=endpoint, payload=item_dict)

        # Retry with PUT if item already exists (409 Conflict)
        if resp.status_code == 409:
            self.logger.info(f"Item {item_id} already exists, updating via PUT...")
            resp = self._request(
                method="PUT",
                endpoint=f"{endpoint}/{item_id}",
                payload=item_dict,
            )

        if resp.success:
            return True, "success"
        return False, f"error ({resp.status_code})"

    def upsert_items(self) -> StacApiResponse:
        """Post or update STAC items to the API.

        Returns:
            StacApiResponse: Structured response object.
        """
        success_count = 0
        error_count = 0
        results: Dict[str, str] = {}

        for stac_item in self.stac_items:
            item_dict = _clean_metadata(stac_item.to_dict())
            item_id = stac_item.id

            try:
                ok, result_str = self._upsert_single_item(item_dict, item_id)
                if ok:
                    success_count += 1
                else:
                    error_count += 1
                results[item_id] = result_str
            except Exception as e:
                error_count += 1
                results[item_id] = f"exception ({e})"
                self.logger.exception(f"Error while upserting {item_id}: {e}")

        return StacApiResponse(
            success=(error_count == 0),
            status_code=200 if error_count == 0 else 207,
            message=f"Upsert finished ({success_count} success, {error_count} errors)",
            data={
                "success": success_count,
                "errors": error_count,
                "results": results,
            },
        )
