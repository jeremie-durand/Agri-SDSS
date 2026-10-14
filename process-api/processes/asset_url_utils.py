"""Public URL builders for the STAC assets this deployment publishes.

A STAC asset href must be an absolute, publicly resolvable URI. The processors
write their COGs to a shared volume and know only the container-local path
(``/data/foo.tif``), which no external client can resolve, so every href goes
through one of these builders before it reaches an item.

Three URLs exist per COG: the file itself (served by the home nginx's static
COG route, byte-range capable), a TiTiler PNG preview, and a TiTiler TileJSON
document.
"""

import os
from typing import Optional
from urllib.parse import quote, unquote

from processes.config import PublicUrlConfig

# Public route serving the COG files themselves: a static `location` block
# in the home nginx (frontend/home/scripts/entrypoint.sh).
COG_ROUTE = "/cog"

# Public route proxying TiTiler.
RASTER_API_ROUTE = "/raster-api"

# Path the COG directory is mounted at inside the raster-api container; this is
# what TiTiler expects in its ``url`` query parameter.
RASTER_API_DATA_DIR = "/data"

# Tile grid identifier TiTiler 2.x requires in the TileJSON path.
TILE_MATRIX_SET = "WebMercatorQuad"


def _filename(cog_path: str) -> str:
    """Return the URL-encoded basename of a COG path.

    Accepts either a local path or an already-built public URL: the basename is
    unquoted before being re-quoted, so encoding is idempotent and a URL that
    has already been through these builders does not get double-encoded.
    """
    return quote(unquote(os.path.basename(cog_path)))


def cog_href(cog_path: str) -> str:
    """Return the public URL of the COG file itself.

    The route is served as a static file by the home nginx, so this URL
    answers Range requests and can be opened directly by GDAL, rasterio or
    QGIS.
    """
    return f"{PublicUrlConfig().base_url}{COG_ROUTE}/{_filename(cog_path)}"


def _render_query(rescale: Optional[str], bidx: Optional[int]) -> str:
    """Return the query suffix telling TiTiler how to render a COG."""
    suffix = f"&bidx={bidx}" if bidx else ""
    return f"{suffix}&rescale={rescale}" if rescale else suffix


def preview_href(
    cog_path: str, rescale: Optional[str] = None, bidx: Optional[int] = None
) -> str:
    """Return the public TiTiler PNG preview URL for a COG.

    Args:
        cog_path: Local path or already-public URL of the COG — only its
            basename is used, and encoding it is idempotent, so either form
            can be passed safely.
        rescale: Optional ``min,max`` pair for products whose values are not
            already in a displayable range.
        bidx: Optional 1-based band to render, required for a COG TiTiler
            cannot encode whole (see ``_display_band`` on the processors).
    """
    return (
        f"{PublicUrlConfig().base_url}{RASTER_API_ROUTE}/cog/preview.png"
        f"?url={RASTER_API_DATA_DIR}/{_filename(cog_path)}"
        f"{_render_query(rescale, bidx)}"
    )


def tilejson_href(
    cog_path: str, rescale: Optional[str] = None, bidx: Optional[int] = None
) -> str:
    """Return the public TiTiler TileJSON URL for a COG.

    Args:
        cog_path: Local path or already-public URL of the COG — only its
            basename is used.
        rescale: Optional ``min,max`` pair, carried into the tile URLs the
            TileJSON advertises so the tiles render with the same value range
            as the preview.
        bidx: Optional 1-based band, carried into the tile URLs for the same
            reason, so tiles and preview show the same band.
    """
    return (
        f"{PublicUrlConfig().base_url}{RASTER_API_ROUTE}/cog/{TILE_MATRIX_SET}"
        f"/tilejson.json?url={RASTER_API_DATA_DIR}/{_filename(cog_path)}"
        f"{_render_query(rescale, bidx)}"
    )
