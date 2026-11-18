"""The image ships the DuckDB extensions vector-api loads, so no download runs.

These tests check the environment they run in: they pass only in a vector-api
image whose build installed the extensions for the runtime user.
"""

from pathlib import Path

import duckdb
import pytest

pytestmark = pytest.mark.integration

UNREACHABLE_REPOSITORY = "http://127.0.0.1:9"


def test_spatial_loads_without_install() -> None:
    conn = duckdb.connect(
        config={
            "autoinstall_known_extensions": False,
            "autoload_known_extensions": False,
        }
    )
    try:
        conn.execute("LOAD spatial")
    finally:
        conn.close()


def test_spatial_was_installed_before_the_test_session(
    session_start_time: float,
) -> None:
    conn = duckdb.connect()
    try:
        install_path = conn.execute(
            "SELECT install_path FROM duckdb_extensions() "
            "WHERE extension_name = 'spatial' AND installed"
        ).fetchone()
    finally:
        conn.close()

    assert install_path is not None
    assert Path(install_path[0]).stat().st_mtime < session_start_time


def test_runtime_install_needs_no_network() -> None:
    conn = duckdb.connect()
    try:
        conn.execute(f"SET custom_extension_repository = '{UNREACHABLE_REPOSITORY}'")
        conn.execute("INSTALL spatial")
        conn.execute("LOAD spatial")
    finally:
        conn.close()
