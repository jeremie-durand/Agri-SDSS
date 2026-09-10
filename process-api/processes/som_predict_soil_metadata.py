"""OGC API – Processes metadata definition for the som-predict-soil process."""

PROCESS_METADATA = {
    "version": "0.1.0",
    "id": "som-predict-soil",
    "title": {
        "en": "SOM Soil Prediction",
        "fr": "Prédiction de la matière organique du sol (MOS)",
    },
    "description": {
        "en": (
            "Predicts Soil Organic Matter (SOM) for selected agricultural field IDs "
            "using a RandomForest model trained on GEE-derived bare-soil spectral indices, "
            "topographic features, and bioclimatic variables (2019–2023). "
            "Training data is read directly from DuckDB Parquet files. "
            "Returns a GeoJSON FeatureCollection with per-image predictions and a "
            "field-level summary. Note: execution may take several minutes."
        ),
        "fr": (
            "Prédit la matière organique du sol (MOS) pour les parcelles sélectionnées "
            "à l'aide d'un modèle RandomForest entraîné sur des données GEE (indices "
            "spectraux, topographie, variables bioclimatiques, 2019–2023). "
            "Retourne un GeoJSON FeatureCollection avec les prédictions par image."
        ),
    },
    "keywords": [
        "som",
        "soil",
        "organic matter",
        "machine learning",
        "random forest",
        "gee",
    ],
    "jobControlOptions": ["sync-execute"],
    "outputTransmission": ["value"],
    "inputs": {
        "field_ids": {
            "title": "Field IDs",
            "description": (
                "List of integer field IDs (matching gid in the som_field_boundaries "
                "PostGIS table) to include in the prediction run. Required."
            ),
            "schema": {
                "type": "array",
                "items": {"type": "integer"},
                "minItems": 1,
            },
            "minOccurs": 1,
            "maxOccurs": 1,
        },
        "scenarios": {
            "title": "ML Scenarios",
            "description": (
                "Scenarios to run. Each adds more feature groups: "
                "S1_spec_soil (spectral + soil types), "
                "S2_spec_soil_topo (+ topography), "
                "S3_spec_soil_topo_clim (+ climate). "
                "Defaults to all three."
            ),
            "schema": {
                "type": "array",
                "items": {
                    "type": "string",
                    "enum": [
                        "S1_spec_soil",
                        "S2_spec_soil_topo",
                        "S3_spec_soil_topo_clim",
                    ],
                },
                "minItems": 1,
                "default": [
                    "S1_spec_soil",
                    "S2_spec_soil_topo",
                    "S3_spec_soil_topo_clim",
                ],
            },
            "minOccurs": 0,
            "maxOccurs": 1,
        },
    },
    "outputs": {
        "result": {
            "title": "SOM Prediction GeoJSON FeatureCollection",
            "description": (
                "A GeoJSON FeatureCollection where each Feature represents one "
                "(FIELD_ID, Image_ID) prediction. Feature geometry is the field polygon "
                "from PostGIS. Properties include y_true_lin, y_pred_lin, y_true_log, "
                "y_pred_log, algo, and scenario. A top-level field_summary key contains "
                "per-field aggregated metrics."
            ),
            "schema": {
                "type": "object",
                "contentMediaType": "application/geo+json",
            },
        }
    },
    "example": {
        "inputs": {
            "field_ids": [416, 417, 475, 476],
            "scenarios": ["S3_spec_soil_topo_clim"],
        }
    },
}
