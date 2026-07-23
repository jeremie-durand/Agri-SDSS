"""
Quebec LiDAR Derived Products Fetch Process

Fetches LiDAR-derived rasters (DTM, CHM, hillshade, slope) from the Quebec MRNF
open data portal for a given farm polygon, clips them to the farm bounding box,
converts to Cloud Optimized GeoTIFF (COG), and publishes to the STAC catalog.

Data source: https://www.donneesquebec.ca/recherche/dataset/produits-derives-de-base-du-lidar
"""

import hashlib
import json
import logging
import math
import os
import re
import subprocess
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

import numpy as np
import psycopg
import rasterio
import requests
from pygeoapi.process.base import BaseProcessor, ProcessorExecuteError
from rasterio.features import geometry_mask
from shapely.geometry import shape

from .config import ApiConfig, DatabaseConfig, FarmConfig, StorageConfig
from .lidar_backend.quebec_lidar_config import VALID_PRODUCTS
from .lidar_backend.quebec_lidar_tile_index import LidarTileIndex
from .quebec_lidar_fetch_metadata import PROCESS_METADATA

logger = logging.getLogger(__name__)


class LidarFetchProcessor(BaseProcessor):
    """Processor for fetching Quebec LiDAR-derived raster products."""

    # Area limit — no cloud-compute cost, but large areas produce very large COGs
    MAX_FARM_AREA_KM2: float = 200.0

    # Nodata value written to output COGs
    DEFAULT_NODATA: int = -9999

    # Spatial reference for output COGs
    DEFAULT_CRS: str = "EPSG:4326"

    # GDAL / COG settings
    COG_COMPRESSION: str = "DEFLATE"
    COG_BLOCKSIZE: int = 512
    COG_OVERVIEWS: str = "AUTO"

    # STAC settings
    STAC_COLLECTION_ID: str = "lidar_quebec"
    STAC_VERSION: str = "1.0.0"
    # Quebec bounding box (west, south, east, north)
    STAC_SPATIAL_EXTENT_BBOX: List[float] = [-79.75, 41.75, -56.0, 63.0]
    # Approximate acquisition start; MRNF campaigns began ~2015
    STAC_TEMPORAL_START: str = "2015-01-01T00:00:00Z"

    # Derived (non-MRNF) product and the MRNF product it's derived from
    ASPECT_PRODUCT: str = "aspect"
    ASPECT_SOURCE_PRODUCT: str = "dtm"

    # Default products when the caller omits 'products' — matches
    # PROCESS_METADATA["inputs"]["products"]["schema"]["default"]; excludes
    # aspect (opt-in only, since it triggers an extra gdaldem computation).
    DEFAULT_PRODUCTS: List[str] = ["dtm", "chm", "hillshade", "slope"]

    # Geographic calculation constants
    KM_PER_DEGREE: float = 111.32

    # API service ports
    DEFAULT_STAC_API_PORT: int = 8081
    DEFAULT_RASTER_API_PORT: int = 8082

    # API timeouts (seconds)
    API_TIMEOUT_SHORT: int = 10
    API_TIMEOUT_LONG: int = 30

    # Class-level cache so the collection existence check runs once per lifetime
    _collection_checked: bool = False

    def __init__(self, processor_def: Dict[str, Any]) -> None:
        super().__init__(processor_def, PROCESS_METADATA)
        self.output_dir: str = StorageConfig().LIDAR_OUTPUT_DIR

    # ------------------------------------------------------------------
    # Public entrypoint
    # ------------------------------------------------------------------

    def execute(
        self, data: Dict[str, Any], outputs: Optional[Any] = None
    ) -> Tuple[str, Dict[str, Any]]:
        """
        Execute the LiDAR fetch and processing workflow.

        Args:
            data: Input parameters from process request.
            outputs: Optional output configuration (unused).

        Returns:
            Tuple of (mimetype, result_dict).
        """
        mimetype = "application/json"

        try:
            farm_geometry: Optional[Dict[str, Any]] = data.get("farm_geometry")
            farm_id: Optional[int] = data.get("farm_id")
            products: List[str] = data.get("products", self.DEFAULT_PRODUCTS)

            # ----------------------------------------------------------
            # Input validation
            # ----------------------------------------------------------
            if farm_geometry is None and farm_id is None:
                raise ProcessorExecuteError(
                    "Either 'farm_geometry' or 'farm_id' must be provided"
                )
            if farm_geometry is not None and farm_id is not None:
                raise ProcessorExecuteError(
                    "Provide only one of 'farm_geometry' or 'farm_id', not both"
                )
            if farm_id is not None and farm_id <= 0:
                raise ProcessorExecuteError(
                    f"farm_id must be a positive integer, got: {farm_id}"
                )

            unknown = set(products) - set(VALID_PRODUCTS)
            if unknown:
                raise ProcessorExecuteError(
                    f"Unknown product(s): {sorted(unknown)}. "
                    f"Valid values: {VALID_PRODUCTS}"
                )

            # ----------------------------------------------------------
            # Resolve geometry
            # ----------------------------------------------------------
            geometry_geojson: Dict[str, Any]
            farm_identifier: str

            if farm_id is not None:
                geometry_geojson = self._get_geometry_from_db(farm_id)
                farm_identifier = f"farm_{farm_id}"
            else:
                geometry_geojson = farm_geometry  # type: ignore[assignment]
                geom_shape_pre = shape(geometry_geojson)
                bbox_key = "_".join(f"{v:.4f}" for v in geom_shape_pre.bounds)
                farm_identifier = (
                    f"geom_{hashlib.md5(bbox_key.encode()).hexdigest()[:8]}"
                )

            # ----------------------------------------------------------
            # Compute bbox and validate area
            # ----------------------------------------------------------
            geom_shape = shape(geometry_geojson)
            bbox: Tuple[float, float, float, float] = geom_shape.bounds  # (W,S,E,N)

            area_km2 = self._calculate_area_km2(bbox)
            if area_km2 > self.MAX_FARM_AREA_KM2:
                raise ProcessorExecuteError(
                    f"Farm area ({area_km2:.1f} km²) exceeds maximum allowed "
                    f"({self.MAX_FARM_AREA_KM2} km²)"
                )

            # ----------------------------------------------------------
            # Tile lookup
            # ----------------------------------------------------------
            fetch_products: List[str] = [
                p for p in products if p != self.ASPECT_PRODUCT
            ]
            if (
                self.ASPECT_PRODUCT in products
                and self.ASPECT_SOURCE_PRODUCT not in fetch_products
            ):
                fetch_products.append(self.ASPECT_SOURCE_PRODUCT)

            tile_index = LidarTileIndex()
            tile_urls = tile_index.get_tile_urls(bbox, fetch_products)

            missing = set(fetch_products) - set(tile_urls)
            if missing:
                logger.warning(
                    "No LiDAR tiles found for products %s within bbox %s",
                    sorted(missing),
                    bbox,
                )
            if not tile_urls:
                raise ProcessorExecuteError(
                    f"No LiDAR tiles found for the supplied geometry "
                    f"(bbox={bbox}). The area may not be covered by MRNF LiDAR data."
                )
            if (
                self.ASPECT_PRODUCT in products
                and self.ASPECT_SOURCE_PRODUCT not in tile_urls
            ):
                raise ProcessorExecuteError(
                    "Cannot compute 'aspect': no DTM tiles found for the "
                    f"supplied geometry (bbox={bbox}). Aspect is derived "
                    "from DTM."
                )

            # ----------------------------------------------------------
            # Stream → clip → COG → STAC for each fetched product
            # ----------------------------------------------------------
            stac_items: List[Dict[str, Any]] = []
            assets: Dict[str, Dict[str, Any]] = {}
            cog_paths: Dict[str, str] = {}

            for product, urls in tile_urls.items():
                logger.info(
                    "Processing LiDAR product '%s' (%d tile(s))", product, len(urls)
                )

                # Stream tiles directly via /vsicurl/ — no full download needed.
                # gdalwarp fetches only the blocks covering the bbox.
                vsicurl_paths = [f"/vsicurl/{url}" for url in urls]

                cog_filename = f"lidar_{product}_{farm_identifier}.tif"
                cog_path = os.path.join(self.output_dir, cog_filename)

                self._get_or_build_cog(
                    cog_path,
                    product,
                    lambda: self._clip_and_convert_to_cog(
                        vsicurl_paths, cog_path, bbox
                    ),
                )

                cog_paths[product] = cog_path

                if product not in products:
                    # Fetched only as an input dependency (DTM for aspect
                    # derivation) — not a product the caller asked for.
                    continue

                self._add_product_asset(
                    assets=assets,
                    stac_items=stac_items,
                    product=product,
                    cog_path=cog_path,
                    geometry_geojson=geometry_geojson,
                    bbox=bbox,
                    farm_identifier=farm_identifier,
                )

            # ----------------------------------------------------------
            # Derive aspect from DTM, if requested
            # ----------------------------------------------------------
            if self.ASPECT_PRODUCT in products:
                dtm_cog_path = cog_paths[self.ASPECT_SOURCE_PRODUCT]
                aspect_filename = (
                    f"lidar_{self.ASPECT_PRODUCT}_{farm_identifier}.tif"
                )
                aspect_cog_path = os.path.join(self.output_dir, aspect_filename)

                self._get_or_build_cog(
                    aspect_cog_path,
                    self.ASPECT_PRODUCT,
                    lambda: self._compute_aspect_cog(dtm_cog_path, aspect_cog_path),
                )

                self._add_product_asset(
                    assets=assets,
                    stac_items=stac_items,
                    product=self.ASPECT_PRODUCT,
                    cog_path=aspect_cog_path,
                    geometry_geojson=geometry_geojson,
                    bbox=bbox,
                    farm_identifier=farm_identifier,
                )

            # ----------------------------------------------------------
            # Build response: existing assets/stac_items structure, plus a
            # flat slope/aspect summary for callers that don't need to
            # parse STAC asset internals (e.g. external integrations).
            # ----------------------------------------------------------
            summary: Dict[str, Any] = {}
            if "slope" in assets:
                summary["slope"] = assets["slope"]["statistics"]
            if self.ASPECT_PRODUCT in assets:
                summary[self.ASPECT_PRODUCT] = assets[self.ASPECT_PRODUCT][
                    "statistics"
                ]

            return mimetype, {
                "stac_items": [item["id"] for item in stac_items],
                "assets": assets,
                "bbox": list(bbox),
                "products": list(assets.keys()),
                **summary,
            }

        except ProcessorExecuteError:
            raise
        except Exception as exc:
            logger.error(
                "Unexpected error in LidarFetchProcessor: %s", exc, exc_info=True
            )
            raise ProcessorExecuteError(f"LiDAR fetch failed: {exc}") from exc

    # ------------------------------------------------------------------
    # Geometry helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _get_geometry_from_db(farm_id: int) -> Dict:
        """Retrieve farm geometry from PostGIS database."""
        try:
            conn_params = DatabaseConfig().to_conn_params()
            farm = FarmConfig()

            with psycopg.connect(**conn_params) as conn:
                with conn.cursor() as cur:
                    table_name: str = farm.FARM_TABLE_NAME
                    geom_column: str = farm.FARM_GEOMETRY_COLUMN
                    id_column: str = farm.FARM_ID_COLUMN

                    if not re.match(r"^[a-zA-Z0-9_.-]+$", table_name):
                        raise ProcessorExecuteError(
                            "Invalid table name format in FARM_TABLE_NAME"
                        )
                    if not re.match(r"^[a-zA-Z0-9_]+$", geom_column):
                        raise ProcessorExecuteError(
                            "Invalid geometry column name format in FARM_GEOMETRY_COLUMN"
                        )
                    if not re.match(r"^[a-zA-Z0-9_]+$", id_column):
                        raise ProcessorExecuteError(
                            "Invalid ID column name format in FARM_ID_COLUMN"
                        )

                    query: str = f"""
                        SELECT ST_AsGeoJSON({geom_column}) as geom
                        FROM {table_name}
                        WHERE {id_column} = %s
                    """
                    cur.execute(query, (farm_id,))
                    result = cur.fetchone()

                    if not result:
                        raise ProcessorExecuteError(
                            f"Farm ID {farm_id} not found in database"
                        )

                    try:
                        return json.loads(result[0])
                    except json.JSONDecodeError as exc:
                        raise ProcessorExecuteError(
                            f"Invalid geometry data for farm ID {farm_id}: {exc}"
                        ) from exc

        except psycopg.Error as exc:
            raise ProcessorExecuteError(
                f"Database error retrieving farm geometry: {exc}"
            ) from exc

    @staticmethod
    def _calculate_area_km2(bounds: Tuple[float, float, float, float]) -> float:
        """Calculate approximate area in km² from a bounding box in EPSG:4326."""
        lon_span: float = bounds[2] - bounds[0]
        lat_span: float = bounds[3] - bounds[1]
        lat_mid: float = (bounds[1] + bounds[3]) / 2
        km_per_deg_lon: float = LidarFetchProcessor.KM_PER_DEGREE * math.cos(
            math.radians(lat_mid)
        )
        km_per_deg_lat: float = LidarFetchProcessor.KM_PER_DEGREE
        return lon_span * km_per_deg_lon * lat_span * km_per_deg_lat

    # ------------------------------------------------------------------
    # Raster processing
    # ------------------------------------------------------------------

    def _get_or_build_cog(
        self, cog_path: str, product: str, build: Callable[[], None]
    ) -> None:
        """
        Reuse an existing COG at cog_path, or build it via the supplied
        callback. Shared by the tile-fetch loop and the aspect-derivation
        step, which both cache by output path.
        """
        if os.path.exists(cog_path):
            logger.info(
                "Cache hit: reusing existing COG for '%s': %s", product, cog_path
            )
        else:
            build()

    def _clip_and_convert_to_cog(
        self,
        input_paths: List[str],
        output_path: str,
        bbox: Tuple[float, float, float, float],
    ) -> None:
        """
        Clip one or more raster sources to bbox and write a COG.

        Sources are passed directly to gdalwarp — use /vsicurl/<url> paths to
        stream only the required blocks over HTTP without a full download.
        Multiple inputs are mosaicked implicitly by gdalwarp.
        """
        west, south, east, north = bbox
        cmd: List[str] = [
            "gdalwarp",
            "-te",
            str(west),
            str(south),
            str(east),
            str(north),
            "-te_srs",
            self.DEFAULT_CRS,
            "-t_srs",
            self.DEFAULT_CRS,
            "-of",
            "COG",
            "-co",
            f"COMPRESS={self.COG_COMPRESSION}",
            "-co",
            "NUM_THREADS=ALL_CPUS",
            "-co",
            f"OVERVIEWS={self.COG_OVERVIEWS}",
            "-co",
            f"BLOCKSIZE={self.COG_BLOCKSIZE}",
            "-dstnodata",
            str(self.DEFAULT_NODATA),
            "-overwrite",
            *input_paths,
            output_path,
        ]
        result: subprocess.CompletedProcess = subprocess.run(
            cmd, capture_output=True, text=True
        )
        if result.returncode != 0:
            raise ProcessorExecuteError(
                f"gdalwarp clip/COG conversion failed: {result.stderr}"
            )

    def _compute_aspect_cog(self, dtm_path: str, output_path: str) -> None:
        """
        Derive an aspect raster (compass bearing in degrees, 0=North) from a
        clipped DTM COG. Aspect is not a native MRNF product, so it's
        computed locally instead of fetched from a tile URL. Flat cells get
        nodata (-9999) by default, which _masked_zonal_values excludes.
        """
        cmd: List[str] = [
            "gdaldem",
            "aspect",
            dtm_path,
            output_path,
            "-of",
            "COG",
            "-co",
            f"COMPRESS={self.COG_COMPRESSION}",
            "-co",
            "NUM_THREADS=ALL_CPUS",
            "-co",
            f"OVERVIEWS={self.COG_OVERVIEWS}",
            "-co",
            f"BLOCKSIZE={self.COG_BLOCKSIZE}",
        ]
        result: subprocess.CompletedProcess = subprocess.run(
            cmd, capture_output=True, text=True
        )
        if result.returncode != 0:
            raise ProcessorExecuteError(
                f"gdaldem aspect computation failed: {result.stderr}"
            )

    # ------------------------------------------------------------------
    # Zonal statistics (exact polygon, not bounding box)
    # ------------------------------------------------------------------

    @staticmethod
    def _masked_zonal_values(cog_path: str, geometry: Dict[str, Any]) -> np.ndarray:
        """
        Return raster values at pixels that are both valid (not nodata) and
        inside the exact polygon geometry — not just its bounding box, which
        is what the COG itself is clipped to.
        """
        with rasterio.open(cog_path) as src:
            band = src.read(1, masked=True)
            polygon_mask = geometry_mask(
                [geometry],
                out_shape=(src.height, src.width),
                transform=src.transform,
                invert=True,
            )
        nodata_mask = np.ma.getmaskarray(band)
        valid = polygon_mask & ~nodata_mask
        return band.data[valid]

    def _slope_statistics(
        self, cog_path: str, geometry: Dict[str, Any]
    ) -> Dict[str, Optional[float]]:
        """Mean slope in degrees and percent, over the exact farm polygon."""
        values = self._masked_zonal_values(cog_path, geometry)
        if values.size == 0:
            return {"mean_degrees": None, "mean_percent": None}
        mean_degrees = float(values.mean())
        # Percent must be averaged per-pixel (tan is nonlinear) — converting
        # the mean degrees value afterward would be mathematically wrong.
        percent_values = np.tan(np.radians(values)) * 100.0
        mean_percent = float(percent_values.mean())
        return {"mean_degrees": mean_degrees, "mean_percent": mean_percent}

    def _aspect_statistics(
        self, cog_path: str, geometry: Dict[str, Any]
    ) -> Dict[str, Optional[float]]:
        """
        Circular mean aspect in degrees (compass bearing, 0=North), over the
        exact farm polygon. Aspect wraps at 360/0, so a naive arithmetic
        mean is wrong (e.g. 350 deg and 10 deg must average to ~0 deg, not
        ~180 deg) — this uses vector averaging instead.
        """
        values = self._masked_zonal_values(cog_path, geometry)
        if values.size == 0:
            return {"mean_degrees": None}
        radians = np.radians(values)
        mean_rad = math.atan2(
            float(np.sin(radians).mean()), float(np.cos(radians).mean())
        )
        mean_degrees = math.degrees(mean_rad) % 360.0
        return {"mean_degrees": float(mean_degrees)}

    # ------------------------------------------------------------------
    # STAC helpers
    # ------------------------------------------------------------------

    def _add_product_asset(
        self,
        assets: Dict[str, Dict[str, Any]],
        stac_items: List[Dict[str, Any]],
        product: str,
        cog_path: str,
        geometry_geojson: Dict[str, Any],
        bbox: Tuple[float, float, float, float],
        farm_identifier: str,
    ) -> None:
        """
        Build the STAC asset entry (with statistics) for one product and
        publish its STAC item, appending both to the caller's accumulators.
        dtm/chm/hillshade keep the existing bounding-box mean; slope/aspect
        use the exact-polygon statistics added in Tasks 4-5.
        """
        if product == "slope":
            with rasterio.open(cog_path) as src:
                data_type = str(src.dtypes[0])
            statistics: Dict[str, Optional[float]] = self._slope_statistics(
                cog_path, geometry_geojson
            )
        elif product == self.ASPECT_PRODUCT:
            with rasterio.open(cog_path) as src:
                data_type = str(src.dtypes[0])
            statistics = self._aspect_statistics(cog_path, geometry_geojson)
        else:
            with rasterio.open(cog_path) as src:
                data_type = str(src.dtypes[0])
                band = src.read(1, masked=True)
                mean_val = float(band.mean()) if band.count() > 0 else None
            statistics = {"mean": mean_val}

        assets[product] = {
            "href": cog_path,
            "type": "image/tiff; application=geotiff; profile=cloud-optimized",
            "roles": ["data"],
            "title": self._get_product_title(product),
            "statistics": statistics,
            "raster:bands": [
                {
                    "nodata": self.DEFAULT_NODATA,
                    "data_type": data_type,
                    "description": self._get_product_description(product),
                }
            ],
        }

        stac_item = self._create_stac_item(
            item_id=f"lidar_{product}_{farm_identifier}",
            geometry=geometry_geojson,
            bbox=tuple(bbox),
            product=product,
            asset=assets[product],
        )
        stac_items.append(stac_item)

    def _create_stac_item(
        self,
        item_id: str,
        geometry: Dict[str, Any],
        bbox: Tuple[float, float, float, float],
        product: str,
        asset: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Build a STAC item and publish it to the STAC API."""
        stac_item: Dict[str, Any] = {
            "type": "Feature",
            "stac_version": self.STAC_VERSION,
            "stac_extensions": [
                "https://stac-extensions.github.io/projection/v1.0.0/schema.json",
                "https://stac-extensions.github.io/raster/v1.1.0/schema.json",
            ],
            "id": item_id,
            "geometry": geometry,
            "bbox": list(bbox),
            "properties": {
                "datetime": datetime.now(timezone.utc)
                .isoformat()
                .replace("+00:00", "Z"),
                "created": datetime.now(timezone.utc)
                .isoformat()
                .replace("+00:00", "Z"),
                "platform": "lidar-mrnf",
                "instruments": ["lidar"],
                "lidar:product": product,
                "lidar:source": "MRNF Quebec open data",
                "proj:epsg": 4326,
            },
            "assets": {product: asset},
            "links": [],
        }

        self._post_to_stac_api(stac_item)
        return stac_item

    def _ensure_collection_exists(self) -> None:
        """Ensure the lidar_quebec collection exists in the STAC API."""
        if LidarFetchProcessor._collection_checked:
            return

        stac_api_url: str = ApiConfig().STAC_API_URL
        collection_id: str = self.STAC_COLLECTION_ID
        collection_url: str = f"{stac_api_url}/collections/{collection_id}"

        try:
            resp = requests.get(collection_url, timeout=self.API_TIMEOUT_SHORT)
            if resp.status_code == 200:
                logger.info("STAC collection %s already exists", collection_id)
                LidarFetchProcessor._collection_checked = True
                return
            elif resp.status_code != 404:
                logger.warning(
                    "Unexpected response checking collection: %s", resp.status_code
                )
                return

            collection: Dict[str, Any] = {
                "type": "Collection",
                "id": collection_id,
                "stac_version": self.STAC_VERSION,
                "title": "Quebec LiDAR Derived Products",
                "description": (
                    "LiDAR-derived raster products (DTM, CHM, hillshade, slope) "
                    "from the Quebec MRNF open data portal, clipped to individual "
                    "farm extents."
                ),
                "license": "OGL-Canada-2.0",
                "extent": {
                    "spatial": {"bbox": [self.STAC_SPATIAL_EXTENT_BBOX]},
                    "temporal": {"interval": [[self.STAC_TEMPORAL_START, None]]},
                },
                "links": [],
            }

            resp = requests.post(
                f"{stac_api_url}/collections",
                json=collection,
                headers={"Content-Type": "application/json"},
                timeout=self.API_TIMEOUT_LONG,
            )

            if resp.status_code in [200, 201]:
                logger.info("Created STAC collection %s", collection_id)
                LidarFetchProcessor._collection_checked = True
            else:
                logger.error(
                    "Failed to create STAC collection: %s - %s",
                    resp.status_code,
                    resp.text,
                )

        except requests.exceptions.RequestException as exc:
            logger.warning("Could not connect to STAC API to check collection: %s", exc)
        except Exception as exc:
            logger.error(
                "Error ensuring STAC collection exists: %s", exc, exc_info=True
            )

    def _post_to_stac_api(self, stac_item: Dict[str, Any]) -> bool:
        """Post a STAC item to the STAC API, updating if it already exists."""
        self._ensure_collection_exists()

        stac_api_url: str = ApiConfig().STAC_API_URL
        collection_id: str = self.STAC_COLLECTION_ID
        items_url: str = f"{stac_api_url}/collections/{collection_id}/items"
        item_id: str = stac_item["id"]

        try:
            resp = requests.post(
                items_url,
                json=stac_item,
                headers={"Content-Type": "application/json"},
                timeout=self.API_TIMEOUT_LONG,
            )

            if resp.status_code in [200, 201]:
                logger.info("Successfully posted STAC item %s", item_id)
                return True
            elif resp.status_code == 409:
                logger.info("STAC item %s already exists, updating…", item_id)
                resp = requests.put(
                    f"{items_url}/{item_id}",
                    json=stac_item,
                    headers={"Content-Type": "application/json"},
                    timeout=self.API_TIMEOUT_LONG,
                )
                if resp.ok:
                    logger.info("Successfully updated STAC item %s", item_id)
                    return True
                logger.error(
                    "Failed to update STAC item: %s - %s", resp.status_code, resp.text
                )
                return False
            else:
                logger.error(
                    "Failed to post STAC item: %s - %s", resp.status_code, resp.text
                )
                return False

        except requests.exceptions.Timeout:
            logger.error("Timeout posting STAC item %s", item_id)
            return False
        except requests.exceptions.RequestException as exc:
            logger.error("Network error posting STAC item %s: %s", item_id, exc)
            return False
        except Exception as exc:
            logger.error(
                "Unexpected error posting STAC item %s: %s", item_id, exc, exc_info=True
            )
            return False

    def _generate_preview_url(self, asset_href: str) -> str:
        """Generate TiTiler preview URL for an asset."""
        filename: str = os.path.basename(asset_href)
        raster_api_port: int = ApiConfig().RASTER_API_PORT
        raster_api_url: str = f"http://raster-api:{raster_api_port}"
        return f"{raster_api_url}/cog/preview.png?url=/data/{filename}"

    # ------------------------------------------------------------------
    # Product metadata helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _get_product_title(product: str) -> str:
        """Return a human-readable title for a product key."""
        titles: Dict[str, str] = {
            "dtm": "Digital Terrain Model (DTM)",
            "chm": "Canopy Height Model (CHM)",
            "hillshade": "Hillshade (Shaded Relief)",
            "slope": "Slope (degrees and percent)",
            "aspect": "Aspect (compass bearing, degrees)",
        }
        return titles.get(product, product.upper())

    @staticmethod
    def _get_product_description(product: str) -> str:
        """Return a short description for a product key."""
        descriptions: Dict[str, str] = {
            "dtm": "Bare-ground elevation in metres above sea level (1 m resolution)",
            "chm": "Vegetation height in metres derived as DSM − DTM (1 m resolution)",
            "hillshade": "Shaded relief computed from DTM (2 m resolution)",
            "slope": "Terrain slope in degrees computed from DTM (2 m resolution)",
            "aspect": (
                "Downslope compass bearing in degrees (0=North, clockwise), "
                "derived from DTM via gdaldem aspect (1 m resolution); not a "
                "native MRNF product"
            ),
        }
        return descriptions.get(product, "")
