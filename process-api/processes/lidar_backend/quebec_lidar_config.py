"""
Configuration constants for the Quebec MRNF LiDAR tile index.
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

VALID_PRODUCTS: list[str] = list(PRODUCT_COLUMN.keys())

CACHE_TTL_SECONDS: int = 86_400
DEFAULT_CACHE_PATH: str = "/tmp/quebec_lidar_tile_index.geojson"

DOWNLOAD_TIMEOUT_SECONDS: int = 60
