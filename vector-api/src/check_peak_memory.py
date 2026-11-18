"""Measure vector-api's peak RSS for each known heavy request (#292).

Run inside the vector-api container with ``python -m vector_api.check_peak_memory``
(``make check-parquet-memory``). For each request it resets the uvicorn
process's peak RSS (``/proc/1/clear_refs``), sends the request to the local
server, reads the body without keeping it, then reads ``VmHWM`` and ``VmSwap``
from ``/proc/1/status``. Requests run one at a time.

Exit codes: 0 every request passed; 1 a peak above
``VECTOR_API_PEAK_RSS_MAX_MB`` (default 950), a status other than 200, or
swapped memory; 2 the process cannot be measured or the threshold is invalid.
A collection that answers 404 on one backend is skipped, not failed.
"""

import http.client
import os
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

BASE_URL: str = f"http://127.0.0.1:{os.getenv('VECTOR_API_PORT', '8083')}"
SERVER_PROCESS_NAME: str = "uvicorn"
SERVER_PROC: Path = Path("/proc/1")
# The shortened 1.5M-vertex page grhq_hr_04ac_s_udh?limit=10000 peaks at
# 774-960 MB, so it can exceed this; the other heavy requests stay at or below
# 833 MB. Lower the budget and this threshold once no stored feature is above
# 100 000 vertices (#292 follow-up; see vector-api/CLAUDE.md).
DEFAULT_PEAK_RSS_MAX_MB: int = 950
TIMEOUT_SECONDS: int = 300
READ_CHUNK_BYTES: int = 1024 * 1024
KB_PER_MB: int = 1024

HEAVY_REQUESTS: list[str] = [
    "/parquet/collections/grhq_hr_06aa_udh/items?limit=1",
    "/parquet/collections/grhq_hr_06ac_udh/items?limit=1",
    "/parquet/collections/grhq_hr_04ac_udh/items?limit=1",
    "/parquet/collections/grhq_hr_04ac_s_udh/items",
    "/parquet/collections/grhq_hr_04ac_s_udh/items?limit=10000",
    "/parquet/collections/couverture_pedo_2022/items?limit=10000",
    "/parquet/collections/couverture_pedo_2022/items?offset=200000&limit=100",
    "/parquet/collections/grhq_hr_05ae_rh_j/items?limit=10000",
    "/postgis/collections/public.grhq_hr_06aa_udh/items?limit=1",
    "/postgis/collections/public.grhq_hr_06ac_udh/items?limit=1",
    "/postgis/collections/public.grhq_hr_04ac_udh/items?limit=1",
    "/postgis/collections/public.grhq_hr_04ac_s_udh/items",
]


class MeasurementError(RuntimeError):
    """Raised when the server process cannot be measured."""


@dataclass(frozen=True)
class Measurement:
    """One request's result and the server's memory figures after it."""

    path: str
    status: int
    body_bytes: int
    seconds: float
    peak_rss_mb: int
    swap_mb: int


def parse_memory(status_text: str) -> tuple[int, int]:
    """Return (peak RSS, swapped) in MB from the text of /proc/<pid>/status.

    Raises:
        MeasurementError: If the process is not the uvicorn server (a shell or
            an init would report a few MB and every request would pass), or if
            VmHWM or VmSwap is missing.
    """
    values: dict[str, int] = {}
    name = ""
    for line in status_text.splitlines():
        key, _, rest = line.partition(":")
        if key == "Name":
            name = rest.strip()
        elif key in ("VmHWM", "VmSwap"):
            values[key] = int(rest.split()[0]) // KB_PER_MB
    if name != SERVER_PROCESS_NAME:
        raise MeasurementError(
            f"PID 1 is {name!r}, not {SERVER_PROCESS_NAME!r}: cannot measure the server"
        )
    if set(values) != {"VmHWM", "VmSwap"}:
        raise MeasurementError("VmHWM or VmSwap missing from the process status")
    return values["VmHWM"], values["VmSwap"]


