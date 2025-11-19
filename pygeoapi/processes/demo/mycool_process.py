import math
import os

import pandas as pd
from pygeoapi.process.base import BaseProcessor, ProcessorExecuteError

PROCESS_METADATA = {
    "version": "0.1.0",
    "id": "mycool-process",
    "title": {
        "en": "My Cool Sqrt Process",
        "fr": "Mon super processus de racine carrée",
    },
    "description": {
        "en": 'Calculates square roots from a CSV column named "value"',
        "fr": 'Calcule la racine carrée d\'une colonne "value" dans un CSV',
    },
    "jobControlOptions": ["sync-execute"],
    "inputs": {},
    "outputs": {
        "sqrt_values": {
            "title": "Square Root Values",
            "description": "List of square root values computed from CSV",
            "schema": {"type": "object", "contentMediaType": "application/json"},
        }
    },
}


class MyCoolSqrtProcessor(BaseProcessor):
    def __init__(self, processor_def):
        super().__init__(processor_def, PROCESS_METADATA)

    def execute(self, data, outputs=None):
        mimetype = "application/json"

        # CSV file for demo is located in the same directory as this script
        csv_path = os.path.join(os.path.dirname(__file__), "obs.csv")
        if not os.path.exists(csv_path):
            raise ProcessorExecuteError(f"CSV file not found at {csv_path}")

        df = pd.read_csv(csv_path)

        if "value" not in df.columns:
            raise ProcessorExecuteError('Missing "value" column in CSV')

        df["sqrt"] = df["value"].apply(lambda x: round(math.sqrt(x), 3))
        results = df[["id", "value", "sqrt"]].to_dict(orient="records")

        return mimetype, {"id": "sqrt_values", "value": results}

    def __repr__(self):
        return f"<MyCoolSqrtProcessor> {self.name}"
