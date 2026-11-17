"""Child-process entry points for the SOM model store locking tests.

`spawn` children import their target by module path, so these functions live
in an importable module rather than in the test file.
"""

from __future__ import annotations

import json
import time
from multiprocessing.synchronize import Barrier
from pathlib import Path

import pandas as pd
import sklearn
from processes.som_backend.som_model_store import (
    BUNDLE_FORMAT_VERSION,
    SOMModelBundle,
    SOMModelStore,
)


class SlowCountingStore(SOMModelStore):
    """Trains a placeholder bundle slowly and logs each training run."""

    def __init__(self, model_dir: Path, runs_log: Path, delay: float) -> None:
        super().__init__(ml_backend=None, model_dir=model_dir)
        self._runs_log = runs_log
        self._delay = delay

    def _train(
        self, scenario: str, all_data: pd.DataFrame, fingerprint: str
    ) -> SOMModelBundle:
        started = time.time()
        time.sleep(self._delay)
        with self._runs_log.open("a") as log:
            log.write(
                json.dumps(
                    {"scenario": scenario, "start": started, "end": time.time()}
                )
                + "\n"
            )
        return SOMModelBundle(
            scenario=scenario,
            scaler=None,
            selected_features=[],
            feat_idx=[],
            col_means=pd.Series(dtype=float),
            mlb=None,
            log_som_bounds=(0.0, 1.0),
            rf_production=None,
            smearing_factor=1.0,
            cv_predictions={},
            global_metrics={},
            fingerprint=fingerprint,
            trained_at=f"{started}",
            sklearn_version=sklearn.__version__,
            format_version=BUNDLE_FORMAT_VERSION,
        )


def train_scenario(
    model_dir: str,
    data_dir: str,
    scenario: str,
    runs_log: str,
    result_path: str,
    delay: float,
    start_together: Barrier,
) -> None:
    """Run get_or_train() once every sibling is ready, and write the bundle's
    identity to result_path."""
    store = SlowCountingStore(Path(model_dir), Path(runs_log), delay)
    start_together.wait(timeout=60)
    bundle = store.get_or_train(scenario, pd.DataFrame(), Path(data_dir))
    Path(result_path).write_text(
        json.dumps({"fingerprint": bundle.fingerprint, "trained_at": bundle.trained_at})
    )
