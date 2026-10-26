"""
OGC API Processes metadata for the pedo-coverage process.
"""

from .spatial_backend.metadata import LOCATION_INPUTS

PROCESS_METADATA = {
    "version": "1.0.0",
    "id": "pedo-coverage",
    "title": {
        "en": "Pedological Coverage",
        "fr": "Couverture pédologique",
    },
    "description": {
        "en": (
            "Returns the pedological classes (for example ARGILE Bon) covering a "
            "parcel and the share of its area each covers, from the IRDA 2026 soil "
            "map. When the 2026 classes describe less than min_described_pct of the "
            "parcel, the IRDA 2022 map is used instead, with its soil descriptions; "
            "the two releases are never mixed. A point is buffered by 5 m. "
            "Non-soil classes such as Étendue d'eau are kept."
        ),
        "fr": (
            "Retourne les classes pédologiques (par exemple ARGILE Bon) qui couvrent "
            "une parcelle et la part de sa superficie couverte par chacune, d'après "
            "la carte pédologique IRDA 2026. Si les classes 2026 décrivent moins de "
            "min_described_pct de la parcelle, la carte IRDA 2022 est utilisée à la "
            "place, avec ses descriptions de sol ; les deux éditions ne sont jamais "
            "mélangées. Un point reçoit une zone tampon de 5 m. Les classes non "
            "pédologiques comme Étendue d'eau sont conservées."
        ),
    },
    "keywords": ["soil", "pedology", "IRDA", "coverage", "parcel"],
    "links": [
        {
            "type": "text/html",
            "rel": "about",
            "title": "IRDA — Cartes pédologiques du Québec",
            "href": (
                "https://irda.qc.ca/fr/outils/donnees-pedologiques-sols/"
                "cartes-pedologiques-quebec-irda/"
            ),
        }
    ],
    "inputs": {
        **LOCATION_INPUTS,
        "min_described_pct": {
            "title": "Minimum described share (%)",
            "description": (
                "Share of the parcel the 2026 classes must describe before the "
                "2022 map is tried instead (0 to 100, default 50)."
            ),
            "schema": {
                "type": "number",
                "minimum": 0,
                "maximum": 100,
                "default": 50,
            },
            "minOccurs": 0,
        },
    },
    "outputs": {
        "result": {
            "title": "Pedological coverage",
            "description": (
                '{"source": "irda_2026" | "irda_2022" | null, "symbole", '
                '"description", "count", "described_pct", "classes": [{"symbole", '
                '"description", "share_pct"}]}: classes by decreasing share; '
                "symbole and description are those of the first class. 2026 "
                "classes have a null description."
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
