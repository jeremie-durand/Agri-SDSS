"""Guards the COG route against drifting out of sync across services.

The literal string ``/cog`` is duplicated in four places that ship in
separate Docker images (or separate compose services) with no shared package
between them:

- ``frontend/home/scripts/entrypoint.sh`` — the nginx ``location`` block
  that serves the route, and the ``root`` it resolves against.
- ``docker-compose.yml`` — the ``home`` service's volume mount, whose
  container-side path (``root`` + route) must actually exist on disk.
- ``processes/asset_url_utils.py`` (this service) — ``COG_ROUTE``.
- ``gis-pipeline/src/gis_pipeline/core/config.py`` — ``COG_ROUTE``.

The duplication is structural: nothing short of a shared package could
remove it. The obvious failure mode — renaming the route in one of the two
``COG_ROUTE`` constants but not the other, or not in the nginx block — is
caught by comparing the three route strings. A subtler one is a *consistent*
rename across all three route strings that leaves the docker-compose volume
mount pointing at the old path: nginx would then resolve `/cogs/x.tif`
(route renamed) to `/usr/share/nginx/cogs/x.tif`, which is not a mounted
directory, and every COG 404s even though the three route strings still
agree with each other. This test also greps the mount's container-side path
out of docker-compose.yml and checks it ends with the same route segment.

Everything is grepped as literal text rather than imported or parsed as
YAML/nginx config, so a rename anywhere turns it red without needing either
service's runtime dependencies installed.

This test needs files from `frontend/home/`, `gis-pipeline/` and the repo
root that are not copied into the process-api Docker image (each service
ships in isolation — see the "Key source paths" note in the top-level
CLAUDE.md). It is a no-op skip under the standard ``make test-process-api``
container, and only runs for real via ``make test-repo-consistency``, which
bind-mounts the full repo into the process-api image (already built for the
standard suite) instead of relying on its baked-in ``/app`` copy. See the
Makefile.
"""

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

ENTRYPOINT_SH = REPO_ROOT / "frontend" / "home" / "scripts" / "entrypoint.sh"
DOCKER_COMPOSE_YML = REPO_ROOT / "docker-compose.yml"
PROCESS_API_ASSET_URL_UTILS = (
    REPO_ROOT / "process-api" / "processes" / "asset_url_utils.py"
)
GIS_PIPELINE_CONFIG = (
    REPO_ROOT / "gis-pipeline" / "src" / "gis_pipeline" / "core" / "config.py"
)

_ALL_FILES = (
    ENTRYPOINT_SH,
    DOCKER_COMPOSE_YML,
    PROCESS_API_ASSET_URL_UTILS,
    GIS_PIPELINE_CONFIG,
)
_REPO_AVAILABLE = all(path.is_file() for path in _ALL_FILES)

# Matches the literal nginx location block text:
#     location ~ ^/cog/[^/]+\.tiff?$ {
# Anchored on the raster-extension suffix `[^/]+\.tiff?$` (not just on the
# first `location ~ ^/<word>/` it finds) so an unrelated location block
# added above it — e.g. `location ~ ^/tiles/[^/]+\.png$` — cannot be
# mistaken for the COG route.
_NGINX_COG_LOCATION = re.compile(
    r"location ~ \^(/[A-Za-z0-9_-]+)/\[\^/\]\+\\\.tiff\?\$"
)

# Matches `COG_ROUTE = "/cog"` or `COG_ROUTE = '/cog'`.
_PY_COG_ROUTE = re.compile(r"^COG_ROUTE\s*=\s*(['\"])([^'\"]+)\1", re.MULTILINE)


def _nginx_cog_route(path: Path) -> str:
    """Return the COG route prefix from the nginx ``location`` regex."""
    text = path.read_text()
    match = _NGINX_COG_LOCATION.search(text)
    assert match, f"no COG location block found in {path}"
    return match.group(1)


def _python_cog_route(path: Path) -> str:
    """Return the COG route prefix from a ``COG_ROUTE = "..."`` assignment."""
    text = path.read_text()
    match = _PY_COG_ROUTE.search(text)
    assert match, f"no COG_ROUTE assignment found in {path}"
    return match.group(2)


def _compose_home_cog_mount(path: Path) -> str:
    """Return the container-side path of the home service's COG mount."""
    text = path.read_text()
    home_block = re.search(r"\n {2}home:\n(.*?)(?=\n {2}\S)", text, re.DOTALL)
    assert home_block, f"no top-level `home:` service block found in {path}"
    mount = re.search(r"-\s*\S*raster_cog:([^:\n]+):ro", home_block.group(1))
    assert mount, f"no raster_cog volume mount found on `home` in {path}"
    return mount.group(1)


@pytest.mark.unit
@pytest.mark.skipif(
    not _REPO_AVAILABLE,
    reason=(
        "requires frontend/home/, gis-pipeline/ and docker-compose.yml from "
        "the full repo checkout; run `make test-repo-consistency` instead "
        "of this container's own image-local /app copy"
    ),
)
def test_cog_route_matches_across_services():
    """The nginx route, both ``COG_ROUTE`` constants, and the compose mount
    all agree on the same route segment."""
    nginx_route = _nginx_cog_route(ENTRYPOINT_SH)
    process_api_route = _python_cog_route(PROCESS_API_ASSET_URL_UTILS)
    gis_pipeline_route = _python_cog_route(GIS_PIPELINE_CONFIG)

    assert nginx_route == process_api_route == gis_pipeline_route, (
        "COG route drift detected: "
        f"nginx entrypoint.sh={nginx_route!r}, "
        f"process-api COG_ROUTE={process_api_route!r}, "
        f"gis-pipeline COG_ROUTE={gis_pipeline_route!r}"
    )

    mount_path = _compose_home_cog_mount(DOCKER_COMPOSE_YML)
    route_segment = nginx_route.lstrip("/")
    assert mount_path.endswith(f"/{route_segment}"), (
        "COG route drift detected: the route is "
        f"{nginx_route!r} but docker-compose.yml mounts the COG directory "
        f"at {mount_path!r} on the `home` service, which does not end with "
        f"/{route_segment} — nginx would resolve requests to a directory "
        "that is not actually mounted"
    )
