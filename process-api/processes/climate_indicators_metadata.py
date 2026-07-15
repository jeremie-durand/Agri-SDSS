"""
OGC API – Processes metadata definition for the climate-indicators process.
"""

PROCESS_METADATA = {
    "version": "0.1.0",
    "id": "climate-indicators",
    "title": {
        "en": "Climate Indicators",
        "fr": "Indicateurs climatiques",
    },
    "description": {
        "en": (
            "Computes agronomic climate indicators from gridded weather data. "
            "Supports historical reanalysis (ERA5-Land, RDRS) and CMIP6 climate "
            "projections (ESPO-G6-R2). Implemented indicators: "
            "Growing Degree Days (GDD), "
            "Frost Days, Heat Stress Days, Precipitation Total, Precipitation Days. "
            "Returns a valid GeoJSON Feature with indicator results in its properties."
        ),
        "fr": (
            "Calcule des indicateurs climatiques agronomiques "
            "à partir de données grillées. "
            "Supporte la réanalyse historique et les projections CMIP6. "
            "Indicateurs disponibles: DJC, jours de gel, jours de stress thermique, "
            "précipitations totales, jours de précipitations."
        ),
    },
    "keywords": [
        "climate",
        "indicators",
        "growing-degree-days",
        "gdd",
        "frost-days",
        "heat-stress",
        "precipitation",
        "agronomy",
        "temperature",
        "pavics",
        "ouranos",
        "cmip6",
        "era5",
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
        "indicator": {
            "title": "Indicator",
            "description": (
                "Climate indicator to compute. "
                "'gdd': Growing Degree Days (requires base_temp, uses tasmin+tasmax). "
                "'frost_days': Count of days with tasmin < 0 °C. "
                "'heat_stress_days': Count of days with tasmax > "
                "threshold (default 30 °C). "
                "'pr_total': Total precipitation over the period (mm). "
                "'pr_days': Count of days with precipitation > "
                "threshold (default 1 mm/day)."
            ),
            "schema": {
                "type": "string",
                "enum": [
                    "gdd",
                    "frost_days",
                    "heat_stress_days",
                    "pr_total",
                    "pr_days",
                ],
            },
            "minOccurs": 1,
            "maxOccurs": 1,
        },
        "start_date": {
            "title": "Start Date",
            "description": "Start of the temporal window (ISO 8601, YYYY-MM-DD).",
            "schema": {"type": "string", "format": "date"},
            "minOccurs": 1,
            "maxOccurs": 1,
        },
        "end_date": {
            "title": "End Date",
            "description": "End of the temporal window (ISO 8601, YYYY-MM-DD).",
            "schema": {"type": "string", "format": "date"},
            "minOccurs": 1,
            "maxOccurs": 1,
        },
        "dataset": {
            "title": "Dataset",
            "description": (
                "Source dataset. Use 'era5_land' (default) or 'rdrs_v2_1' for "
                "historical data; 'cmip6_espo_g6_r2' for projected indicators "
                "(requires scenario + model)."
            ),
            "schema": {
                "type": "string",
                "enum": ["era5_land", "rdrs_v2_1", "cmip6_espo_g6_r2"],
                "default": "era5_land",
            },
            "minOccurs": 0,
            "maxOccurs": 1,
        },
        "scenario": {
            "title": "Emissions Scenario",
            "description": (
                "Required when dataset is 'cmip6_espo_g6_r2'. "
                "One of: ssp245, ssp370, ssp585."
            ),
            "schema": {
                "type": "string",
                "enum": ["ssp245", "ssp370", "ssp585"],
            },
            "minOccurs": 0,
            "maxOccurs": 1,
        },
        "model": {
            "title": "Climate Model",
            "description": (
                "Required when dataset is 'cmip6_espo_g6_r2'. "
                "CMIP6 model name (e.g. 'MPI-ESM1-2-LR')."
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
            "minOccurs": 0,
            "maxOccurs": 1,
        },
        "base_temp": {
            "title": "Base Temperature",
            "description": (
                "Base temperature threshold for GDD computation in °C. "
                "GDD_i = max(0, (tasmax_i + tasmin_i) / 2 - base_temp). "
                "Common agronomic bases: 0 °C (cool-season crops), 5 °C (default, "
                "most cereals), 10 °C (corn and warm-season crops). "
                "Valid range: 0–15 °C. "
                "Only used by the 'gdd' indicator."
            ),
            "schema": {
                "type": "number",
                "default": 5.0,
                "minimum": 0.0,
                "maximum": 15.0,
            },
            "minOccurs": 0,
            "maxOccurs": 1,
        },
        "threshold": {
            "title": "Threshold",
            "description": (
                "Threshold value used by 'heat_stress_days' (°C, default 30.0) "
                "and 'pr_days' (mm/day, default 1.0). Ignored for other indicators. "
                "Valid range: 0–50."
            ),
            "schema": {
                "type": "number",
                "default": 30.0,
                "minimum": 0.0,
                "maximum": 50.0,
            },
            "minOccurs": 0,
            "maxOccurs": 1,
        },
    },
    "outputs": {
        "result": {
            "title": "Climate Indicator GeoJSON Feature",
            "description": (
                "A GeoJSON Feature whose geometry represents the queried area "
                "and whose properties contain the indicator result and metadata."
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
                            "indicator": {"type": "string"},
                            "base_temp": {"type": "number"},
                            "temporal_extent": {
                                "type": "array",
                                "items": {"type": "string"},
                            },
                            "result": {"type": "object"},
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
            "indicator": "gdd",
            "start_date": "2020-04-01",
            "end_date": "2020-09-30",
            "base_temp": 5.0,
            "dataset": "era5_land",
        }
    },
}
