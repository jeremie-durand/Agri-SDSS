"""make check-parquet-memory measures each heavy request's peak RSS (#292)."""

from contextlib import AbstractContextManager
from email.message import Message
from pathlib import Path
from typing import Any
from unittest.mock import patch
from urllib.error import HTTPError

import pytest
from vector_api import check_peak_memory
from vector_api.check_peak_memory import (
    MeasurementError,
    main,
    parse_memory,
)

pytestmark = pytest.mark.unit

STATUS_TEXT: str = """Name:\tuvicorn
VmPeak:\t 2000000 kB
VmHWM:\t  786432 kB
VmRSS:\t  500000 kB
VmSwap:\t       0 kB
"""


def _status(hwm_kb: int, swap_kb: int = 0, name: str = "uvicorn") -> str:
    return f"Name:\t{name}\nVmHWM:\t {hwm_kb} kB\nVmSwap:\t {swap_kb} kB\n"


@pytest.fixture
def proc_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    (tmp_path / "clear_refs").write_text("")
    (tmp_path / "status").write_text(_status(400 * 1024))
    monkeypatch.setattr(check_peak_memory, "SERVER_PROC", tmp_path)
    monkeypatch.setattr(
        check_peak_memory, "HEAVY_REQUESTS", ["/parquet/a", "/postgis/b"]
    )
    monkeypatch.delenv("VECTOR_API_PEAK_RSS_MAX_MB", raising=False)
    return tmp_path


def _serve(
    proc_dir: Path, answers: dict[str, tuple[int, int, int]], swap_kb: int = 0
) -> AbstractContextManager[Any]:
    """Patch fetch: each path answers (status, body bytes, peak RSS in kB)."""

    def fetch(path: str) -> tuple[int, int, float]:
        status, body_bytes, hwm_kb = answers[path]
        (proc_dir / "status").write_text(_status(hwm_kb, swap_kb))
        return status, body_bytes, 0.5

    return patch.object(check_peak_memory, "fetch", side_effect=fetch)


def test_parse_memory_reads_peak_and_swap_in_mb() -> None:
    assert parse_memory(STATUS_TEXT) == (768, 0)
    assert parse_memory(_status(2048, 3 * 1024)) == (2, 3)


def test_parse_memory_without_vmhwm_cannot_measure() -> None:
    with pytest.raises(MeasurementError, match="VmHWM or VmSwap missing"):
        parse_memory("Name:\tuvicorn\nVmSwap:\t 0 kB\n")


