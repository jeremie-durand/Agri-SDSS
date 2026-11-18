"""Guards the ``database`` service's ``PGDATA`` against drifting from its data mount.

The pgSTAC image tag does not show its PostgreSQL major version, and the
PostgreSQL 18 images moved the default data directory to
``/var/lib/postgresql/18/docker``. pgSTAC's own entrypoint has no check for the
old path, so without an explicit ``PGDATA`` an image bump would start a new,
empty cluster next to the mounted data. Pinned to the mount target, a database
image built on another major version refuses the existing directory instead
(#90).

Run via ``make test-repo-consistency``, which bind-mounts the repo at
``/repo``.
"""

import re
from pathlib import Path

import pytest

REPO_ROOT: Path = Path(__file__).resolve().parent.parent.parent
DOCKER_COMPOSE_YML: Path = REPO_ROOT / "docker-compose.yml"

pytestmark = pytest.mark.unit

_SERVICE_BLOCK = re.compile(
    r"^  database:\n(?P<body>(?:^(?: {4,}.*)?\n)+)", re.MULTILINE
)
_PGDATA_ENV = re.compile(r"^\s*-\s*PGDATA=(?P<value>\S+)\s*$", re.MULTILINE)
_DATA_MOUNT = re.compile(
    r"^\s*-\s*\$\{PGDATA_PATH(?::-[^}]*)?\}:(?P<target>[^:\s]+)(?::\w+)?\s*$",
    re.MULTILINE,
)


def _database_block() -> str:
    """Return the indented body of the ``database`` service."""
    match = _SERVICE_BLOCK.search(DOCKER_COMPOSE_YML.read_text())
    assert match, f"no database service found in {DOCKER_COMPOSE_YML.name}"
    return match.group("body")


def test_pgdata_is_pinned_to_the_data_mount() -> None:
    """``PGDATA`` is set and equals the container side of the data volume."""
    block = _database_block()
    pgdata = _PGDATA_ENV.findall(block)
    targets = _DATA_MOUNT.findall(block)

    assert len(pgdata) == 1, (
        f"the database service must set PGDATA exactly once, found {pgdata}: "
        "without it a database image with another default data path starts "
        "an empty cluster instead of refusing the mounted one"
    )
    assert (
        len(targets) == 1
    ), f"expected one ${{PGDATA_PATH}} volume on the database service, found {targets}"
    assert (
        pgdata[0] == targets[0]
    ), f"PGDATA={pgdata[0]} does not match the data mount target {targets[0]}"
