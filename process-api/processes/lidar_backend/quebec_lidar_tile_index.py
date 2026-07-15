"""
Quebec LiDAR Tile Index

Provides spatial lookup of MRNF LiDAR tile download URLs by bounding box.
The tile index is sourced from the publicly available GeoJSON published by
the Ministère des Ressources naturelles et des Forêts (MRNF).

Tile index URL:
  https://diffusion.mffp.gouv.qc.ca/Diffusion/DonneeGratuite/Foret/IMAGERIE/
  Produits_derives_LiDAR/Produit_derive_lidar/03-Telechargement/URL_Lidar.geojson

Each 15 km × 15 km tile carries URLs for four raster products (GeoTIFF):
  - MNT  : Digital Terrain Model (DTM)  — bare ground elevation, 1 m resolution
  - MHC  : Canopy Height Model (CHM)    — vegetation height (DSM − DTM), 1 m resolution
  - MNT_Ombre : Hillshade               — shaded relief, 2 m resolution
  - Pentes    : Slope                   — gradient in degrees, 2 m resolution
"""

import json
import logging
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import requests
from shapely.geometry import box, shape

from .quebec_lidar_config import (
    CACHE_TTL_SECONDS,
    DEFAULT_CACHE_PATH,
    DOWNLOAD_TIMEOUT_SECONDS,
    PRODUCT_COLUMN,
    TILE_INDEX_URL,
    VALID_PRODUCTS,
)

logger = logging.getLogger(__name__)


class LidarTileIndex:
    """
    Spatial index of Quebec MRNF LiDAR tiles.

    Downloads the GeoJSON tile index on first use and caches it to disk.
    Subsequent calls use the cache until it expires (24 h by default).
    """

    def __init__(
        self,
        cache_path: str = DEFAULT_CACHE_PATH,
        cache_ttl: int = CACHE_TTL_SECONDS,
    ) -> None:
        self._cache_path = Path(cache_path)
        self._cache_ttl = cache_ttl
        self._features: Optional[List[Dict]] = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_tile_urls(
        self,
        bbox: Tuple[float, float, float, float],
        products: List[str],
    ) -> Dict[str, List[str]]:
        """
        Return download URLs for tiles that intersect the given bbox.

        Args:
            bbox: Bounding box (west, south, east, north) in EPSG:4326.
            products: Subset of VALID_PRODUCTS to fetch.

        Returns:
            Dict mapping each product name to a list of GeoTIFF URLs,
            e.g. ``{"dtm": ["https://...MNT_33C15NO.tif"], "slope": [...]}``.
            Only products with at least one matching tile are included.

        Raises:
            ValueError: If an unrecognised product name is supplied.
            RuntimeError: If the tile index cannot be downloaded or parsed.
        """
        unknown = set(products) - set(VALID_PRODUCTS)
        if unknown:
            raise ValueError(
                f"Unknown LiDAR product(s): {sorted(unknown)}. "
                f"Valid products: {VALID_PRODUCTS}"
            )

        features = self._load_features()
        bbox_geom = box(*bbox)

        result: Dict[str, List[str]] = {p: [] for p in products}

        for feature in features:
            try:
                tile_geom = shape(feature["geometry"])
            except Exception as exc:
                logger.warning("Skipping tile with invalid geometry: %s", exc)
                continue

            if not tile_geom.intersects(bbox_geom):
                continue

            props = feature.get("properties", {})
            for product in products:
                col = PRODUCT_COLUMN[product]
                url = props.get(col)
                if url:
                    result[product].append(url)
                else:
                    logger.debug(
                        "Tile %s has no URL for product %s",
                        props.get("Feuillet20K", "?"),
                        product,
                    )

        return {p: urls for p, urls in result.items() if urls}

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _load_features(self) -> List[Dict]:
        """Return GeoJSON features, using disk cache when available."""
        if self._features is not None:
            return self._features

        if self._cache_is_fresh():
            logger.debug("Loading LiDAR tile index from cache: %s", self._cache_path)
            self._features = self._read_cache()
        else:
            logger.info("Downloading LiDAR tile index from MRNF…")
            self._features = self._download_and_cache()

        return self._features

    def _cache_is_fresh(self) -> bool:
        """Return True if the cache file exists and is younger than cache_ttl."""
        if not self._cache_path.exists():
            return False
        age = time.time() - self._cache_path.stat().st_mtime
        return age < self._cache_ttl

    def _read_cache(self) -> List[Dict]:
        """Read and parse the cached GeoJSON file."""
        try:
            with self._cache_path.open("r", encoding="utf-8") as fh:
                data = json.load(fh)
            return data["features"]
        except Exception as exc:
            logger.warning("Cache read failed (%s), re-downloading.", exc)
            return self._download_and_cache()

    def _download_and_cache(self) -> List[Dict]:
        """Download the tile index GeoJSON, persist to cache, and return features."""
        try:
            resp = requests.get(
                TILE_INDEX_URL,
                timeout=DOWNLOAD_TIMEOUT_SECONDS,
            )
            resp.raise_for_status()
        except requests.RequestException as exc:
            raise RuntimeError(
                f"Failed to download LiDAR tile index from MRNF: {exc}"
            ) from exc

        try:
            data = resp.json()
            features: List[Dict] = data["features"]
        except (ValueError, KeyError) as exc:
            raise RuntimeError(f"Unexpected tile index format: {exc}") from exc

        try:
            self._cache_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._cache_path.with_suffix(".tmp")
            tmp.write_text(resp.text, encoding="utf-8")
            tmp.replace(self._cache_path)
            logger.debug("LiDAR tile index cached to %s", self._cache_path)
        except OSError as exc:
            logger.warning("Could not cache tile index: %s", exc)

        return features