def test_every_request_under_the_threshold_exits_0(
    proc_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    answers = {
        "/parquet/a": (200, 1024, 500 * 1024),
        "/postgis/b": (200, 10, 300 * 1024),
    }
    with _serve(proc_dir, answers):
        assert main() == 0

    out = capsys.readouterr().out.splitlines()
    assert out[0].startswith("ok  /parquet/a  status=200")
    assert "peak=500 MB" in out[0]
    assert out[-1] == "2 requests measured, 0 skipped, 0 failed (threshold 950 MB)"
    assert (proc_dir / "clear_refs").read_text() == "5"


def test_peak_above_the_threshold_exits_1(
    proc_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    answers = {
        "/parquet/a": (200, 1024, 1000 * 1024),
        "/postgis/b": (200, 10, 300 * 1024),
    }
    with _serve(proc_dir, answers):
        assert main() == 1

    first = capsys.readouterr().out.splitlines()[0]
    assert first.startswith("FAIL peak 1000 MB above 950 MB  /parquet/a")


def test_threshold_comes_from_the_environment(
    proc_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("VECTOR_API_PEAK_RSS_MAX_MB", "1000")
    answers = {
        "/parquet/a": (200, 1024, 990 * 1024),
        "/postgis/b": (200, 10, 300 * 1024),
    }
    with _serve(proc_dir, answers):
        assert main() == 0


def test_non_200_status_exits_1(
    proc_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    answers = {"/parquet/a": (500, 38, 300 * 1024), "/postgis/b": (200, 10, 300 * 1024)}
    with _serve(proc_dir, answers):
        assert main() == 1

    assert capsys.readouterr().out.splitlines()[0].startswith("FAIL status 500")


def test_swapped_memory_exits_1(
    proc_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    answers = {
        "/parquet/a": (200, 1024, 300 * 1024),
        "/postgis/b": (200, 10, 300 * 1024),
    }
    with _serve(proc_dir, answers, swap_kb=70 * 1024):
        assert main() == 1

    assert "70 MB swapped" in capsys.readouterr().out


@pytest.mark.parametrize("missing", ["/parquet/a", "/postgis/b"])
def test_404_on_either_backend_is_skipped_not_failed(
    proc_dir: Path, capsys: pytest.CaptureFixture[str], missing: str
) -> None:
    answers = {
        "/parquet/a": (200, 1024, 300 * 1024),
        "/postgis/b": (200, 10, 300 * 1024),
    }
    answers[missing] = (404, 60, 300 * 1024)
    with _serve(proc_dir, answers):
        assert main() == 0

    out = capsys.readouterr().out.splitlines()
    assert f"skipped  {missing}  (404: not on this stack)" in out
    assert out[-1].startswith("1 requests measured, 1 skipped, 0 failed")


def test_unwritable_clear_refs_exits_2(
    proc_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (proc_dir / "clear_refs").unlink()
    (proc_dir / "clear_refs").mkdir()

    assert main() == 2

    assert "Cannot reset the peak RSS" in capsys.readouterr().err


@pytest.mark.parametrize("raw", ["0", "-5", "abc"])
def test_invalid_threshold_exits_2(
    proc_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    raw: str,
) -> None:
    monkeypatch.setenv("VECTOR_API_PEAK_RSS_MAX_MB", raw)

    assert main() == 2

    assert "VECTOR_API_PEAK_RSS_MAX_MB" in capsys.readouterr().err


def test_parse_memory_refuses_a_process_other_than_uvicorn() -> None:
    with pytest.raises(MeasurementError, match="PID 1 is 'tini'"):
        parse_memory(_status(4 * 1024, name="tini"))


def test_server_that_is_not_uvicorn_exits_2(
    proc_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (proc_dir / "status").write_text(_status(4 * 1024, name="sh"))

    assert main() == 2

    assert "PID 1 is 'sh'" in capsys.readouterr().err


@pytest.mark.parametrize(
    "error",
    [ConnectionRefusedError(111, "refused"), TimeoutError("timed out")],
    ids=["refused", "timeout"],
)
def test_request_without_an_answer_fails_and_the_next_one_still_runs(
    proc_dir: Path, capsys: pytest.CaptureFixture[str], error: Exception
) -> None:
    with patch.object(check_peak_memory.urllib.request, "urlopen", side_effect=error):
        assert main() == 1

    out = capsys.readouterr().out.splitlines()
    assert out[0].startswith("FAIL status 0  /parquet/a")
    assert out[1].startswith("FAIL status 0  /postgis/b")
    assert out[-1] == "2 requests measured, 0 skipped, 2 failed (threshold 950 MB)"


@pytest.mark.parametrize(
    ("code", "first_line"),
    [(404, "skipped  /parquet/a  (404: not on this stack)"), (500, "FAIL status 500")],
    ids=["missing-collection", "server-error"],
)
def test_http_error_answers_keep_their_status(
    proc_dir: Path, capsys: pytest.CaptureFixture[str], code: int, first_line: str
) -> None:
    """urllib raises HTTPError for 404 and 500; their status must survive."""
    error = HTTPError("http://127.0.0.1/parquet/a", code, "error", Message(), None)
    with patch.object(check_peak_memory.urllib.request, "urlopen", side_effect=error):
        main()

    assert capsys.readouterr().out.splitlines()[0].startswith(first_line)
