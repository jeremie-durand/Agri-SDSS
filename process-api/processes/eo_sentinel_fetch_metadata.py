"""
Metadata definition for Sentinel-2 Earth Observation Data Fetch Process
"""

PROCESS_METADATA = {
    "version": "0.1.0",
    "id": "sentinel-fetch",
    "title": {
        "en": "Sentinel-2 Earth Observation Data Fetch",
        "fr": "Récupération de données d'observation de la Terre Sentinel-2",
    },
    "description": {
        "en": "Fetches Sentinel-2 data from openEO backends for a farm polygon, calculates vegetation indices (NDVI, EVI, SAVI), and stores as Cloud Optimized GeoTIFF in STAC catalog",
        "fr": "Récupère les données Sentinel-2 depuis les backends openEO pour un polygone de ferme, calcule les indices de végétation (NDVI, EVI, SAVI), et stocke au format Cloud Optimized GeoTIFF dans le catalogue STAC",
    },
    "keywords": [
        "sentinel-2",
        "openeo",
        "ndvi",
        "evi",
        "agriculture",
        "earth observation",
    ],
    "jobControlOptions": ["sync-execute"],
    "inputs": {
        "farm_geometry": {
            "title": "Farm Geometry (GeoJSON)",
            "description": "GeoJSON Polygon or MultiPolygon representing the farm boundary (optional if farm_id provided)",
            "schema": {"type": "object", "contentMediaType": "application/geo+json"},
            "minOccurs": 0,
            "maxOccurs": 1,
        },
        "farm_id": {
            "title": "Farm ID",
            "description": "Database ID to lookup farm geometry from PostGIS table (optional if farm_geometry provided)",
            "schema": {"type": "integer"},
            "minOccurs": 0,
            "maxOccurs": 1,
        },
        "temporal_extent": {
            "title": "Temporal Extent",
            "description": "Array of two ISO 8601 dates [start_date, end_date] for data acquisition period",
            "schema": {
                "type": "array",
                "items": {"type": "string", "format": "date"},
                "minItems": 2,
                "maxItems": 2,
            },
            "minOccurs": 1,
            "maxOccurs": 1,
        },
        "output_products": {
            "title": "Output Products",
            "description": "List of products to generate (raw_bands, ndvi, evi, savi, true_color)",
            "schema": {
                "type": "array",
                "items": {
                    "type": "string",
                    "enum": ["raw_bands", "ndvi", "evi", "savi", "true_color"],
                },
            },
            "minOccurs": 1,
            "maxOccurs": 1,
        },
        "aggregation_method": {
            "title": "Temporal Aggregation Method",
            "description": "Method to aggregate multiple Sentinel-2 scenes over time period",
            "schema": {
                "type": "string",
                "enum": ["median", "max", "min", "mean"],
                "default": "median",
            },
            "minOccurs": 0,
            "maxOccurs": 1,
        },
        "cloud_cover_max": {
            "title": "Maximum Cloud Cover",
            "description": "Maximum allowed cloud cover percentage (0-100)",
            "schema": {"type": "number", "minimum": 0, "maximum": 100, "default": 20},
            "minOccurs": 0,
            "maxOccurs": 1,
        },
    },
    "outputs": {
        "result": {
            "title": "Process Result",
            "description": "STAC item ID, asset URLs, and preview links for generated products",
            "schema": {
                "type": "object",
                "contentMediaType": "application/json",
                "properties": {
                    "stac_item_id": {"type": "string"},
                    "assets": {"type": "object"},
                    "preview_url": {"type": "string"},
                    "bbox": {"type": "array"},
                    "temporal_extent": {"type": "array"},
                },
            },
        }
    },
    "example": {
        "inputs": {
            "farm_id": 4,
            "temporal_extent": ["2024-06-01", "2024-08-31"],
            "output_products": ["ndvi", "true_color"],
            "aggregation_method": "median",
            "cloud_cover_max": 20,
        }
    },
}
