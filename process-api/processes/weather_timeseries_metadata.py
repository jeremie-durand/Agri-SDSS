"""
OGC API – Processes metadata definition for the weather-timeseries process.
"""

PROCESS_METADATA = {
    "version": "0.1.0",
    "id": "weather-timeseries",
    "title": {
        "en": "Weather Timeseries",
        "fr": "Série temporelle météorologique",
    },
    "description": {
        "en": (
            "Retrieves gridded climate and reanalysis timeseries from the Ouranos "
            "PAVICS THREDDS server (OPeNDAP) for a given spatial area and time range. "
            "Supports farm, point, bounding-box, and polygon location types. "
            "Returns a valid GeoJSON Feature with temporal data in its properties."
        ),
        "fr": (
            "Récupère des séries temporelles climatiques et de réanalyse grillées "
            "depuis le serveur THREDDS PAVICS d'Ouranos (OPeNDAP) pour une zone "
            "spatiale et une plage temporelle données."
        ),
    },
    "keywords": [
        "weather",
        "climate",
        "reanalysis",
        "era5",
        "pavics",
        "ouranos",
        "timeseries",
        "temperature",
        "precipitation",
    ],
    "jobControlOptions": ["sync-execute"],
    "outputTransmission": ["value"],
    "inputs": {
        "location_type": {
            "title": "Location Type",
            "description": (
                "How the spatial query area is specified. "
                "Exactly one of farm_id, point, bbox, or polygon must be provided."
            ),
            "schema": {
                "type": "string",
                "enum": ["farm_id", "point", "bbox", "polygon"],
            },
            "minOccurs": 1,
            "maxOccurs": 1,
        },
        "farm_id": {
            "title": "Farm ID",
            "description": (
                "Database primary key used to look up the farm geometry from PostGIS. "
                "Required when location_type is 'farm_id'."
            ),
            "schema": {"type": "string"},
            "minOccurs": 0,
            "maxOccurs": 1,
        },
        "point": {
            "title": "Point",
            "description": (
                "Longitude/latitude pair [lon, lat] in EPSG:4326. "
                "Required when location_type is 'point'."
            ),
            "schema": {
                "type": "array",
                "items": {"type": "number"},
                "minItems": 2,
                "maxItems": 2,
            },
            "minOccurs": 0,
            "maxOccurs": 1,
        },
        "bbox": {
            "title": "Bounding Box",
            "description": (
                "[minx, miny, maxx, maxy] in EPSG:4326. "
                "Required when location_type is 'bbox'."
            ),
            "schema": {
                "type": "array",
                "items": {"type": "number"},
                "minItems": 4,
                "maxItems": 4,
            },
            "minOccurs": 0,
            "maxOccurs": 1,
        },
        "polygon": {
            "title": "Polygon",
            "description": (
                "GeoJSON Polygon geometry object in EPSG:4326. "
                "Required when location_type is 'polygon'."
            ),
            "schema": {
                "type": "object",
                "contentMediaType": "application/geo+json",
            },
            "minOccurs": 0,
            "maxOccurs": 1,
        },
        "variables": {
            "title": "Variables",
            "description": (
                "List of climate variables to retrieve. "
                "Supported: tasmin (daily min temperature), "
                "tasmax (daily max temperature), tas (daily mean temperature), "
                "pr (precipitation)."
            ),
            "schema": {
                "type": "array",
                "items": {
                    "type": "string",
                    "enum": ["tasmin", "tasmax", "tas", "pr"],
                },
                "minItems": 1,
            },
            "minOccurs": 1,
            "maxOccurs": 1,
        },
        "start_date": {
            "title": "Start Date",
            "description": "Start of the temporal query window (ISO 8601, YYYY-MM-DD).",
            "schema": {"type": "string", "format": "date"},
            "minOccurs": 1,
            "maxOccurs": 1,
        },
        "end_date": {
            "title": "End Date",
            "description": "End of the temporal query window (ISO 8601, YYYY-MM-DD).",
            "schema": {"type": "string", "format": "date"},
            "minOccurs": 1,
            "maxOccurs": 1,
        },
        "aggregation": {
            "title": "Temporal Aggregation",
            "description": (
                "Temporal resolution of the output timeseries. "
                "'daily' returns one value per day; 'monthly' returns monthly means."
            ),
            "schema": {
                "type": "string",
                "enum": ["daily", "monthly"],
                "default": "daily",
            },
            "minOccurs": 0,
            "maxOccurs": 1,
        },
        "dataset": {
            "title": "Dataset",
            "description": (
                "PAVICS dataset identifier, as defined in weather_datasets.yaml "
                "(e.g. 'era5_land'). Defaults to 'era5_land'."
            ),
            "schema": {"type": "string", "default": "era5_land"},
            "minOccurs": 0,
            "maxOccurs": 1,
        },
    },
    "outputs": {
        "result": {
            "title": "Weather Timeseries GeoJSON Feature",
            "description": (
                "A GeoJSON Feature whose geometry represents the queried area "
                "and whose properties contain the timeseries data and metadata."
            ),
            "schema": {
                "type": "object",
                "contentMediaType": "application/geo+json",
                "properties": {
                    "type": {"type": "string", "enum": ["Feature"]},
                    "geometry": {"type": "object"},
                    "properties": {
                        "type": "object",
                        "properties": {
                            "provider": {"type": "string"},
                            "dataset": {"type": "string"},
                            "variables": {"type": "array", "items": {"type": "string"}},
                            "aggregation": {"type": "string"},
                            "temporal_extent": {
                                "type": "array",
                                "items": {"type": "string"},
                            },
                            "data": {"type": "object"},
                            "units": {"type": "object"},
                        },
                    },
                },
            },
        }
    },
    "example": {
        "inputs": {
            "location_type": "bbox",
            "bbox": [-72.0, 45.0, -71.0, 46.0],
            "variables": ["tasmin", "tasmax"],
            "start_date": "2020-01-01",
            "end_date": "2020-01-31",
            "aggregation": "monthly",
            "dataset": "era5_land",
        }
    },
}
