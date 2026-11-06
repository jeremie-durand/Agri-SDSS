"""Guards the vector-api memory defaults against drifting between two files.

``DUCKDB_MEMORY_LIMIT``, ``VECTOR_API_MAX_OPEN_DUCKDB`` and
``VECTOR_API_MAX_DUCKDB_QUERIES`` each have a default in two places:

- ``docker-compose.yml``: the ``${VAR:-default}`` used by every deployment;
- ``vector-api/src/duckdb_manager.py``: the ``DEFAULT_*`` constants used when
  the variable is unset (tests, ad-hoc runs).

The three values were measured together against the real data in a 1 GiB
container (#288): cap 2 at 819MB walks every collection, while cap 4 at 819MB
is OOM-killed, and 512MB makes the largest single polygon answer 500 (#279).
Changing one of them in one file only is the regression this test catches.

Both files are read as literal text. ``docker-compose.yml`` is not in the
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
