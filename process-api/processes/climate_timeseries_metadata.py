"""
OGC API – Processes metadata definition for the climate-timeseries process.
"""

PROCESS_METADATA = {
    "version": "0.1.0",
    "id": "climate-timeseries",
    "title": {
        "en": "Climate Timeseries (CMIP6 Projections)",
        "fr": "Série temporelle climatique (projections CMIP6)",
    },
    "description": {
        "en": (
            "Retrieves daily CMIP6 climate projection timeseries from the Ouranos "
            "PAVICS THREDDS server (OPeNDAP) for a given spatial area and time range. "
            "Data source: ESPO-G6-R2 v1.0.0 bias-adjusted projections (26 models, "
            "SSP2-4.5 / SSP3-7.0 / SSP5-8.5, 1950–2100). "
            "Returns a valid GeoJSON Feature with temporal data in its properties."
        ),
        "fr": (
            "Récupère des séries temporelles de projections climatiques CMIP6 "
            "depuis le serveur THREDDS PAVICS d'Ouranos pour une zone spatiale "
            "et une plage temporelle données. Source: ESPO-G6-R2 v1.0.0."
        ),
    },
    "keywords": [
        "climate",
        "cmip6",
        "projections",
        "espo-g6-r2",
        "pavics",
        "ouranos",
        "timeseries",
        "temperature",
        "precipitation",
        "ssp245",
        "ssp370",
        "ssp585",
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
                "tasmax (daily max temperature), pr (precipitation). "
                "Note: tas (mean temperature) is not available in CMIP6 ESPO-G6-R2."
            ),
            "schema": {
                "type": "array",
                "items": {
                    "type": "string",
                    "enum": ["tasmin", "tasmax", "pr"],
                },
                "minItems": 1,
            },
            "minOccurs": 1,
            "maxOccurs": 1,
        },
        "start_date": {
            "title": "Start Date",
            "description": (
                "Start of the temporal query window (ISO 8601, YYYY-MM-DD). "
                "Range: 1950–2100."
            ),
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
                "CMIP6 dataset identifier (e.g. 'cmip6_espo_g6_r2'). "
                "Defaults to 'cmip6_espo_g6_r2'."
            ),
            "schema": {
                "type": "string",
                "enum": ["cmip6_espo_g6_r2"],
                "default": "cmip6_espo_g6_r2",
            },
            "minOccurs": 0,
            "maxOccurs": 1,
        },
        "scenario": {
            "title": "Emissions Scenario",
            "description": (
                "CMIP6 Shared Socioeconomic Pathway: "
                "ssp245 (intermediate), ssp370 (high), ssp585 (very high). "
                "Note: EC-Earth3-CC and NESM3 do not provide ssp370."
            ),
            "schema": {
                "type": "string",
                "enum": ["ssp245", "ssp370", "ssp585"],
            },
            "minOccurs": 1,
            "maxOccurs": 1,
        },
        "model": {
            "title": "Climate Model",
            "description": (
                "CMIP6 model name (e.g. 'MPI-ESM1-2-LR'). "
                "Available models: TaiESM1, BCC-CSM2-MR, FGOALS-g3, CanESM5, "
                "CMCC-ESM2, CNRM-CM6-1, CNRM-ESM2-1, ACCESS-CM2, ACCESS-ESM1-5, "
                "EC-Earth3-CC, EC-Earth3-Veg, EC-Earth3, INM-CM4-8, INM-CM5-0, "
                "IPSL-CM6A-LR, MIROC-ES2L, MIROC6, UKESM1-0-LL, MPI-ESM1-2-HR, "
                "MPI-ESM1-2-LR, MRI-ESM2-0, NorESM2-LM, NorESM2-MM, KACE-1-0-G, "
                "GFDL-ESM4, NESM3."
            ),
            "schema": {
                "type": "string",
                "enum": [
                    "TaiESM1",
                    "BCC-CSM2-MR",
                    "FGOALS-g3",
                    "CanESM5",
                    "CMCC-ESM2",
                    "CNRM-CM6-1",
                    "CNRM-ESM2-1",
                    "ACCESS-CM2",
                    "ACCESS-ESM1-5",
                    "EC-Earth3-CC",
                    "EC-Earth3-Veg",
                    "EC-Earth3",
                    "INM-CM4-8",
                    "INM-CM5-0",
                    "IPSL-CM6A-LR",
                    "MIROC-ES2L",
                    "MIROC6",
                    "UKESM1-0-LL",
                    "MPI-ESM1-2-HR",
                    "MPI-ESM1-2-LR",
                    "MRI-ESM2-0",
                    "NorESM2-LM",
                    "NorESM2-MM",
                    "KACE-1-0-G",
                    "GFDL-ESM4",
                    "NESM3",
                ],
            },
            "minOccurs": 1,
            "maxOccurs": 1,
        },
    },
    "outputs": {
        "result": {
            "title": "Climate Timeseries GeoJSON Feature",
            "description": (
                "A GeoJSON Feature whose geometry represents the queried area "
                "and whose properties contain the CMIP6 timeseries data and metadata, "
                "including scenario and model information."
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
                            "scenario": {"type": "string"},
                            "model": {"type": "string"},
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
            "start_date": "2050-01-01",
            "end_date": "2050-01-07",
            "aggregation": "daily",
            "dataset": "cmip6_espo_g6_r2",
            "scenario": "ssp245",
            "model": "MPI-ESM1-2-LR",
        }
    },
}
