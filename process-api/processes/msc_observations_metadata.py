"""
OGC API Processes metadata for the msc-observations process.
"""

PROCESS_METADATA = {
    "version": "1.0.0",
    "id": "msc-observations",
    "title": "MSC GeoMet Weather Station Observations",
    "description": (
        "Retrieves daily or near real-time surface weather observations from the "
        "Meteorological Service of Canada (MSC) GeoMet OGC API "
        "(https://api.weather.gc.ca). Data is open and requires no authentication. "
        "Returns a GeoJSON FeatureCollection with one Feature per station found "
        "within the requested area."
    ),
    "keywords": ["weather", "observations", "MSC", "GeoMet", "Canada", "stations"],
    "links": [
        {
            "type": "text/html",
            "rel": "about",
            "title": "MSC Open Data documentation",
            "href": "https://eccc-msc.github.io/open-data/",
        }
    ],
    "inputs": {
        "location_type": {
            "title": "Location type",
            "description": "Type of spatial filter: farm_id, point, bbox, or polygon.",
            "schema": {
                "type": "string",
                "enum": ["farm_id", "point", "bbox", "polygon"],
            },
        },
        "farm_id": {
            "title": "Farm ID",
            "description": (
                "Database farm identifier " "(required when location_type is farm_id)."
            ),
            "schema": {"type": "string"},
            "minOccurs": 0,
        },
        "point": {
            "title": "Point",
            "description": (
                "[lon, lat] in EPSG:4326 " "(required when location_type is point)."
            ),
            "schema": {
                "type": "array",
                "items": {"type": "number"},
                "minItems": 2,
                "maxItems": 2,
            },
            "minOccurs": 0,
        },
        "bbox": {
            "title": "Bounding box",
            "description": (
                "[minx, miny, maxx, maxy] in EPSG:4326 "
                "(required when location_type is bbox)."
            ),
            "schema": {
                "type": "array",
                "items": {"type": "number"},
                "minItems": 4,
                "maxItems": 4,
            },
            "minOccurs": 0,
        },
        "polygon": {
            "title": "Polygon",
            "description": (
                "GeoJSON Polygon geometry " "(required when location_type is polygon)."
            ),
            "schema": {"type": "object"},
            "minOccurs": 0,
        },
        "collection": {
            "title": "MSC collection",
            "description": (
                "MSC GeoMet collection to query. "
                "'climate-daily': daily observations 1840–present (1–2 day lag). "
                "'swob-realtime': sub-hourly observations for the last 30 days."
            ),
            "schema": {
                "type": "string",
                "enum": ["climate-daily", "swob-realtime"],
                "default": "climate-daily",
            },
            "minOccurs": 0,
        },
        "variables": {
            "title": "Variables",
            "description": (
                "Canonical variable names to retrieve. "
                "climate-daily: tasmin, tasmax, tas, pr, prsn, snd. "
                "swob-realtime: tas, tasmin, tasmax, pr, hurs, wss."
            ),
            "schema": {
                "type": "array",
                "items": {"type": "string"},
                "minItems": 1,
            },
        },
        "start_date": {
            "title": "Start date",
            "description": "Start of the time range (YYYY-MM-DD, inclusive).",
            "schema": {"type": "string", "format": "date"},
        },
        "end_date": {
            "title": "End date",
            "description": "End of the time range (YYYY-MM-DD, inclusive).",
            "schema": {"type": "string", "format": "date"},
        },
        "limit": {
            "title": "Station limit",
            "description": (
                "Maximum number of stations to return " "(1–5000, default 500)."
            ),
            "schema": {
                "type": "integer",
                "minimum": 1,
                "maximum": 5000,
                "default": 500,
            },
            "minOccurs": 0,
        },
    },
    "outputs": {
        "result": {
            "title": "Station observations FeatureCollection",
            "description": (
                "GeoJSON FeatureCollection. Each Feature represents "
                "one weather station with a timeseries of the requested "
                "variables in its properties."
            ),
            "schema": {"type": "object", "contentMediaType": "application/geo+json"},
        }
    },
    "example": {
        "inputs": {
            "location_type": "bbox",
            "bbox": [-74.0, 45.0, -73.0, 46.0],
            "collection": "climate-daily",
            "variables": ["tasmin", "tasmax", "pr"],
            "start_date": "2024-01-01",
            "end_date": "2024-01-07",
        }
    },
}
