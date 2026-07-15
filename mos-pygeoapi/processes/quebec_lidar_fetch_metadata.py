"""
Metadata definition for Quebec LiDAR Derived Products Fetch Process
"""

PROCESS_METADATA = {
    "version": "0.1.0",
    "id": "lidar-fetch",
    "title": {
        "en": "Quebec LiDAR Derived Products Fetch",
        "fr": "Récupération des produits dérivés LiDAR du Québec",
    },
    "description": {
        "en": (
            "Fetches Quebec LiDAR-derived raster products (DTM, CHM, hillshade, slope) "
            "from the MRNF open data portal for a farm polygon, clips them to the farm "
            "bounding box, converts to Cloud Optimized GeoTIFF (COG), and stores in the "
            "STAC catalog."
        ),
        "fr": (
            "Récupère les produits dérivés du LiDAR québécois (MNT, MHC, ombre, pentes) "
            "depuis le portail de données ouvertes du MRNF pour un polygone de ferme, "
            "les découpe selon l'emprise de la ferme, les convertit en GeoTIFF optimisé "
            "pour le cloud (COG) et les stocke dans le catalogue STAC."
        ),
    },
    "keywords": [
        "lidar",
        "dtm",
        "mnt",
        "chm",
        "mhc",
        "slope",
        "hillshade",
        "elevation",
        "agriculture",
        "quebec",
        "mrnf",
    ],
    "jobControlOptions": ["sync-execute"],
    "inputs": {
        "farm_geometry": {
            "title": "Farm Geometry (GeoJSON)",
            "description": (
                "GeoJSON Polygon or MultiPolygon representing the farm boundary "
                "(optional if farm_id provided)"
            ),
            "schema": {"type": "object", "contentMediaType": "application/geo+json"},
            "minOccurs": 0,
            "maxOccurs": 1,
        },
        "farm_id": {
            "title": "Farm ID",
            "description": (
                "Database ID to lookup farm geometry from PostGIS table "
                "(optional if farm_geometry provided)"
            ),
            "schema": {"type": "integer"},
            "minOccurs": 0,
            "maxOccurs": 1,
        },
        "products": {
            "title": "LiDAR Products",
            "description": (
                "List of LiDAR-derived products to fetch. "
                "dtm=Digital Terrain Model (bare ground), "
                "chm=Canopy Height Model (vegetation height), "
                "hillshade=Shaded Relief, "
                "slope=Slope gradient in degrees"
            ),
            "schema": {
                "type": "array",
                "items": {
                    "type": "string",
                    "enum": ["dtm", "chm", "hillshade", "slope"],
                },
                "default": ["dtm", "chm", "hillshade", "slope"],
            },
            "minOccurs": 0,
            "maxOccurs": 1,
        },
    },
    "outputs": {
        "result": {
            "title": "Process Result",
            "description": "STAC item IDs, asset URLs, and bbox for generated LiDAR products",
            "schema": {
                "type": "object",
                "contentMediaType": "application/json",
                "properties": {
                    "stac_items": {"type": "array"},
                    "assets": {"type": "object"},
                    "bbox": {"type": "array"},
                    "products": {"type": "array"},
                },
            },
        }
    },
    "example": {
        "inputs": {
            "farm_id": 4,
            "products": ["dtm", "slope"],
        }
    },
}
