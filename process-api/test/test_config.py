"""Unit tests for the environment configuration classes."""

import pytest
from processes.config import SpatialTablesConfig


@pytest.mark.unit
def test_spatial_tables_defaults(monkeypatch):
    for name in (
        "WATER_TABLE_NAME",
        "PEDO_TABLE_NAME",
        "PEDO_2022_TABLE_NAME",
        "SOM_TABLE_NAME",
    ):
        monkeypatch.delenv(name, raising=False)

    config = SpatialTablesConfig()

    assert config.WATER_TABLE_NAME == "public.grhq_water_union"
    assert (
        config.PEDO_TABLE_NAME
        == "public.couverture_pedologique_2026_01_couverture_p_cbc3c8"
    )
    assert config.PEDO_2022_TABLE_NAME == "public.couverture_pedo_2022"
    assert config.SOM_TABLE_NAME == "public.som_field_boundaries"


@pytest.mark.unit
def test_spatial_tables_read_from_env(monkeypatch):
    monkeypatch.setenv("PEDO_TABLE_NAME", "public.other_pedo")

    assert SpatialTablesConfig().PEDO_TABLE_NAME == "public.other_pedo"
