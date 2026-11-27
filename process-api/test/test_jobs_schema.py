"""The boot step that creates the jobs table (``python -m processes.jobs.schema``)."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from unittest.mock import patch

import pytest
from processes.jobs import schema
from processes.jobs.schema import ensure_schema, jobs_table
from processes.jobs.store import JobStore


def _write_config(tmp_path: Path, manager: str) -> Path:
    path = tmp_path / "pygeoapi-config.yaml"
    path.write_text(f"server:\n  manager:\n{manager}")
    return path


@pytest.mark.mocked
def test_boot_ensures_the_table_the_config_names(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _write_config(tmp_path, "    connection:\n      table: other.jobs\n")
    monkeypatch.setenv("PYGEOAPI_CONFIG", str(config))
    monkeypatch.setenv("PROCESS_JOBS_TABLE", "jobs.process_jobs")

    with patch.object(schema, "ensure_schema") as ensure:
        schema.main()

    ensure.assert_called_once_with("other.jobs")


@pytest.mark.mocked
def test_boot_ensures_the_environment_table_when_the_config_names_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _write_config(tmp_path, "    connection: null\n")
    monkeypatch.setenv("PYGEOAPI_CONFIG", str(config))
    monkeypatch.setenv("PROCESS_JOBS_TABLE", "jobs.process_jobs")

    with patch.object(schema, "ensure_schema") as ensure:
        schema.main()

    ensure.assert_called_once_with("jobs.process_jobs")


@pytest.mark.unit
def test_jobs_table_follows_the_manager_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("PROCESS_JOBS_TABLE", raising=False)

    assert jobs_table({"server": {}}) == "public.process_jobs"
    assert (
        jobs_table({"server": {"manager": {"connection": {"table": "public.zz"}}}})
        == "public.zz"
    )


@pytest.mark.unit
def test_jobs_table_falls_back_to_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PROCESS_JOBS_TABLE", "jobs.process_jobs")

    assert jobs_table({"server": {}}) == "jobs.process_jobs"
    assert jobs_table({"server": {"manager": {"connection": None}}}) == (
        "jobs.process_jobs"
    )
    assert (
        jobs_table({"server": {"manager": {"connection": {"table": "public.zz"}}}})
        == "public.zz"
    )


@pytest.mark.unit
@pytest.mark.parametrize("function", [ensure_schema, JobStore])
def test_the_table_has_no_default(function: Callable[..., object]) -> None:
    with pytest.raises(TypeError):
        function()
