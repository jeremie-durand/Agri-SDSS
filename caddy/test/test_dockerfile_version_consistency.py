"""Guards the two ``caddy:`` stages of Dockerfile.caddy against version drift.

The binary that ships is the one xcaddy compiles in the ``-builder`` stage;
the ``-alpine`` stage only supplies the runtime filesystem. Dependabot tracks
both ``FROM`` lines as one ``caddy`` dependency and has bumped them to
different versions (PR #305: 2.11.8-builder with 2.11.9-alpine), which ships
the older Caddy under a newer-looking runtime tag.

Run via ``make test-repo-consistency``. ``make test-caddy`` mounts only
``caddy/test/`` and selects ``-m integration``, so it never runs this test.
"""

import re
from pathlib import Path

import pytest

DOCKERFILE = Path(__file__).resolve().parent.parent / "Dockerfile.caddy"

_CADDY_FROM = re.compile(
    r"^FROM\s+caddy:(\d+\.\d+\.\d+)-(\S+)", re.MULTILINE | re.IGNORECASE
)


@pytest.mark.unit
def test_builder_and_runtime_caddy_versions_match() -> None:
    """Both ``FROM caddy:<version>-<variant>`` lines pin the same version."""
    stages: dict[str, str] = {
        variant: version
        for version, variant in _CADDY_FROM.findall(DOCKERFILE.read_text())
    }
    builder = next((v for k, v in stages.items() if k.startswith("builder")), None)
    runtime = next((v for k, v in stages.items() if not k.startswith("builder")), None)

    assert builder and runtime, (
        f"expected a caddy builder and a caddy runtime stage in {DOCKERFILE}, "
        f"found {stages}"
    )
    assert builder == runtime, (
        f"Caddy version drift in {DOCKERFILE.name}: builder stage is "
        f"{builder}, runtime stage is {runtime}. The builder version is the "
        "Caddy that actually ships — bump both FROM lines together"
    )
