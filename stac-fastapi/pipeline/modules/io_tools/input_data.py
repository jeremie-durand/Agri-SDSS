from pathlib import Path
from typing import Dict, List

from pipeline.logging_setup import setup_logging
from pipeline.mapping import SupportedRasterFormats, SupportedVectorFormats

logger = setup_logging()


def discover_geodata(input_path: Path) -> Dict[str, List[Path]]:
    """Discover vector and raster data files in the input directory.

    Args:
        input_path: Path to the directory containing input data files

    Returns:
        Dictionary with keys 'vector' and 'raster', each containing a list of Paths.
    """
    rasters: List[Path] = []
    vectors: List[Path] = []

    for file in input_path.rglob("*"):
        if file.is_file():
            if (ext := file.suffix.lower()) in SupportedRasterFormats.get_extensions():
                rasters.append(file)
            elif ext in SupportedVectorFormats.get_extensions():
                vectors.append(file)

    logger.info(
        f"Discovered {len(rasters)} raster files and {len(vectors)} vector files."
    )
    return {"rasters": rasters, "vectors": vectors}
