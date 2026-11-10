"""make check-materialized lists large geometry collections without a usable index."""

import shutil
from pathlib import Path

import duckdb
import pytest
from vector_api.check_materialized import main
from vector_api.materialize import materialize_collection

pytestmark = pytest.mark.unit


@pytest.fixture
def data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("DUCKDB_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("VECTOR_API_RAW_PARQUET_WARN_MB", "1")
    return tmp_path


def _add(
    data_dir: Path, large_sources: dict[str, Path], name: str, source: str
) -> Path:
    path = data_dir / f"{name}.parquet"
    shutil.copy(large_sources[source], path)
    return path


def test_missing_index_is_listed(
    data_dir: Path,
    large_sources: dict[str, Path],
    capsys: pytest.CaptureFixture[str],
) -> None:
    size_mb = _add(data_dir, large_sources, "big", "geo").stat().st_size / 1024**2

    assert main() == 1

    lines = capsys.readouterr().out.splitlines()
    assert lines[0] == f"big  {size_mb:.1f} MB  missing"
    assert lines[1].startswith("1 of 1 collections")


def test_corrupt_index_is_listed_as_unreadable(
    data_dir: Path,
    large_sources: dict[str, Path],
    capsys: pytest.CaptureFixture[str],
) -> None:
    _add(data_dir, large_sources, "big", "geo")
    (data_dir / "big.duckdb").write_text("not a real duckdb file")

    assert main() == 1

    first_line = capsys.readouterr().out.splitlines()[0]
    assert first_line.startswith("big  ")
    assert "  unreadable: " in first_line


def test_index_without_items_table_is_listed_as_unreadable(
    data_dir: Path,
    large_sources: dict[str, Path],
    capsys: pytest.CaptureFixture[str],
) -> None:
    _add(data_dir, large_sources, "big", "geo")
    with duckdb.connect(str(data_dir / "big.duckdb")) as conn:
        conn.execute("CREATE TABLE other AS SELECT 1 AS x")

    assert main() == 1

    first_line = capsys.readouterr().out.splitlines()[0]
    assert first_line.startswith("big  ")
    assert "  unreadable: " in first_line


def test_unreadable_parquet_does_not_stop_the_scan(
    data_dir: Path,
    large_sources: dict[str, Path],
    capsys: pytest.CaptureFixture[str],
) -> None:
    (data_dir / "a_bad.parquet").write_bytes(b"junk" * (1024 * 1024))
    _add(data_dir, large_sources, "big", "geo")

    assert main() == 1

    lines = capsys.readouterr().out.splitlines()
    assert lines[0].startswith("a_bad  unchecked: ")
    assert lines[1].startswith("big  ")
    assert lines[1].endswith("  missing")
    assert lines[2].startswith("2 of 2 collections")


def test_nothing_to_report(
    data_dir: Path,
    large_sources: dict[str, Path],
    sample_geoparquet: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _add(data_dir, large_sources, "big_table", "plain")
    indexed = _add(data_dir, large_sources, "big_indexed", "geo")
    materialize_collection(indexed, data_dir / "big_indexed.duckdb")

    assert main() == 0

    assert capsys.readouterr().out.splitlines() == [
        "0 of 3 collections are geometry collections above 1 MB "
        "without a usable .duckdb"
    ]


def test_invalid_threshold_exits_2(
    data_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("VECTOR_API_RAW_PARQUET_WARN_MB", "0")

    assert main() == 2

    assert "VECTOR_API_RAW_PARQUET_WARN_MB" in capsys.readouterr().err


def test_missing_data_dir_exits_2(
    data_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("DUCKDB_DATA_DIR", str(data_dir / "absent"))

    assert main() == 2

    assert "Data directory not found" in capsys.readouterr().err
