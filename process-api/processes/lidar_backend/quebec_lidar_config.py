"""
Configuration constants for the Quebec MRNF LiDAR tile index.

Deliberately constants rather than environment variables. PRODUCT_COLUMN,
DERIVED_PRODUCTS and VALID_PRODUCTS are a schema contract with the MRNF
GeoJSON and are coupled to code paths, so a wrong value fails silently: an
unmatched column name yields no tiles rather than an error. TILE_INDEX_URL
and DOWNLOAD_TIMEOUT_SECONDS have a single upstream and no per-deployment
variance. CACHE_TTL_SECONDS and DEFAULT_CACHE_PATH are already injectable
through LidarTileIndex(cache_path=..., cache_ttl=...), which is the seam
callers and tests use.
"""

TILE_INDEX_URL: str = (
    "https://diffusion.mffp.gouv.qc.ca/Diffusion/DonneeGratuite/Foret/IMAGERIE/"
    "Produits_derives_LiDAR/Produit_derive_lidar/03-Telechargement/URL_Lidar.geojson"
)

PRODUCT_COLUMN: dict[str, str] = {
    "dtm": "MNT",
    "chm": "MHC",
    "hillshade": "MNT_Ombre",
    "slope": "Pentes",
}

# Not an MRNF product — derived locally from DTM via gdaldem aspect.
# Never pass this to LidarTileIndex.get_tile_urls (no PRODUCT_COLUMN entry).
DERIVED_PRODUCTS: list[str] = ["aspect"]

VALID_PRODUCTS: list[str] = list(PRODUCT_COLUMN.keys()) + DERIVED_PRODUCTS

CACHE_TTL_SECONDS: int = 86_400
DEFAULT_CACHE_PATH: str = "/tmp/quebec_lidar_tile_index.geojson"

DOWNLOAD_TIMEOUT_SECONDS: int = 60
