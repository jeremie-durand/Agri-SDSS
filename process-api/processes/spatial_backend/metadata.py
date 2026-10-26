"""OGC process input descriptions shared by the spatial utility processes."""

from __future__ import annotations

from typing import Any

LOCATION_INPUTS: dict[str, dict[str, Any]] = {
    "location_type": {
        "title": "Location type",
        "description": "Type of location: farm_id, point or polygon (bbox is rejected).",
        "schema": {"type": "string", "enum": ["farm_id", "point", "polygon"]},
    },
    "farm_id": {
        "title": "Farm ID",
        "description": "Database farm identifier (required when location_type is farm_id).",
        "schema": {"type": "string"},
        "minOccurs": 0,
    },
    "point": {
        "title": "Point",
        "description": "[lon, lat] in EPSG:4326 (required when location_type is point).",
        "schema": {
            "type": "array",
            "items": {"type": "number"},
            "minItems": 2,
            "maxItems": 2,
        },
        "minOccurs": 0,
    },
    "polygon": {
        "title": "Polygon",
        "description": (
            "GeoJSON Polygon or MultiPolygon in EPSG:4326 (required when "
            "location_type is polygon). Invalid geometries are repaired."
        ),
        "schema": {"type": "object"},
        "minOccurs": 0,
    },
}
