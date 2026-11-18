"""Guards the vector-api memory envelope against drifting across repo files.

``DUCKDB_MEMORY_LIMIT``, ``VECTOR_API_MAX_OPEN_DUCKDB``,
``VECTOR_API_MAX_DUCKDB_QUERIES`` and ``VECTOR_API_MAX_PAGE_VERTICES`` each
have a default in two places:

- ``docker-compose.yml``: the ``${VAR:-default}`` used by every deployment;
- ``vector-api/src/duckdb_manager.py``: the ``DEFAULT_*`` constants used when
  the variable is unset (tests, ad-hoc runs).

The three values were measured together against the real data in a 1 GiB
container (#288): cap 2 at 819MB walks every collection, while cap 4 at 819MB
is OOM-killed, and 512MB makes the largest single polygon answer 500 (#279).
The page vertex budget bounds what one request can ask DuckDB to render, and
its default sits just above the largest real feature (#292). Changing one of
them in one file only is the regression this test catches.

vector-api's ``memswap_limit`` must equal its memory limit, so the container
never swaps and runs out of memory the same way on every host (#292). Without
it Docker allows as much swap again as the limit, and a request that does not
fit answers 200 slowly on a host with swap but is killed on one without.

vector-api runs a single uvicorn worker. The request gate and every DuckDB
``memory_limit`` are per process, so a second worker (``WEB_CONCURRENCY`` or
``--workers``) would let two heavy queries run at once in the same container.

The files are read as literal text. ``docker-compose.yml`` is not in the
vector-api image, so the test skips under ``make test-vector-api``. It runs
for real only through ``make test-repo-consistency``, which bind-mounts the
repo at ``/repo``.
"""

import re
from pathlib import Path

import pytest

REPO_ROOT: Path = Path(__file__).resolve().parent.parent.parent
DOCKER_COMPOSE_YML: Path = REPO_ROOT / "docker-compose.yml"
DUCKDB_MANAGER_PY: Path = REPO_ROOT / "vector-api" / "src" / "duckdb_manager.py"
VECTOR_API_DOCKERFILE: Path = REPO_ROOT / "vector-api" / "Dockerfile.vector-api"

pytestmark = [
    pytest.mark.unit,
    pytest.mark.skipif(
        not DOCKER_COMPOSE_YML.is_file(),
        reason="needs the full repo; run through make test-repo-consistency",
    ),
]

DEFAULTS: list[tuple[str, str]] = [
    ("DUCKDB_MEMORY_LIMIT", "DEFAULT_MEMORY_LIMIT"),
    ("VECTOR_API_MAX_OPEN_DUCKDB", "DEFAULT_MAX_OPEN_DUCKDB"),
    ("VECTOR_API_MAX_DUCKDB_QUERIES", "DEFAULT_MAX_DUCKDB_QUERIES"),
    ("VECTOR_API_MAX_PAGE_VERTICES", "DEFAULT_MAX_PAGE_VERTICES"),
]


def _compose_default(env_name: str) -> str:
    """Return the ``${VAR:-default}`` default from the vector-api env list."""
    pattern = re.compile(
        rf"^\s*-\s*{env_name}=\$\{{{env_name}:-([^}}]+)\}}\s*$", re.MULTILINE
    )
    matches = pattern.findall(DOCKER_COMPOSE_YML.read_text())
    assert len(matches) == 1, f"expected one {env_name} entry, found {matches}"
    return matches[0]


def _module_constant(constant: str) -> str:
    """Return a ``NAME: type = value`` constant's value, unquoted."""
    pattern = re.compile(rf"^{constant}:\s*\w+\s*=\s*(['\"]?)([^'\"\n]+)\1\s*$", re.M)
    match = pattern.search(DUCKDB_MANAGER_PY.read_text())
    assert match, f"{constant} not found in {DUCKDB_MANAGER_PY}"
    return match.group(2)


@pytest.mark.parametrize(("env_name", "constant"), DEFAULTS)
def test_compose_default_matches_module_constant(env_name: str, constant: str) -> None:
    assert _compose_default(env_name) == _module_constant(constant)


def _vector_api_block() -> str:
    """Return the vector-api service block of docker-compose.yml."""
    text = DOCKER_COMPOSE_YML.read_text()
    start = text.index("\n  vector-api:\n")
    end = re.search(r"\n  [a-z][a-z0-9_-]*:\n", text[start + 1 :])
    assert end, "vector-api is the last service"
    return text[start : start + 1 + end.start()]


def test_vector_api_never_swaps() -> None:
    block = _vector_api_block()
    memory = re.findall(r"^\s+memory:\s*(\S+)\s*$", block, re.MULTILINE)
    memswap = re.findall(r"^\s+memswap_limit:\s*(\S+)\s*$", block, re.MULTILINE)
    assert len(memory) == 1, f"expected one memory limit, found {memory}"
    assert memswap == memory


def test_vector_api_runs_one_worker() -> None:
    block = _vector_api_block()
    pinned = re.findall(r"^\s*-\s*WEB_CONCURRENCY=1\s*$", block, re.MULTILINE)
    assert block.count("WEB_CONCURRENCY") == len(pinned)
    assert "--workers" not in block


def test_vector_api_image_sets_no_workers() -> None:
    dockerfile = VECTOR_API_DOCKERFILE.read_text()
    assert "WEB_CONCURRENCY" not in dockerfile
    assert "--workers" not in dockerfile
