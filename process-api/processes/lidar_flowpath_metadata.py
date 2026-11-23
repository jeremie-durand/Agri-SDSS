"""OGC API Processes metadata for the lidar-flowpath process."""

from __future__ import annotations

from typing import Any

PROCESS_METADATA: dict[str, Any] = {
    "version": "1.0.0",
    "id": "lidar-flowpath",
    "title": {
        "en": "LiDAR Flow Paths and LS Factor",
        "fr": "Écoulement de l'eau et facteur LS (LiDAR)",
    },
    "description": {
        "en": (
            "Maps where water flows and concentrates in a field, from the MRNF "
            "LiDAR terrain model resampled to 2 m in EPSG:32198 (NAD83 / Québec "
            "Lambert) over the field plus an upstream margin. Returns four "
            "Cloud Optimized GeoTIFFs clipped to the field and published to "
            "STAC: filled_dtm (m, depressions filled), sca (specific catchment "
            "area in m, multiple-flow-direction routing), slope (percent) and "
            "ls (dimensionless RUSLE LS factor, Moore & Burch, slope length "
            "capped at 300 m). The result also gives the field's mean slope and "
            "LS mean, median, 90th percentile and maximum, optional per-zone "
            "statistics, the parameters used and the MRNF sheets read. It does "
            "not compute runoff volumes or soil loss. Fields up to 5 km² "
            "(bounding box). Prefer asynchronous execution "
            "(Prefer: respond-async)."
        ),
        "fr": (
            "Cartographie les chemins d'écoulement de l'eau dans un champ à "
            "partir du MNT LiDAR du MRNF rééchantillonné à 2 m en EPSG:32198 "
            "(NAD83 / Québec Lambert) sur le champ et une marge en amont. "
            "Retourne quatre GeoTIFF optimisés (COG) découpés sur le champ et "
            "publiés dans STAC : filled_dtm (m, cuvettes comblées), sca (aire "
            "contributive spécifique en m, écoulement multidirectionnel), slope "
            "(pourcentage) et ls (facteur LS de RUSLE sans unité, Moore & "
            "Burch, longueur de pente plafonnée à 300 m). Le résultat donne "
            "aussi la pente moyenne du champ et la moyenne, la médiane, le 90e "
            "percentile et le maximum du LS, des statistiques par zone en "
            "option, les paramètres utilisés et les feuillets MRNF lus. Ne "
            "calcule ni volume de ruissellement ni perte de sol. Champs jusqu'à "
            "5 km² (emprise). Privilégier l'exécution asynchrone "
            "(Prefer: respond-async)."
        ),
    },
    "keywords": [
        "lidar",
        "flow accumulation",
        "flow path",
        "ruissellement",
        "LS factor",
        "RUSLE",
        "slope",
        "agriculture",
        "quebec",
        "mrnf",
    ],
    "jobControlOptions": ["sync-execute", "async-execute"],
    "links": [
        {
            "type": "text/html",
            "rel": "about",
            "title": "Produits dérivés de base du LiDAR — Données Québec",
            "href": (
                "https://www.donneesquebec.ca/recherche/dataset/"
                "produits-derives-de-base-du-lidar"
            ),
        }
    ],
    "inputs": {
        "location_type": {
            "title": "Location type",
            "description": "Type of field location: farm_id, polygon or bbox.",
            "schema": {"type": "string", "enum": ["farm_id", "polygon", "bbox"]},
        },
        "farm_id": {
            "title": "Farm ID",
            "description": (
                "Database farm identifier (required when location_type is farm_id)."
            ),
            "schema": {"type": "string"},
            "minOccurs": 0,
        },
        "polygon": {
            "title": "Field polygon",
            "description": (
                "GeoJSON Polygon or MultiPolygon in EPSG:4326 (required when "
                "location_type is polygon). Invalid geometries are repaired."
            ),
            "schema": {"type": "object"},
            "minOccurs": 0,
        },
        "bbox": {
            "title": "Bounding box",
            "description": (
                "[minx, miny, maxx, maxy] in EPSG:4326 (required when "
                "location_type is bbox)."
            ),
            "schema": {
                "type": "array",
                "items": {"type": "number"},
                "minItems": 4,
                "maxItems": 4,
            },
            "minOccurs": 0,
        },
        "upstream_margin_m": {
            "title": "Upstream margin (m)",
            "description": (
                "Distance added around the field's bounding box so flow coming "
                "from upslope is counted (0 to 1000, default 300)."
            ),
            "schema": {
                "type": "integer",
                "minimum": 0,
                "maximum": 1000,
                "default": 300,
            },
            "minOccurs": 0,
        },
        "zones": {
            "title": "Management zones",
            "description": (
                "Optional GeoJSON FeatureCollection of 1 to 50 Polygon or "
                "MultiPolygon features in EPSG:4326, each with an optional 'id' "
                "property. Adds summary.zones with the statistics of each zone "
                "inside the field. Zones do not change the computed layers."
            ),
            "schema": {"type": "object"},
            "minOccurs": 0,
        },
    },
    "outputs": {
        "result": {
            "title": "Flow-path layers",
            "description": (
                '{"stac_items", "assets": {"filled_dtm", "sca", "slope", "ls"}, '
                '"bbox", "summary": {"slope": {"mean_percent"}, "ls": {"mean", '
                '"median", "p90", "max"}, "zones": [{"id", "area_ha", "slope", '
                '"ls"}]}, "parameters": {"upstream_margin_m", "resolution_m", '
                '"crs", "resampling", "sca_cap_m", "mfd_exponent", '
                '"fill_epsilon_m", "algorithm_version"}, "source": {"dataset", '
                '"url", "sheets"}}. assets.<layer>.href is the public COG URL '
                "(byte-range readable, no authentication). Pixels outside the "
                "field are -9999."
            ),
            "schema": {"type": "object", "contentMediaType": "application/json"},
        }
    },
    "example": {
        "inputs": {
            "location_type": "polygon",
            "polygon": {
                "type": "Polygon",
                "coordinates": [
                    [
                        [-72.96, 45.62],
                        [-72.95, 45.62],
                        [-72.95, 45.63],
                        [-72.96, 45.63],
                        [-72.96, 45.62],
                    ]
                ],
            },
            "upstream_margin_m": 300,
        }
    },
}
