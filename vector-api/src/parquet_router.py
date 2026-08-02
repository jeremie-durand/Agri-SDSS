"""Parquet Router for Vector API - OGC API Features style endpoints.

This module provides FastAPI routes for exposing GeoParquet files through
an OGC-compliant API interface under the /parquet namespace.
"""

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from .config import PARQUET_COLLECTIONS, PARQUET_PREFIX
from .duckdb_manager import (
    ColumnInfo,
    DuckDBManager,
    DuckDBSpatialExtensionError,
    ParquetSchemaInfo,
    get_shared_manager,
)

logger = logging.getLogger(__name__)

# OGC standard CRS for WGS84 longitude/latitude
OGC_CRS84 = "http://www.opengis.net/def/crs/OGC/1.3/CRS84"

router = APIRouter(prefix=PARQUET_PREFIX, tags=["Parquet Collections"])


def validate_collection_exists(collection_id: str) -> Path:
    """Validate collection ID and check if Parquet file exists.

    Delegates to the shared DuckDBManager so that the path is always
    resolved from the manager's authoritative ``data_dir``.

    Args:
        collection_id: The collection identifier.

    Returns:
        Path to the validated Parquet file.

    Raises:
        HTTPException: 400 if the collection ID is invalid, 404 if the
            collection does not exist, 503 if the DuckDB spatial extension
            cannot be loaded.
    """
    try:
        manager = get_shared_manager()
        parquet_path = manager.get_parquet_path(collection_id)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail="Invalid collection ID. Only alphanumeric characters, underscores, and hyphens are allowed.",
        )
    except DuckDBSpatialExtensionError as e:
        logger.error(f"Failed to initialize DuckDB manager: {e}")
        raise HTTPException(
            status_code=503,
            detail="Parquet service unavailable: DuckDB spatial extension could not be loaded. Please check server configuration.",
        )

    if parquet_path is None:
        raise HTTPException(
            status_code=404, detail=f"Collection not found: {collection_id}"
        )

    return parquet_path


def get_duckdb_manager() -> DuckDBManager:
    """Return the shared DuckDBManager singleton.

    Notes :
        A single connection is reused across all requests to avoid the overhead
        of loading the spatial extension on every call. Thread safety is handled
        internally by DuckDBManager via a per-instance lock.

    Raises:
        HTTPException: 503 if DuckDB spatial extension cannot be loaded.
    """
    try:
        return get_shared_manager()
    except DuckDBSpatialExtensionError as e:
        logger.error(f"Failed to initialize DuckDB manager: {e}")
        raise HTTPException(
            status_code=503,
            detail="Parquet service unavailable: DuckDB spatial extension could not be loaded. Please check server configuration.",
        )


def build_links(request: Request, collection_id: Optional[str] = None) -> List[Dict]:
    """Build OGC-style links for responses.

    Args:
        request: FastAPI request object for URL building.
        collection_id: Optional collection ID for item-level links.

    Returns:
        List of link dictionaries.
    """
    base_url = str(request.base_url).rstrip("/")
    links = []

    if collection_id:
        links.extend(
            [
                {
                    "href": f"{base_url}{PARQUET_COLLECTIONS}/{collection_id}",
                    "rel": "self",
                    "type": "application/json",
                    "title": "This collection",
                },
                {
                    "href": f"{base_url}{PARQUET_COLLECTIONS}/{collection_id}/items",
                    "rel": "items",
                    "type": "application/geo+json",
                    "title": "Items",
                },
                {
                    "href": f"{base_url}{PARQUET_COLLECTIONS}",
                    "rel": "parent",
                    "type": "application/json",
                    "title": "Collections",
                },
            ]
        )
    else:
        links.append(
            {
                "href": f"{base_url}{PARQUET_COLLECTIONS}",
                "rel": "self",
                "type": "application/json",
                "title": "Parquet Collections",
            }
        )

    return links


@router.get("/collections", response_class=JSONResponse)
async def list_collections(request: Request) -> Dict[str, Any]:
    """List all available Parquet collections.

    Args:
        request: FastAPI request object for URL building.

    Returns:
        OGC API Features style collection listing, auto-discovering
        all *.parquet files in the configured data directory.
    """
    try:
        manager = get_duckdb_manager()
        parquet_files = manager.list_parquet_files()

        collections = []
        for pf in parquet_files:
            collection_id = pf["id"]
            try:
                schema: ParquetSchemaInfo = manager.get_parquet_schema(collection_id)
                extent = None
                if schema.get("bbox"):
                    extent = {
                        "spatial": {
                            "bbox": [schema["bbox"]],
                            "crs": OGC_CRS84,
                        }
                    }

                collections.append(
                    {
                        "id": collection_id,
                        "title": pf["title"],
                        "description": f"GeoParquet collection: {collection_id}",
                        "extent": extent,
                        "itemType": "feature",
                        "crs": [OGC_CRS84],
                        "links": build_links(request, collection_id),
                    }
                )
            except Exception as e:
                logger.warning(
                    f"Could not get schema for {collection_id}: {e}", exc_info=True
                )
                collections.append(
                    {
                        "id": collection_id,
                        "title": pf["title"],
                        "description": f"Parquet file: {collection_id}",
                        "links": build_links(request, collection_id),
                    }
                )

        return {
            "collections": collections,
            "links": build_links(request),
            "numberMatched": len(collections),
            "numberReturned": len(collections),
        }
    except Exception as e:
        logger.error(f"Error listing collections: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/collections/{collection_id}", response_class=JSONResponse)
