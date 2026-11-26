"""Unit tests for the environment configuration classes."""

import pytest
from processes.config import JobQueueConfig, SpatialTablesConfig
from pydantic import ValidationError

JOB_QUEUE_VARIABLES: tuple[str, ...] = (
    "PROCESS_JOB_TIMEOUT_SECONDS",
    "PROCESS_JOB_RETENTION_DAYS",
    "PROCESS_WORKER_POLL_SECONDS",
    "PROCESS_WORKER_SWEEP_SECONDS",
)


@pytest.mark.unit
def test_spatial_tables_defaults(monkeypatch):
    for name in (
        "WATER_TABLE_NAME",
        "PEDO_TABLE_NAME",
        "PEDO_2022_TABLE_NAME",
        "SOM_TABLE_NAME",
        "SOM_ID_COLUMN",
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
    assert config.SOM_ID_COLUMN == "gid"


@pytest.mark.unit
def test_spatial_tables_read_from_env(monkeypatch):
    monkeypatch.setenv("PEDO_TABLE_NAME", "public.other_pedo")

    assert SpatialTablesConfig().PEDO_TABLE_NAME == "public.other_pedo"


@pytest.mark.unit
def test_job_queue_defaults(monkeypatch):
    for name in JOB_QUEUE_VARIABLES:
        monkeypatch.delenv(name, raising=False)

    config = JobQueueConfig()

    assert config.PROCESS_JOB_TIMEOUT_SECONDS == 1800
    assert config.PROCESS_JOB_RETENTION_DAYS == 7
    assert config.PROCESS_WORKER_POLL_SECONDS == 5
    assert config.PROCESS_WORKER_SWEEP_SECONDS == 60


@pytest.mark.unit
@pytest.mark.parametrize("name", JOB_QUEUE_VARIABLES)
@pytest.mark.parametrize("value", ["0", "-1"])
def test_job_queue_rejects_non_positive_values(monkeypatch, name, value):
    monkeypatch.setenv(name, value)

    with pytest.raises(ValidationError):
        JobQueueConfig()
