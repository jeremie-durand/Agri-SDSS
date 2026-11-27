"""Guards the compose default that keeps the private SOM tables off vector-api.

``TIPG_DB_EXCLUDE_TABLES`` hides ``som_field_boundaries``, ``som_soil_samples``
and ``som_soil_analysis`` from both vector-api backends: they hold producers'
personal data and the private soil samples of the research team that provided
them. The default in ``docker-compose.yml`` is the only place that lists them,
since the other tests inject their own value, so dropping or misspelling an
entry there would publish a table again with every other test green.

Like ``test_memory_defaults_consistency.py``, it reads ``docker-compose.yml``
as text, skips under ``make test-vector-api`` and runs for real through
``make test-repo-consistency``.
"""

import json
import re
from pathlib import Path

import pytest

REPO_ROOT: Path = Path(__file__).resolve().parent.parent.parent
DOCKER_COMPOSE_YML: Path = REPO_ROOT / "docker-compose.yml"

PRIVATE_TABLES: set[str] = {
    "public.som_field_boundaries",
    "public.som_soil_samples",
    "public.som_soil_analysis",
}

pytestmark = [
    pytest.mark.unit,
    pytest.mark.skipif(
        not DOCKER_COMPOSE_YML.is_file(),
        reason="needs the full repo; run through make test-repo-consistency",
    ),
]


def test_compose_default_hides_the_private_som_tables() -> None:
    pattern = re.compile(
        r"^\s*-\s*TIPG_DB_EXCLUDE_TABLES=\$\{TIPG_DB_EXCLUDE_TABLES:-(.+)\}\s*$",
        re.MULTILINE,
    )
    matches = pattern.findall(DOCKER_COMPOSE_YML.read_text())
    assert len(matches) == 1, f"expected one TIPG_DB_EXCLUDE_TABLES entry: {matches}"
    assert PRIVATE_TABLES <= set(json.loads(matches[0]))
