"""
OGC API Processes metadata for the som-field-match process.
"""

from .spatial_backend.metadata import LOCATION_INPUTS

PROCESS_METADATA = {
    "version": "1.0.0",
    "id": "som-field-match",
    "title": {
        "en": "SOM Field Match",
        "fr": "Correspondance des champs MOS",
    },
    "description": {
        "en": (
            "Returns the SOM field boundaries within tolerance_m metres of a "
            "parcel, with the geodesic distance to each and whether GEE training "
            "data exists for it. Fields with GEE data come first, then by "
            "increasing distance. Use the returned gid values as field_ids for "
            "som-predict-soil."
        ),
        "fr": (
            "Retourne les champs MOS situés à moins de tolerance_m mètres d'une "
            "parcelle, avec la distance géodésique à chacun et la présence de "
            "données d'entraînement GEE. Les champs avec données GEE viennent en "
            "premier, puis par distance croissante. Les gid retournés servent de "
            "field_ids pour som-predict-soil."
        ),
    },
    "keywords": ["SOM", "soil", "field", "GEE", "parcel"],
    "links": [],
    "inputs": {
        **LOCATION_INPUTS,
        "tolerance_m": {
            "title": "Tolerance (m)",
            "description": (
                "Maximum distance between the location and a field "
                "(0 to 500, default 20)."
            ),
            "schema": {
                "type": "number",
                "minimum": 0,
                "maximum": 500,
                "default": 20,
            },
            "minOccurs": 0,
        },
    },
    "outputs": {
        "result": {
            "title": "Matching fields",
            "description": (
                '{"matches": [{"gid": <integer>, "has_gee_data": <boolean>, '
                '"dist_m": <number>}]}: GEE fields first, then by distance.'
            ),
            "schema": {"type": "object", "contentMediaType": "application/json"},
        }
    },
    "example": {
        "inputs": {
            "location_type": "point",
            "point": [-72.0, 45.4],
            "tolerance_m": 20,
        }
    },
}
