"""Unit tests verifying that pygeoapi-config.yaml processor class paths are importable.

These tests catch configuration regressions (wrong class path, renamed module, missing
resource key) that mocked HTTP tests cannot detect. Every process the config
registers is listed by GET /processes, so each one is checked.
"""

import importlib
from pathlib import Path
from typing import Any

import pytest
import yaml

CONFIG_PATH = Path(__file__).parent.parent.parent / "config" / "pygeoapi-config.yaml"


def _load_config() -> dict[str, Any]:
    if not CONFIG_PATH.exists():
        return {}
    with CONFIG_PATH.open() as f:
        return yaml.safe_load(f) or {}


PROCESS_RESOURCES: list[tuple[str, str]] = [
    (resource_id, resource["processor"]["name"])
    for resource_id, resource in _load_config().get("resources", {}).items()
    if resource.get("type") == "process"
]
PROCESS_IDS: list[str] = [resource_id for resource_id, _ in PROCESS_RESOURCES]


@pytest.fixture(scope="module")
def config() -> dict[str, Any]:
    return _load_config()


@pytest.mark.unit
def test_config_file_exists():
    assert CONFIG_PATH.exists(), f"Config not found at {CONFIG_PATH}"


@pytest.mark.unit
def test_sentinel_fetch_resource_registered(config):
    assert (
        "sentinel-fetch" in config["resources"]
    ), "sentinel-fetch missing from resources"


@pytest.mark.unit
def test_config_registers_processes() -> None:
    assert PROCESS_RESOURCES, "no type: process resource in pygeoapi-config.yaml"


@pytest.mark.unit
@pytest.mark.parametrize(
    ("resource_id", "processor_path"),
    PROCESS_RESOURCES,
    ids=PROCESS_IDS,
)
def test_processor_class_path_is_importable(
    resource_id: str, processor_path: str
) -> None:
    module_path, class_name = processor_path.rsplit(".", 1)
    module = importlib.import_module(module_path)
    assert hasattr(module, class_name), f"{class_name} not found in {module_path}"


@pytest.mark.unit
@pytest.mark.parametrize(
    ("resource_id", "processor_path"),
    PROCESS_RESOURCES,
    ids=PROCESS_IDS,
)
def test_processor_class_has_execute_method(
    resource_id: str, processor_path: str
) -> None:
    module_path, class_name = processor_path.rsplit(".", 1)
    module = importlib.import_module(module_path)
    cls = getattr(module, class_name)
    assert hasattr(cls, "execute"), f"{class_name}.execute() not found"


@pytest.mark.unit
@pytest.mark.parametrize(
    ("resource_id", "processor_path"),
    PROCESS_RESOURCES,
    ids=PROCESS_IDS,
)
def test_processor_metadata_id_matches_resource_key(
    resource_id: str, processor_path: str
) -> None:
    module_path, _class_name = processor_path.rsplit(".", 1)
    module = importlib.import_module(module_path)
    assert module.PROCESS_METADATA["id"] == resource_id
