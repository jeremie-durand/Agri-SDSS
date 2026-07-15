"""
Earth Observation Sentinel-2 Data Fetch Process

This process fetches Sentinel-2 data from openEO backends for a given farm polygon,
calculates vegetation indices (NDVI, EVI, SAVI) and other products, converts to COG,
and stores in STAC catalog.
"""

import hashlib
import json
import logging
import math
import os
import re
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple, Union

import openeo
import psycopg
import rasterio
import requests
from openeo.rest import JobFailedException
from pygeoapi.process.base import BaseProcessor, ProcessorExecuteError
from shapely.geometry import MultiPolygon, Polygon, shape

from .config import ApiConfig, DatabaseConfig, FarmConfig
from .eo_backend import vegetation_indices as veg_indices
from .eo_sentinel_fetch_metadata import PROCESS_METADATA

logger = logging.getLogger(__name__)


def _extract_cog_stats(cog_path: str) -> Dict[int, Any]:
    """Return per-band min/max/mean/std stats from a COG file."""
    with rasterio.open(cog_path) as src:
        stats: Dict[int, Any] = {}
        for i in src.indexes:
            band_data = src.read(i, masked=True)
            if band_data.count() > 0:
                stats[i] = {
                    "min": float(band_data.min()),
                    "max": float(band_data.max()),
                    "mean": float(band_data.mean()),
                    "std": float(band_data.std()),
                }
            else:
                stats[i] = {"min": None, "max": None, "mean": None, "std": None}
    return stats


