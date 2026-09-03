"""
Metadata definition for Quebec LiDAR Derived Products Fetch Process
"""

PROCESS_METADATA = {
    "version": "0.2.0",
    "id": "lidar-fetch",
    "title": {
        "en": "Quebec LiDAR Derived Products Fetch",
        "fr": "Récupération des produits dérivés LiDAR du Québec",
    },
    "description": {
        "en": (
            "Fetches Quebec LiDAR-derived raster products (DTM, CHM, hillshade, "
            "slope) from the MRNF open data portal for a farm polygon, clips them "
            "to the farm bounding box, converts to Cloud Optimized GeoTIFF (COG), "
            "stores in the STAC catalog, and computes band statistics (mean) for "
            "each product. Aspect can also be requested; it is derived locally "
            "from the DTM (not a native MRNF product). Slope and aspect "
            "statistics are computed over the exact farm polygon; the other "
            "products use the bounding-box mean."
        ),
        "fr": (
            "Récupère les produits dérivés du LiDAR québécois (MNT, MHC, ombre, "
            "pentes) depuis le portail de données ouvertes du MRNF pour un "
            "polygone de ferme, les découpe selon l'emprise de la ferme, les "
            "convertit en GeoTIFF optimisé pour le cloud (COG), les stocke dans "
            "le catalogue STAC, et calcule des statistiques de bande (moyenne) "
            "pour chaque produit. L'orientation (aspect) peut aussi être "
            "demandée; elle est dérivée localement du MNT (ce n'est pas un "
            "produit MRNF natif). Les statistiques de pente et d'orientation "
            "sont calculées sur le polygone exact de la ferme; les autres "
            "produits utilisent la moyenne de l'emprise rectangulaire."
        ),
    },
    "keywords": [
        "lidar",
        "dtm",
        "mnt",
        "chm",
        "mhc",
        "slope",
        "aspect",
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
                "slope=Slope gradient in degrees and percent, "
                "aspect=Downslope compass bearing in degrees, derived locally "
                "from the DTM (not a native MRNF product; requesting it also "
                "fetches DTM internally even if 'dtm' is not itself requested)"
            ),
            "schema": {
                "type": "array",
                "items": {
                    "type": "string",
                    "enum": ["dtm", "chm", "hillshade", "slope", "aspect"],
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
            "description": (
                "STAC item IDs, asset URLs, and bbox for generated LiDAR "
                "products. Each entry in assets.<product>.statistics carries "
                "the band mean the process computes for that product: "
                '{"mean": ...} for dtm/chm/hillshade (bounding-box mean), '
                '{"mean_degrees": ..., "mean_percent": ...} for slope, and '
                '{"mean_degrees": ...} for aspect (circular mean) — slope and '
                "aspect statistics are computed over the exact farm polygon. "
                "When slope or aspect is requested, their statistics are also "
                "duplicated at the top level (result.slope / result.aspect) "
                "for direct access without parsing the assets structure."
            ),
            "schema": {
                "type": "object",
                "contentMediaType": "application/json",
                "properties": {
                    "stac_items": {"type": "array"},
                    "assets": {"type": "object"},
                    "bbox": {"type": "array"},
                    "products": {"type": "array"},
                    "slope": {
                        "type": "object",
                        "description": (
                            "Present when 'slope' is requested: "
                            "{mean_degrees, mean_percent} over the exact farm "
                            "polygon."
                        ),
                    },
                    "aspect": {
                        "type": "object",
                        "description": (
                            "Present when 'aspect' is requested: "
                            "{mean_degrees} circular mean over the exact farm "
                            "polygon."
                        ),
                    },
                },
            },
        }
    },
    "example": {
        "inputs": {
            "farm_id": 4,
            "products": ["dtm", "slope", "aspect"],
        }
    },
}