def problems(measurement: Measurement, max_mb: int) -> list[str]:
    """Return what makes a measurement fail; empty when it passes."""
    found: list[str] = []
    if measurement.status != 200:
        found.append(f"status {measurement.status}")
    if measurement.peak_rss_mb > max_mb:
        found.append(f"peak {measurement.peak_rss_mb} MB above {max_mb} MB")
    if measurement.swap_mb:
        found.append(f"{measurement.swap_mb} MB swapped")
    return found


def peak_rss_max_mb() -> int:
    """Return the threshold from VECTOR_API_PEAK_RSS_MAX_MB, or the default.

    Raises:
        MeasurementError: If the variable is set but not a positive integer.
    """
    raw = os.getenv("VECTOR_API_PEAK_RSS_MAX_MB") or str(DEFAULT_PEAK_RSS_MAX_MB)
    try:
        value = int(raw)
    except ValueError:
        value = 0
    if value < 1:
        raise MeasurementError(
            f"VECTOR_API_PEAK_RSS_MAX_MB must be a positive integer, got {raw!r}"
        )
    return value


def reset_peak() -> None:
    """Reset the server process's VmHWM.

    Raises:
        MeasurementError: If /proc/1/clear_refs cannot be written.
    """
    try:
        (SERVER_PROC / "clear_refs").write_text("5")
    except OSError as e:
        raise MeasurementError(f"Cannot reset the peak RSS of PID 1: {e}") from e


def read_memory() -> tuple[int, int]:
    """Return (peak RSS, swapped) in MB of the server process.

    Raises:
        MeasurementError: If /proc/1/status cannot be read or parsed.
    """
    try:
        return parse_memory((SERVER_PROC / "status").read_text())
    except OSError as e:
        raise MeasurementError(f"Cannot read the status of PID 1: {e}") from e


def fetch(path: str) -> tuple[int, int, float]:
    """GET path on the server; return its status, body size and duration.

    A request that gets no complete answer (refused, timed out, cut off) has
    status 0, so it is reported as failed and the next request still runs.
    """
    started = time.monotonic()
    body_bytes = 0
    try:
        with urllib.request.urlopen(
            f"{BASE_URL}{path}", timeout=TIMEOUT_SECONDS
        ) as response:
            status = response.status
            while chunk := response.read(READ_CHUNK_BYTES):
                body_bytes += len(chunk)
    except urllib.error.HTTPError as e:
        status = e.code
    except (urllib.error.URLError, http.client.HTTPException, OSError):
        status = 0
    return status, body_bytes, time.monotonic() - started


def measure(path: str) -> Measurement:
    """Run one request from a reset peak and return its figures."""
    reset_peak()
    status, body_bytes, seconds = fetch(path)
    peak_rss_mb, swap_mb = read_memory()
    return Measurement(path, status, body_bytes, seconds, peak_rss_mb, swap_mb)


def check(requests: list[str], max_mb: int) -> int:
    """Measure each request and print one line per request.

    Returns:
        1 if any request failed, 0 otherwise.
    """
    failed = skipped = 0
    for path in requests:
        measurement = measure(path)
        if measurement.status == 404:
            skipped += 1
            print(f"skipped  {path}  (404: not on this stack)")
            continue
        found = problems(measurement, max_mb)
        failed += bool(found)
        verdict = "FAIL " + "; ".join(found) if found else "ok"
        print(
            f"{verdict}  {path}  status={measurement.status}  "
            f"body={measurement.body_bytes / (1024 * 1024):.1f} MiB  "
            f"peak={measurement.peak_rss_mb} MB  swap={measurement.swap_mb} MB  "
            f"time={measurement.seconds:.1f} s"
        )
    print(
        f"{len(requests) - skipped} requests measured, {skipped} skipped, "
        f"{failed} failed (threshold {max_mb} MB)"
    )
    return 1 if failed else 0


def main() -> int:
    try:
        read_memory()
        return check(HEAVY_REQUESTS, peak_rss_max_mb())
    except MeasurementError as e:
        print(e, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
