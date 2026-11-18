"""
OGC API Processes metadata for the water-distance process.
"""

from .spatial_backend.metadata import LOCATION_INPUTS

PROCESS_METADATA = {
    "version": "1.0.0",
    "id": "water-distance",
    "title": {
        "en": "Distance to Nearest Water Feature",
        "fr": "Distance au plan d'eau le plus proche",
    },
    "description": {
        "en": (
            "Returns the geodesic distance in metres from a parcel to the nearest "
            "hydrographic feature (stream, river or water body) of the Quebec "
            "GRHQ network. The distance is measured from a point inside the "
            "parcel, so a stream crossing the parcel does not give 0. Returns "
            "null when no feature lies within max_distance_m."
        ),
        "fr": (
            "Retourne la distance géodésique en mètres entre une parcelle et "
            "l'entité hydrographique la plus proche (cours d'eau, rivière ou plan "
            "d'eau) du réseau GRHQ du Québec. La distance est mesurée depuis un "
            "point à l'intérieur de la parcelle : un cours d'eau qui la traverse "
            "ne donne donc pas 0. Retourne null si aucune entité ne se trouve à "
            "moins de max_distance_m."
        ),
    },
    "keywords": ["water", "hydrography", "GRHQ", "distance", "parcel"],
    "links": [
        {
            "type": "text/html",
            "rel": "about",
            "title": "Géobase du réseau hydrographique du Québec (GRHQ)",
            "href": "https://www.donneesquebec.ca/recherche/dataset/grhq",
        }
    ],
    "inputs": {
        **LOCATION_INPUTS,
        "max_distance_m": {
            "title": "Maximum distance (m)",
            "description": (
                "Distance beyond which the result is null "
                "(greater than 0, at most 100000, default 100000)."
            ),
            "schema": {
                "type": "number",
                "exclusiveMinimum": 0,
                "maximum": 100000,
                "default": 100000,
            },
            "minOccurs": 0,
        },
    },
    "outputs": {
        "result": {
            "title": "Water distance",
            "description": (
                '{"distance_m": <number | null>}: metres to the nearest GRHQ '
                "feature, or null beyond max_distance_m."
            ),
            "schema": {"type": "object", "contentMediaType": "application/json"},
        }
    },
    "example": {
        "inputs": {
            "location_type": "point",
            "point": [-72.0, 45.4],
        }
    },
}