async def get_collection(request: Request, collection_id: str) -> Dict[str, Any]:
    """Get metadata for a specific Parquet collection.

    Args:
        request: FastAPI request object for URL building.
        collection_id: The collection identifier (Parquet filename without extension).

    Returns:
        OGC API Features style collection metadata.
    """
    try:
        # Validate collection exists before opening DB connection
        validate_collection_exists(collection_id)

        manager = get_duckdb_manager()
        schema: ParquetSchemaInfo = manager.get_parquet_schema(collection_id)

        extent = None
        if schema.get("bbox"):
            extent = {
                "spatial": {
                    "bbox": [schema["bbox"]],
                    "crs": OGC_CRS84,
                }
            }

        # Build queryables from schema
        queryables = []
        col: ColumnInfo
        for col in schema["columns"]:
            if (
                schema["geometry_column"] is None
                or col["name"] != schema["geometry_column"]
            ):
                queryables.append(
                    {
                        "name": col["name"],
                        "type": col["type"],
                    }
                )

        return {
            "id": collection_id,
            "title": collection_id.replace("_", " ").title(),
            "description": f"GeoParquet collection with {schema['feature_count']} features",
            "extent": extent,
            "itemType": "feature",
            "crs": [OGC_CRS84],
            "storageCrs": OGC_CRS84,
            "links": build_links(request, collection_id),
            "queryables": queryables,
            "numberMatched": schema["feature_count"],
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting collection {collection_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/collections/{collection_id}/items", response_class=JSONResponse)
async def get_items(
    request: Request,
    collection_id: str,
    limit: int = Query(
        default=10, ge=1, le=10000, description="Number of items to return"
    ),
    offset: int = Query(default=0, ge=0, description="Number of items to skip"),
    bbox: Optional[str] = Query(
        default=None,
        description="Bounding box filter: minx,miny,maxx,maxy",
    ),
) -> Dict[str, Any]:
    """Get items from a Parquet collection.

    Args:
        request: FastAPI request object for URL building.
        collection_id: The collection identifier.
        limit: Maximum number of items to return (default: 10, max: 10000).
        offset: Number of items to skip for pagination.
        bbox: Optional bounding box filter as comma-separated values.

    Returns:
        GeoJSON FeatureCollection.
    """
    try:
        # Parse bbox if provided
        bbox_tuple = None
        if bbox:
            try:
                parts = [float(x.strip()) for x in bbox.split(",")]
                if len(parts) != 4:
                    raise ValueError("bbox must have 4 values")
                min_lon, min_lat, max_lon, max_lat = parts
                if not (-180 <= min_lon <= 180 and -180 <= max_lon <= 180):
                    raise ValueError("Longitude must be between -180 and 180")
                if not (-90 <= min_lat <= 90 and -90 <= max_lat <= 90):
                    raise ValueError("Latitude must be between -90 and 90")
                if min_lon >= max_lon:
                    raise ValueError("min_lon must be less than max_lon")
                if min_lat >= max_lat:
                    raise ValueError("min_lat must be less than max_lat")
                bbox_tuple = tuple(parts)
            except (ValueError, AttributeError) as e:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid bbox format. Expected minx,miny,maxx,maxy: {e}",
                )

        # Validate collection exists before opening DB connection
        validate_collection_exists(collection_id)

        manager = get_duckdb_manager()
        result = manager.query_items(
            collection_id=collection_id,
            limit=limit,
            offset=offset,
            bbox=bbox_tuple,
        )

        base_url = str(request.base_url).rstrip("/")

        # Build query params string preserving bbox filter
        query_params = f"limit={limit}"
        if bbox:
            query_params += f"&bbox={bbox}"

        links = [
            {
                "href": f"{base_url}{PARQUET_COLLECTIONS}/{collection_id}/items?{query_params}&offset={offset}",
                "rel": "self",
                "type": "application/geo+json",
            },
            {
                "href": f"{base_url}{PARQUET_COLLECTIONS}/{collection_id}",
                "rel": "collection",
                "type": "application/json",
            },
        ]

        # Add pagination links (preserving query params)
        if offset > 0:
            prev_offset = max(0, offset - limit)
            links.append(
                {
                    "href": f"{base_url}{PARQUET_COLLECTIONS}/{collection_id}/items?{query_params}&offset={prev_offset}",
                    "rel": "prev",
                    "type": "application/geo+json",
                }
            )

        if offset + result["numberReturned"] < result["numberMatched"]:
            next_offset = offset + limit
            links.append(
                {
                    "href": f"{base_url}{PARQUET_COLLECTIONS}/{collection_id}/items?{query_params}&offset={next_offset}",
                    "rel": "next",
                    "type": "application/geo+json",
                }
            )

        return {
            "type": "FeatureCollection",
            "features": result["features"],
            "links": links,
            "numberMatched": result["numberMatched"],
            "numberReturned": result["numberReturned"],
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting items from {collection_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/collections/{collection_id}/items/{item_id}", response_class=JSONResponse)
async def get_item(
    request: Request, collection_id: str, item_id: str
) -> Dict[str, Any]:
    """Get a single item from a Parquet collection.

    Args:
        request: FastAPI request object for URL building.
        collection_id: The collection identifier.
        item_id: The item identifier (value of ID column or row number).

    Returns:
        GeoJSON Feature.
    """
    try:
        # Try to convert item_id to int if it looks numeric
        try:
            parsed_id = int(item_id)
        except ValueError:
            parsed_id = item_id

        # Validate collection exists before opening DB connection
        validate_collection_exists(collection_id)

        manager = get_duckdb_manager()
        feature = manager.get_item_by_id(collection_id, parsed_id)
        if not feature:
            raise HTTPException(
                status_code=404,
                detail=f"Item not found: {item_id} in collection {collection_id}",
            )

        base_url = str(request.base_url).rstrip("/")
        feature["links"] = [
            {
                "href": f"{base_url}/parquet/collections/{collection_id}/items/{item_id}",
                "rel": "self",
                "type": "application/geo+json",
            },
            {
                "href": f"{base_url}/parquet/collections/{collection_id}",
                "rel": "collection",
                "type": "application/json",
            },
        ]

        return feature
    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            f"Error getting item {item_id} from {collection_id}: {e}", exc_info=True
        )
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/collections/{collection_id}/queryables", response_class=JSONResponse)
async def get_queryables(request: Request, collection_id: str) -> Dict[str, Any]:
    """Get queryable properties for a Parquet collection.

    Args:
        request: FastAPI request object for URL building.
        collection_id: The collection identifier.

    Returns:
        JSON Schema describing queryable properties.
    """
    try:
        # Validate collection exists before opening DB connection
        validate_collection_exists(collection_id)

        manager = get_duckdb_manager()
        schema: ParquetSchemaInfo = manager.get_parquet_schema(collection_id)

        # Map DuckDB types to JSON Schema types
        type_mapping = {
            "INTEGER": "integer",
            "BIGINT": "integer",
            "SMALLINT": "integer",
            "TINYINT": "integer",
            "DOUBLE": "number",
            "FLOAT": "number",
            "DECIMAL": "number",
            "VARCHAR": "string",
            "BOOLEAN": "boolean",
            "DATE": "string",
            "TIMESTAMP": "string",
            "TIME": "string",
        }

        properties = {}
        col: ColumnInfo
        for col in schema["columns"]:
            if (
                schema["geometry_column"] is None
                or col["name"] != schema["geometry_column"]
            ):
                col_type = col["type"].upper()
                json_type = "string"  # default
                for duckdb_type, jtype in type_mapping.items():
                    if duckdb_type in col_type:
                        json_type = jtype
                        break

                properties[col["name"]] = {"type": json_type}

        base_url = str(request.base_url).rstrip("/")

        return {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": f"{base_url}/parquet/collections/{collection_id}/queryables",
            "type": "object",
            "title": f"Queryables for {collection_id}",
            "properties": properties,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            f"Error getting queryables for {collection_id}: {e}", exc_info=True
        )
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/collections/{collection_id}/invalidate", response_class=JSONResponse)
async def invalidate_collection(collection_id: str) -> Dict[str, Any]:
    """Drop any cached materialized connection for a collection.

    Called after an external rebuild (the manual CLI script or gis-pipeline's
    automatic trigger) swaps in a fresh .duckdb file for this collection, so
    the next request re-opens it instead of serving stale cached data.
    Idempotent: returns success whether or not anything was cached, and
    regardless of whether collection_id refers to a real collection at all.

    Args:
        collection_id: The collection identifier.

    Returns:
        Whether a cached connection was found and dropped.
    """
    manager = get_duckdb_manager()
    invalidated = manager.invalidate_materialized(collection_id)
    return {"collection_id": collection_id, "invalidated": invalidated}
