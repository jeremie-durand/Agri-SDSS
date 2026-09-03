"""Unit tests verifying that pygeoapi-config.yaml processor class paths are importable.

These tests catch configuration regressions (wrong class path, renamed module, missing
resource key) that mocked HTTP tests cannot detect.
"""

import importlib
from pathlib import Path

import pytest
import yaml

CONFIG_PATH = Path(__file__).parent.parent.parent / "config" / "pygeoapi-config.yaml"


@pytest.fixture(scope="module")
def config() -> dict:
    with CONFIG_PATH.open() as f:
        return yaml.safe_load(f)


@pytest.mark.unit
def test_config_file_exists():
    assert CONFIG_PATH.exists(), f"Config not found at {CONFIG_PATH}"


@pytest.mark.unit
def test_sentinel_fetch_resource_registered(config):
    assert (
        "sentinel-fetch" in config["resources"]
    ), "sentinel-fetch missing from resources"


@pytest.mark.unit
def test_processor_class_path_is_importable(config):
    processor_path = config["resources"]["sentinel-fetch"]["processor"]["name"]
    module_path, class_name = processor_path.rsplit(".", 1)
    module = importlib.import_module(module_path)
    assert hasattr(module, class_name), f"{class_name} not found in {module_path}"


@pytest.mark.unit
def test_processor_class_has_execute_method(config):
    processor_path = config["resources"]["sentinel-fetch"]["processor"]["name"]
    module_path, class_name = processor_path.rsplit(".", 1)
    module = importlib.import_module(module_path)
    cls = getattr(module, class_name)
    assert hasattr(cls, "execute"), f"{class_name}.execute() not found"


@pytest.mark.unit
def test_processor_metadata_id_matches_resource_key(config):
    processor_path = config["resources"]["sentinel-fetch"]["processor"]["name"]
    module_path, _class_name = processor_path.rsplit(".", 1)
    module = importlib.import_module(module_path)
    assert module.PROCESS_METADATA["id"] == "sentinel-fetch"