class SentinelFetchProcessor(BaseProcessor):
    """Processor for fetching and processing Sentinel-2 data via openEO"""

    # Area limits
    MAX_FARM_AREA_KM2: float = 100.0

    # Nodata values
    DEFAULT_NODATA: int = -9999

    # OpenEO configuration
    OPENEO_BACKEND_URL: str = "openeo.dataspace.copernicus.eu"
    SENTINEL2_COLLECTION: str = "SENTINEL2_L2A"
    # Sentinel-2 L2A surface reflectance is stored as integer DN with QUANTIFICATION_VALUE=10000.
    # Ref: ESA Sentinel-2 Product Specification Document (S2-PDGS-TAS-DI-PSD), §Field QUANTIFICATION_VALUE.
    SENTINEL2_SCALE_FACTOR: float = 0.0001
    TOKEN_EXPIRY_MSG: str = (
        "Both the primary (OPENEO_REFRESH_TOKEN env var) and fallback (refresh-tokens.json config file) tokens expire after approximately 30 days."
    )
    TOKEN_SCRIPT_PATH: str = "./mos-pygeoapi/scripts/get_openeo_token.sh"
    OPENEO_CONFIG_HOME_DEFAULT: str = "~/.local/share/openeo-python-client"
    # Placeholder patterns to detect unconfigured tokens (case-insensitive)
    TOKEN_PLACEHOLDER_PATTERNS: Tuple[str, ...] = (
        "default_refresh_token_value_here",
        "your_refresh_token_here",
        "placeholder",
        "changeme",
    )

    # Spatial reference
    DEFAULT_CRS: str = "EPSG:4326"

    # EVI coefficients from Huete et al. (2002), doi:10.1016/S0034-4257(02)00096-2
    # Formula: EVI = G * (NIR - Red) / (NIR + C1*Red - C2*Blue + L)
    EVI_COEFF_G: float = 2.5  # Gain factor
    EVI_COEFF_C1: float = 6.0  # Aerosol resistance coefficient (red)
    EVI_COEFF_C2: float = 7.5  # Aerosol resistance coefficient (blue)
    EVI_COEFF_L: float = 1.0  # Canopy background adjustment
    # SAVI coefficients from Huete (1988), doi:10.1016/0034-4257(88)90106-X
    # Formula: SAVI = ((NIR - Red) / (NIR + Red + L)) * (1 + L)
    SAVI_COEFF: float = 1.5  # (1 + L) factor
    SAVI_L_FACTOR: float = (
        0.5  # Soil brightness correction (L=0.5 for intermediate cover)
    )

    # Geographic calculations
    KM_PER_DEGREE: float = 111.32

    # GDAL/COG configuration
    COG_COMPRESSION: str = "DEFLATE"
    COG_BLOCKSIZE: int = 512
    COG_OVERVIEWS: str = "AUTO"

    # STAC configuration
    STAC_COLLECTION_ID: str = "sentinel2_eo_products"
    STAC_VERSION: str = "1.0.0"
    STAC_SPATIAL_EXTENT_BBOX: List[float] = [
        -79.75,
        41.75,
        -56.0,
        51.75,
    ]  # Quebec bounding box (west, south, east, north)
    STAC_TEMPORAL_START: str = (
        "2024-01-01T00:00:00Z"  # Collection temporal extent start
    )

    # Raster metadata
    RASTER_DATA_TYPE: str = "float32"

    # Output directory
    DEFAULT_OUTPUT_DIR: str = "/data"

    # API service ports
    DEFAULT_STAC_API_PORT: int = 8081
    DEFAULT_RASTER_API_PORT: int = 8082

    # API timeouts (seconds)
    API_TIMEOUT_SHORT: int = 10
    API_TIMEOUT_LONG: int = 30

    # Class state
    _collection_checked: bool = False  # Cache for collection existence check

    def __init__(self, processor_def: Dict[str, Any]) -> None:
        super().__init__(processor_def, PROCESS_METADATA)
        self.output_dir: str = self.DEFAULT_OUTPUT_DIR  # Mounted volume in Docker

    @classmethod
    def _is_valid_token(cls, token: str) -> bool:
        """Check if a refresh token is valid (not a placeholder value).

        Args:
            token: The refresh token string to validate

        Returns:
            True if the token appears to be a real token, False if it matches
            a known placeholder pattern
        """
        if not token:
            return False

        token_lower = token.lower().strip()

        # Check against known placeholder patterns (case-insensitive)
        for pattern in cls.TOKEN_PLACEHOLDER_PATTERNS:
            if pattern.lower() in token_lower:
                return False

        # Reject suspiciously short tokens
        if (
            len(token) < 200
        ):  # arbitrary threshold for token length - real tokens are typically much longer
            logger.warning(
                f"Refresh token appears too short ({len(token)} chars). "
                "Valid tokens are typically 500+ characters."
            )
            return False

        return True

    @staticmethod
    def _get_geometry_from_db(farm_id: int) -> Dict:
        """
        Retrieve farm geometry from PostGIS database

        Args:
            farm_id: Database ID of the farm

        Returns:
            GeoJSON geometry dict
        """
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
                    except json.JSONDecodeError as e:
                        raise ProcessorExecuteError(
                            f"Invalid geometry data for farm ID {farm_id}: {str(e)}"
                        )

        except psycopg.Error as e:
            raise ProcessorExecuteError(
                f"Database error retrieving farm geometry: {str(e)}"
            )

    @staticmethod
    def _calculate_area_km2(bounds: Tuple[float, float, float, float]) -> float:
        """Calculate area in km² using simple approximation

        Args:
            bounds: Bounding box (west, south, east, north) in decimal degrees

        Returns:
            Approximate area in square kilometers

        Note:
            Bounds format is (minx, miny, maxx, maxy) i.e., (west, south, east, north)
        """
        longitude_span: float = bounds[2] - bounds[0]  # east - west
        latitude_span: float = bounds[3] - bounds[1]  # north - south
        # Approximate km at mid-latitude (1 degree ≈ 111 km)
        lat_mid: float = (bounds[1] + bounds[3]) / 2
        km_per_deg_lon: float = SentinelFetchProcessor.KM_PER_DEGREE * math.cos(
            math.radians(lat_mid)
        )
        km_per_deg_lat: float = SentinelFetchProcessor.KM_PER_DEGREE
        return longitude_span * km_per_deg_lon * latitude_span * km_per_deg_lat

    @staticmethod
    def _get_required_bands(output_products: List[str]) -> set:
        """Determine required Sentinel-2 bands based on requested products

        Args:
            output_products: List of products to generate
                Examples: ["ndvi"], ["evi", "savi"], ["true_color"]

        Returns:
            Set of required band identifiers (e.g., {"B02", "B04", "B08"})
        """
        required_bands: set = set()
        for product in output_products:
            if product in ["ndvi", "evi", "savi"]:
                required_bands.update(["B04", "B08"])  # Red, NIR
                if product == "evi":
                    required_bands.add("B02")  # Blue for EVI
            elif product == "true_color":
                required_bands.update(["B02", "B03", "B04"])  # Blue, Green, Red
            elif product == "raw_bands":
                required_bands.update(["B02", "B03", "B04", "B08"])
        return required_bands

    def _load_sentinel2_cube(
        self,
        connection: Any,
        bbox: Tuple[float, float, float, float],
        temporal_extent: List[str],
        required_bands: set,
        cloud_cover_max: float,
    ) -> Any:
        """Load and prepare Sentinel-2 data cube from openEO

        Args:
            connection: Authenticated openEO connection
            bbox: Bounding box (west, south, east, north) in decimal degrees
            temporal_extent: [start_date, end_date] in ISO 8601 format
            required_bands: Set of Sentinel-2 band identifiers to load
            cloud_cover_max: Maximum cloud cover percentage (0-100)

        Returns:
            Processed Sentinel-2 data cube with applied filters and scaling

        Raises:
            ProcessorExecuteError: If loading or processing data cube fails
        """
        try:
            s2_cube = connection.load_collection(
                self.SENTINEL2_COLLECTION,
                spatial_extent={
                    "west": bbox[0],
                    "south": bbox[1],
                    "east": bbox[2],
                    "north": bbox[3],
                    "crs": self.DEFAULT_CRS,
                },
                temporal_extent=temporal_extent,
                bands=list(required_bands),
                properties={"eo:cloud_cover": lambda cc: cc <= cloud_cover_max},
            )

            # Apply scale factor to convert DN to reflectance
            # Sentinel-2 L2A stores reflectance values as integers (0-10000)
            # Multiply by 0.0001 to get actual reflectance values (0.0-1.0, dimensionless)
            s2_cube = s2_cube.apply(lambda x: x * self.SENTINEL2_SCALE_FACTOR)

            return s2_cube

        except Exception as e:
            logger.error(f"Failed to load Sentinel-2 data: {str(e)}", exc_info=True)
            raise ProcessorExecuteError(
                "Failed to load Sentinel-2 data from OpenEO. Check server logs for details."
            )

    def _generate_assets(
        self,
        s2_cube: Any,
        geometry: Dict[str, Any],
        output_products: List[str],
        aggregation_method: str,
        temporal_extent: List[str],
        farm_identifier: str,
    ) -> Dict[str, Dict[str, Any]]:
        """Generate output assets from Sentinel-2 data cube

        Args:
            s2_cube: Loaded and prepared Sentinel-2 data cube
            geometry: GeoJSON geometry for masking
            output_products: List of products to generate
            aggregation_method: Temporal aggregation method
            temporal_extent: [start_date, end_date] for naming
            farm_identifier: Unique identifier for file naming

        Returns:
            Dict mapping product names to STAC asset metadata

        Raises:
            ProcessorExecuteError: If no output products could be generated
        """
        assets: Dict[str, Dict[str, Any]] = {}
        temp_dir: str = tempfile.mkdtemp()

        try:
            for product in output_products:
                try:
                    product_cube = self._calculate_product(
                        s2_cube, product, aggregation_method
                    )

                    # Mask to farm geometry
                    product_cube = product_cube.mask_polygon(geometry)

                    # Deterministic COG path — enables cache hit on repeat calls
                    cog_filename = f"sentinel2_{farm_identifier}_{product}_{temporal_extent[0]}_{temporal_extent[1]}.tif"
                    cog_path = os.path.join(self.output_dir, cog_filename)

                    if os.path.exists(cog_path):
                        logger.info(
                            f"Cache hit: {cog_filename}, skipping OpenEO download"
                        )
                        stats = _extract_cog_stats(cog_path)
                        assets[product] = {
                            "href": cog_path,
                            "type": "image/tiff; application=geotiff; profile=cloud-optimized",
                            "roles": (
                                ["data"] if product != "true_color" else ["visual"]
                            ),
                            "title": self._get_product_title(product),
                            "raster:bands": self._get_raster_bands_metadata(product),
                            "statistics": stats,
                        }
                        continue

                    # Download to temporary file
                    temp_file = os.path.join(temp_dir, f"{product}_temp.tif")
                    job = product_cube.execute_batch()
                    job.download_result(temp_file)

                    self._convert_to_cog(temp_file, cog_path)

                    # Extract metadata using masked arrays (rasterio has no .stats() method)
                    stats = _extract_cog_stats(cog_path)

                    assets[product] = {
                        "href": cog_path,
                        "type": "image/tiff; application=geotiff; profile=cloud-optimized",
                        "roles": ["data"] if product != "true_color" else ["visual"],
                        "title": self._get_product_title(product),
                        "raster:bands": self._get_raster_bands_metadata(product),
                        "statistics": stats,
                    }

                except (ValueError, KeyError) as e:
                    logger.warning(f"Data error processing {product}: {str(e)}")
                    continue
                except (OSError, IOError) as e:
                    logger.error(
                        f"File system error processing {product}: {str(e)}",
                        exc_info=True,
                    )
                    continue
                except rasterio.errors.RasterioIOError as e:
                    logger.error(
                        f"Raster I/O error processing {product}: {str(e)}",
                        exc_info=True,
                    )
                    continue
                except subprocess.CalledProcessError as e:
                    logger.error(
                        f"GDAL conversion failed for {product}: {str(e)}", exc_info=True
                    )
                    continue
                except JobFailedException as e:
                    logger.error(
                        "OpenEO job failed for %s: %s", product, e, exc_info=True
                    )
                    continue
                except Exception as e:
                    logger.error("Error processing %s: %s", product, e, exc_info=True)
                    continue

            if not assets:
                raise ProcessorExecuteError("Failed to generate any output products")

            return assets
        finally:
            # Clean up temporary files
            shutil.rmtree(temp_dir, ignore_errors=True)

    def _authenticate_with_env_token(self, connection: Any, refresh_token: str) -> None:
        """Authenticate using the OPENEO_REFRESH_TOKEN environment variable.

        Falls back to refresh-tokens.json config file if the env var token fails
        (e.g. expired). Raises ProcessorExecuteError if both paths fail.

        Args:
            connection: Active openEO connection
            refresh_token: Validated refresh token from the environment variable
        """
        logger.info(
            "Authenticating to openEO using OPENEO_REFRESH_TOKEN environment variable"
        )
        try:
            # Don't specify client_id - let openEO use the client that generated the token
            connection.authenticate_oidc_refresh_token(refresh_token=refresh_token)
            logger.info(
                "Successfully authenticated using environment variable refresh token"
            )
        except Exception as env_auth_error:
            logger.warning(
                f"Authentication failed with OPENEO_REFRESH_TOKEN (token may be expired): "
                f"{str(env_auth_error)}. Falling back to refresh-tokens.json config file.",
                exc_info=True,
            )
            try:
                connection.authenticate_oidc_refresh_token()
                logger.info(
                    "Successfully authenticated using stored refresh token from config file "
                    "(fallback after expired env var token)"
                )
            except Exception as config_auth_error:
                logger.error(
                    f"Authentication failed with config file fallback: {str(config_auth_error)}",
                    exc_info=True,
                )
                error_msg = (
                    f"OpenEO authentication failed. The OPENEO_REFRESH_TOKEN env var token is "
                    f"expired or invalid, and the config file fallback also failed. "
                    f"{self.TOKEN_EXPIRY_MSG} "
                    f"Please re-run: {self.TOKEN_SCRIPT_PATH} to obtain a new token."
                )
                raise ProcessorExecuteError(error_msg)

    def _authenticate_with_config_file(self, connection: Any) -> None:
        """Authenticate using the refresh-tokens.json config file (fallback / local dev).

        Used when OPENEO_REFRESH_TOKEN is not set or contains a placeholder value.
        The openEO client auto-loads the token from $OPENEO_CONFIG_HOME/refresh-tokens.json.
        Raises ProcessorExecuteError if the config file token is missing or invalid.

        Args:
            connection: Active openEO connection
        """
        logger.warning(
            "OPENEO_REFRESH_TOKEN not set or using placeholder value, "
            "falling back to refresh-tokens.json config file (OPENEO_CONFIG_HOME)"
        )
        try:
            connection.authenticate_oidc_refresh_token()
            logger.info(
                "Successfully authenticated using stored refresh token from config file"
            )
        except Exception as config_auth_error:
            logger.error(
                f"Authentication failed with config file: {str(config_auth_error)}",
                exc_info=True,
            )
            config_home = os.getenv(
                "OPENEO_CONFIG_HOME", self.OPENEO_CONFIG_HOME_DEFAULT
            )
            error_msg = (
                f"OpenEO authentication failed. No valid refresh token found. "
                f"Looked for refresh-tokens.json in OPENEO_CONFIG_HOME={config_home}. "
                f"{self.TOKEN_EXPIRY_MSG} "
                f"Please run: {self.TOKEN_SCRIPT_PATH} to set up authentication "
                f"and copy the token to your .env file. "
                f"Error details: {str(config_auth_error)}"
            )
            raise ProcessorExecuteError(error_msg)

    def _process_sentinel_data(
        self,
        bbox: Tuple[float, float, float, float],
        geometry: Dict[str, Any],
        temporal_extent: List[str],
        output_products: List[str],
        aggregation_method: str,
        cloud_cover_max: float,
        farm_identifier: str,
    ) -> Dict[str, Dict[str, Any]]:
        """
        Fetch Sentinel-2 data from openEO and generate requested products

        Args:
            bbox: Bounding box (west, south, east, north) in decimal degrees
                Example: (-73.5, 45.4, -73.3, 45.6)
            geometry: GeoJSON geometry for masking
            temporal_extent: [start_date, end_date] in ISO 8601 format (YYYY-MM-DD)
                Example: ["2024-06-01", "2024-08-31"]
            output_products: List of products to generate
                Example: ["ndvi", "evi", "true_color"]
            aggregation_method: Temporal aggregation method
                One of: "median", "max", "min", "mean"
            cloud_cover_max: Maximum allowed cloud cover percentage (0-100)
                Example: 20 (means 20% maximum cloud cover)
            farm_identifier: Unique identifier for file naming
                Example: "farm_123" or "farm_a1b2c3d4"

        Returns:
            Dict mapping product names to asset metadata
        """
        # Early-exit: serve all products from cache without connecting to OpenEO
        cached_assets: Dict[str, Dict[str, Any]] = {}
        for product in output_products:
            cog_filename = f"sentinel2_{farm_identifier}_{product}_{temporal_extent[0]}_{temporal_extent[1]}.tif"
            cog_path = os.path.join(self.output_dir, cog_filename)
            if os.path.exists(cog_path):
                try:
                    stats = _extract_cog_stats(cog_path)
                    cached_assets[product] = {
                        "href": cog_path,
                        "type": "image/tiff; application=geotiff; profile=cloud-optimized",
                        "roles": ["data"] if product != "true_color" else ["visual"],
                        "title": self._get_product_title(product),
                        "raster:bands": self._get_raster_bands_metadata(product),
                        "statistics": stats,
                    }
                    logger.info(f"Early cache hit: {cog_filename}, skipping OpenEO")
                except Exception as e:
                    logger.warning(
                        f"Cache read failed for {cog_filename}, will re-fetch: {e}"
                    )

        if len(cached_assets) == len(output_products):
            logger.info("All products served from cache — OpenEO connection skipped")
            return cached_assets

        # Connect to openEO backend (only reached when ≥1 product needs fetching)
        try:
            connection = openeo.connect(self.OPENEO_BACKEND_URL)

            # Primary: Try OPENEO_REFRESH_TOKEN environment variable
            refresh_token: Optional[str] = os.getenv("OPENEO_REFRESH_TOKEN")
            refresh_token = refresh_token.strip() if refresh_token else None

            if refresh_token and self._is_valid_token(refresh_token):
                self._authenticate_with_env_token(connection, refresh_token)
            else:
                self._authenticate_with_config_file(connection)

        except ProcessorExecuteError:
            raise
        except Exception as e:
            logger.error(f"Failed to connect to openEO: {str(e)}", exc_info=True)
            raise ProcessorExecuteError(
                f"Failed to connect to openEO backend: {str(e)}"
            )

        # Determine required bands based on requested products
        required_bands: set = self._get_required_bands(output_products)

        # Load Sentinel-2 L2A collection
        s2_cube = self._load_sentinel2_cube(
            connection, bbox, temporal_extent, required_bands, cloud_cover_max
        )

        # Generate output assets from data cube
        assets = self._generate_assets(
            s2_cube,
            geometry,
            output_products,
            aggregation_method,
            temporal_extent,
            farm_identifier,
        )

        return assets

    def _calculate_product(
        self, cube: Any, product: str, aggregation_method: str = "median"
    ) -> Any:
        """Calculate vegetation index or prepare product from data cube

        Args:
            cube: openEO data cube
            product: Product type to generate
            aggregation_method: Temporal aggregation method. Must be one of: "median", "max", "min", "mean"

        Returns:
            Processed data cube for the requested product
        """
        # Validate aggregation method
        valid_methods = ["median", "max", "min", "mean"]
        if aggregation_method not in valid_methods:
            raise ProcessorExecuteError(
                f"Invalid aggregation method '{aggregation_method}'. Must be one of: {', '.join(valid_methods)}"
            )

        # Apply temporal aggregation
        cube = cube.reduce_dimension(dimension="t", reducer=aggregation_method)

        if product == "ndvi":
            return veg_indices.calculate_ndvi(cube)

        elif product == "evi":
            return veg_indices.calculate_evi(
                cube,
                coeff_g=self.EVI_COEFF_G,
                coeff_c1=self.EVI_COEFF_C1,
                coeff_c2=self.EVI_COEFF_C2,
                coeff_l=self.EVI_COEFF_L,
            )

        elif product == "savi":
            return veg_indices.calculate_savi(
                cube, coeff=self.SAVI_COEFF, l_factor=self.SAVI_L_FACTOR
            )

        elif product == "true_color":
            return veg_indices.get_true_color(cube)

        elif product == "raw_bands":
            return veg_indices.get_raw_bands(cube)

        return cube

    def _convert_to_cog(self, input_path: str, output_path: str) -> None:
        """Convert GeoTIFF to Cloud Optimized GeoTIFF using gdalwarp"""
        cmd: List[str] = [
            "gdalwarp",
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
            "-t_srs",
            self.DEFAULT_CRS,
            "-dstnodata",
            str(self.DEFAULT_NODATA),
            "-overwrite",
            input_path,
            output_path,
        ]

        result: subprocess.CompletedProcess = subprocess.run(
            cmd, capture_output=True, text=True
        )
        if result.returncode != 0:
            raise ProcessorExecuteError(f"GDAL COG conversion failed: {result.stderr}")

    def _get_product_title(self, product: str) -> str:
        """Get human-readable title for product"""
        titles: Dict[str, str] = {
            "ndvi": "Normalized Difference Vegetation Index (NDVI)",
            "evi": "Enhanced Vegetation Index (EVI)",
            "savi": "Soil Adjusted Vegetation Index (SAVI)",
            "true_color": "True Color RGB Composite",
            "raw_bands": "Raw Sentinel-2 Bands",
        }
        return titles.get(product, product.upper())

    def _get_raster_bands_metadata(self, product: str) -> List[Dict]:
        """Get raster:bands metadata for STAC"""
        if product == "ndvi":
            return [
                {
                    "nodata": self.DEFAULT_NODATA,
                    "data_type": self.RASTER_DATA_TYPE,
                    "scale": 1.0,
                    "offset": 0.0,
                    "unit": "normalized difference",
                    "description": "NDVI values ranging from -1 to 1",
                }
            ]
        elif product == "evi":
            return [
                {
                    "nodata": self.DEFAULT_NODATA,
                    "data_type": self.RASTER_DATA_TYPE,
                    "scale": 1.0,
                    "offset": 0.0,
                    "unit": "enhanced vegetation index",
                    "description": "EVI values",
                }
            ]
        elif product == "savi":
            return [
                {
                    "nodata": self.DEFAULT_NODATA,
                    "data_type": self.RASTER_DATA_TYPE,
                    "scale": 1.0,
                    "offset": 0.0,
                    "unit": "soil adjusted vegetation index",
                    "description": "SAVI values",
                }
            ]
        elif product == "true_color":
            return [
                {"nodata": self.DEFAULT_NODATA, "name": "red", "common_name": "red"},
                {
                    "nodata": self.DEFAULT_NODATA,
                    "name": "green",
                    "common_name": "green",
                },
                {"nodata": self.DEFAULT_NODATA, "name": "blue", "common_name": "blue"},
            ]
        return [{"nodata": self.DEFAULT_NODATA}]

    def _create_stac_item(
        self,
        item_id: str,
        geometry: Dict[str, Any],
        bbox: Tuple[float, float, float, float],
        temporal_extent: List[str],
        assets: Dict[str, Dict[str, Any]],
        cloud_cover_max: float,
    ) -> Dict[str, Any]:
        """
        Create and publish STAC item to STAC API

        Args:
            item_id: Unique STAC item identifier (e.g., "sentinel2_farm_123_2024-06-01_2024-08-31")
            geometry: GeoJSON geometry dict with 'type' and 'coordinates' keys
                Example: {"type": "Polygon", "coordinates": [[[lon, lat], ...]]}
            bbox: Bounding box (west, south, east, north) in decimal degrees
                Example: (-73.5, 45.4, -73.3, 45.6)
            temporal_extent: [start_date, end_date] in ISO 8601 format (YYYY-MM-DD)
                Example: ["2024-06-01", "2024-08-31"]
            assets: Dictionary mapping product names to STAC asset metadata
                Each asset must include: href, type, roles, title, raster:bands, statistics
            cloud_cover_max: Maximum cloud cover percentage used for filtering (0-100)
                Example: 20.0

        Returns:
            STAC Item compliant with STAC v1.0.0 specification, including:
                - type: "Feature"
                - stac_version: STAC specification version
                - stac_extensions: List of extension schemas used
                - id: Unique item identifier
                - geometry: GeoJSON geometry
                - bbox: Bounding box coordinates
                - properties: Temporal and platform metadata
                - assets: Product asset dictionary
                - links: Related resource links (initially empty)
        """

        start: datetime = datetime.fromisoformat(temporal_extent[0])
        end: datetime = datetime.fromisoformat(temporal_extent[1])
        midpoint: datetime = start + (end - start) / 2

        stac_item: Dict[str, Any] = {
            "type": "Feature",
            "stac_version": self.STAC_VERSION,
            "stac_extensions": [
                "https://stac-extensions.github.io/projection/v1.0.0/schema.json",
                "https://stac-extensions.github.io/raster/v1.1.0/schema.json",
                "https://stac-extensions.github.io/eo/v1.0.0/schema.json",
            ],
            "id": item_id,
            "geometry": geometry,
            "bbox": list(bbox),
            "properties": {
                "datetime": midpoint.isoformat() + "Z",
                "start_datetime": temporal_extent[0] + "T00:00:00Z",
                "end_datetime": temporal_extent[1] + "T23:59:59Z",
                "created": datetime.now(timezone.utc)
                .isoformat()
                .replace("+00:00", "Z"),
                "platform": "sentinel-2",
                "instruments": ["msi"],
                "constellation": "sentinel-2",
                "mission": "copernicus",
                "processing:level": "L2A",
                "eo:cloud_cover": cloud_cover_max,
                "proj:epsg": 4326,
            },
            "assets": assets,
            "links": [],
        }

        # Post to STAC API
        self._post_to_stac_api(stac_item)

        return stac_item

    def _ensure_collection_exists(self) -> None:
        """Ensure the sentinel2_eo_products collection exists in STAC API"""
        if SentinelFetchProcessor._collection_checked:
            return

        stac_api_url: str = ApiConfig().STAC_API_URL
        collection_id: str = self.STAC_COLLECTION_ID
        collection_url: str = f"{stac_api_url}/collections/{collection_id}"

        try:
            # Check if collection exists
            resp = requests.get(collection_url, timeout=self.API_TIMEOUT_SHORT)
            if resp.status_code == 200:
                logger.info(f"STAC collection {collection_id} already exists")
                SentinelFetchProcessor._collection_checked = True
                return
            elif resp.status_code != 404:
                logger.warning(
                    f"Unexpected response checking collection: {resp.status_code}"
                )
                return

            # Collection doesn't exist, create it
            collection: Dict[str, Any] = {
                "type": "Collection",
                "id": collection_id,
                "stac_version": self.STAC_VERSION,
                "title": "Sentinel-2 Earth Observation Products",
                "description": "Processed Sentinel-2 products (NDVI, EVI, SAVI, True Color) generated from openEO backend",
                "license": "proprietary",
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
                logger.info(f"Created STAC collection {collection_id}")
                SentinelFetchProcessor._collection_checked = True
            else:
                logger.error(
                    f"Failed to create STAC collection: {resp.status_code} - {resp.text}"
                )

        except requests.exceptions.RequestException as e:
            logger.warning(f"Could not connect to STAC API to check collection: {e}")
        except Exception as e:
            logger.error(f"Error ensuring STAC collection exists: {e}", exc_info=True)

    def _post_to_stac_api(self, stac_item: Dict[str, Any]) -> bool:
        """Post STAC item to STAC API

        Args:
            stac_item: STAC item to post

        Returns:
            True if successful, False otherwise
        """
        # Ensure collection exists first
        self._ensure_collection_exists()

        stac_api_url: str = ApiConfig().STAC_API_URL
        collection_id: str = self.STAC_COLLECTION_ID
        items_url: str = f"{stac_api_url}/collections/{collection_id}/items"
        item_id: str = stac_item["id"]

        try:
            # POST new item
            resp = requests.post(
                items_url,
                json=stac_item,
                headers={"Content-Type": "application/json"},
                timeout=self.API_TIMEOUT_LONG,
            )

            if resp.status_code in [200, 201]:
                logger.info(f"Successfully posted STAC item {item_id} to STAC API")
                return True
            elif resp.status_code == 409:
                # Item already exists, try PUT to update
                logger.info(f"STAC item {item_id} exists, updating...")
                resp = requests.put(
                    f"{items_url}/{item_id}",
                    json=stac_item,
                    headers={"Content-Type": "application/json"},
                    timeout=self.API_TIMEOUT_LONG,
                )

                if resp.ok:
                    logger.info(f"Successfully updated STAC item {item_id}")
                    return True
                else:
                    logger.error(
                        f"Failed to update STAC item: {resp.status_code} - {resp.text}"
                    )
                    return False
            else:
                logger.error(
                    f"Failed to post STAC item: {resp.status_code} - {resp.text}"
                )
                return False

        except requests.exceptions.Timeout:
            logger.error(f"Timeout posting STAC item {item_id} to STAC API")
            return False
        except requests.exceptions.RequestException as e:
            logger.error(f"Network error posting STAC item {item_id}: {e}")
            return False
        except Exception as e:
            logger.error(
                f"Unexpected error posting STAC item {item_id}: {e}", exc_info=True
            )
            return False

    def _generate_preview_url(self, asset_href: str) -> str:
        """Generate TiTiler preview URL for asset"""
        filename: str = os.path.basename(asset_href)
        raster_api_port: int = ApiConfig().RASTER_API_PORT
        raster_api_url: str = f"http://raster-api:{raster_api_port}"
        return f"{raster_api_url}/cog/preview.png?url=/data/{filename}&rescale=0,1"

    def execute(
        self, data: Dict[str, Any], outputs: Optional[Any] = None
    ) -> Tuple[str, Dict[str, Any]]:
        """
        Execute the Sentinel-2 data fetch and processing workflow

        Args:
            data: Input parameters from process request
            outputs: Optional output configuration

        Returns:
            Tuple of (mimetype, result_dict)
        """
        mimetype = "application/json"

        try:
            farm_geometry: Optional[Dict[str, Any]] = data.get("farm_geometry")
            farm_id: Optional[int] = data.get("farm_id")
            temporal_extent: List[str] = data["temporal_extent"]
            output_products: List[str] = data["output_products"]
            aggregation_method: str = data.get("aggregation_method", "median")
            cloud_cover_max: float = data.get("cloud_cover_max", 20)

            if not 0 <= cloud_cover_max <= 100:
                raise ProcessorExecuteError(
                    f"'cloud_cover_max' must be between 0 and 100, got: {cloud_cover_max}"
                )

            # Validate that exactly one geometry source is provided
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
                    f"Farm ID must be a positive integer, got: {farm_id}"
                )

            # Validate temporal extent
            try:
                start_date: datetime = datetime.fromisoformat(temporal_extent[0])
                end_date: datetime = datetime.fromisoformat(temporal_extent[1])
                if start_date > end_date:
                    raise ProcessorExecuteError(
                        f"Start date ({temporal_extent[0]}) must be before or equal to end date ({temporal_extent[1]})"
                    )
            except (ValueError, IndexError) as e:
                raise ProcessorExecuteError(f"Invalid temporal extent format: {str(e)}")

            # Get farm geometry
            geometry_geojson: Dict[str, Any]
            farm_identifier: str

            if farm_id:
                geometry_geojson = self._get_geometry_from_db(farm_id)
            else:
                geometry_geojson = farm_geometry  # type: ignore

            # Extract bbox from geometry
            geom_shape: Union[Polygon, MultiPolygon] = shape(geometry_geojson)

            # Deterministic farm identifier: use farm_id or MD5 of bbox for geometry input
            if farm_id:
                farm_identifier = f"farm_{farm_id}"
            else:
                bbox_key = "_".join(f"{v:.4f}" for v in geom_shape.bounds)
                farm_identifier = (
                    f"geom_{hashlib.md5(bbox_key.encode()).hexdigest()[:8]}"
                )

            # Validate geometry
            if not geom_shape.is_valid:
                raise ProcessorExecuteError(
                    "Invalid geometry provided. Geometry must be a valid Polygon or MultiPolygon."
                )
            if geom_shape.is_empty:
                raise ProcessorExecuteError(
                    "Empty geometry provided. Geometry must contain coordinates."
                )

            bbox: Tuple[float, float, float, float] = (
                geom_shape.bounds
            )  # (west, south, east, north)

            # Validate farm size (prevent timeouts on large areas)
            area_km2: float = self._calculate_area_km2(geom_shape.bounds)
            if area_km2 > self.MAX_FARM_AREA_KM2:
                raise ProcessorExecuteError(
                    f"Farm area ({area_km2:.2f} km²) exceeds maximum allowed ({self.MAX_FARM_AREA_KM2} km²). "
                    "Please use a smaller polygon or contact administrator for async processing."
                )

            # Fetch and process Sentinel-2 data
            assets: Dict[str, Dict[str, Any]] = self._process_sentinel_data(
                bbox=bbox,
                geometry=geometry_geojson,
                temporal_extent=temporal_extent,
                output_products=output_products,
                aggregation_method=aggregation_method,
                cloud_cover_max=cloud_cover_max,
                farm_identifier=farm_identifier,
            )

            # Create STAC item
            stac_item_id: str = (
                f"sentinel2_{farm_identifier}_{temporal_extent[0]}_{temporal_extent[1]}"
            )
            stac_result: Dict[str, Any] = self._create_stac_item(
                item_id=stac_item_id,
                geometry=geometry_geojson,
                bbox=bbox,
                temporal_extent=temporal_extent,
                assets=assets,
                cloud_cover_max=cloud_cover_max,
            )

            # Generate preview URL for TiTiler
            preview_asset: Dict[str, Any] = (
                assets.get("ndvi")
                or assets.get("true_color")
                or list(assets.values())[0]
            )
            preview_url: str = self._generate_preview_url(preview_asset["href"])

            result: Dict[str, Any] = {
                "stac_item_id": stac_item_id,
                "stac_item": stac_result,
                "assets": {k: v["href"] for k, v in assets.items()},
                "preview_url": preview_url,
                "bbox": list(bbox),
                "temporal_extent": temporal_extent,
                "area_km2": round(area_km2, 2),
            }

            return mimetype, {"id": "result", "value": result}

        except ProcessorExecuteError:
            # Re-raise our own errors without wrapping
            raise
        except (KeyError, TypeError) as e:
            logger.error("Invalid input parameters: %s", e, exc_info=True)
            raise ProcessorExecuteError(
                "Invalid input parameters — check required fields and types."
            )
        except (ValueError, AttributeError) as e:
            logger.error("Data validation error: %s", e, exc_info=True)
            raise ProcessorExecuteError("Data validation error — check input values.")
        except Exception as e:
            logger.error(
                "Unexpected error processing Sentinel-2 data: %s", e, exc_info=True
            )
            raise ProcessorExecuteError("Unexpected error processing Sentinel-2 data.")

    def __repr__(self) -> str:
        return f"<SentinelFetchProcessor> {self.name}"
