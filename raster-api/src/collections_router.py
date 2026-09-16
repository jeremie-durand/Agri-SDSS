"""Collections listing endpoint for locally-mounted COG files.

TiTiler serves individual COGs by absolute file path (/cog/info?url=...)
but has no way to discover what files exist. This router adds a directory
listing so the /data frontend catalog can detect ingested rasters.
"""
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter

router = APIRouter()


def list_cog_files(data_dir: Optional[str] = None) -> List[Dict[str, Any]]:
    """List all COG (.tif/.tiff) files in the given directory.

    Args:
        data_dir: Directory to scan. Defaults to the RASTER_COG_DIR
            environment variable, or "/data" if unset.

    Returns:
        List of dicts with `id` (filename without extension) and `title`.
    """
    directory = Path(data_dir or os.environ.get("RASTER_COG_DIR", "/data"))
    if not directory.exists():
        return []
    files = sorted(list(directory.glob("*.tif")) + list(directory.glob("*.tiff")))
    return [
        {"id": f.stem, "title": f.stem.replace("_", " ").title()} for f in files
    ]


@router.get("/collections")
async def list_collections() -> Dict[str, Any]:
    """List all COG files available in the mounted raster data directory."""
    return {"collections": list_cog_files()}
