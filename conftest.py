"""Root conftest - manages all fixtures and paths."""

import sys
from pathlib import Path

# Add all service paths to PYTHONPATH
workspace = Path(__file__).resolve().parent
sys.path.insert(0, str(workspace))
sys.path.insert(0, str(workspace / "gis-pipeline"))
sys.path.insert(0, str(workspace / "stac-api"))
sys.path.insert(0, str(workspace / "vector-api"))
sys.path.insert(0, str(workspace / "raster-api"))
sys.path.insert(0, str(workspace / "process-api"))
sys.path.insert(0, str(workspace / "tests_shared"))

# Import shared fixtures
pytest_plugins = ["tests_shared.conftest"]
