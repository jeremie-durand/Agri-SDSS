from difflib import get_close_matches
from pathlib import Path
from typing import Dict, List

import pandas as pd
from pipeline.logging_setup import setup_logging
from pipeline.mapping import (
    ColumnMappings,
    CSVDataRegistryForSourceCRS,
    SupportedRasterFormats,
    SupportedVectorFormats,
)

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

    raster_extensions = {e.value for e in SupportedRasterFormats}
    vector_extensions = {e.value for e in SupportedVectorFormats}

    for file in input_path.rglob("*"):
        if file.is_file():
            if (ext := file.suffix.lower()) in raster_extensions:
                rasters.append(file)
            elif ext in vector_extensions:
                vectors.append(file)

    logger.info(
        f"Discovered {len(rasters)} raster files and {len(vectors)} vector files."
    )
    return {"rasters": rasters, "vectors": vectors}


def read_csv_file(
    vector_file: Path, encodings: list[str] | None = None, **read_csv_kwargs
) -> pd.DataFrame:
    """Utility to centralise pd.read_csv calls with sensible defaults and encoding fallback.

    - Tries a list of encodings (utf-8, latin1 by default).
    - Uses pandas' sep autodetection (engine='python', sep=None) so both ',' and ';' CSVs are accepted.
    - Accepts additional pd.read_csv kwargs via read_csv_kwargs.

    Args:
        vector_file: Path to the CSV file to read.
        encodings: List of encodings to try. Defaults to ['utf-8', 'latin1'].
        read_csv_kwargs: Additional keyword arguments to pass to pd.read_csv.

    Returns:
        DataFrame read from the CSV file.
    """
    if encodings is None:
        encodings = ["utf-8", "latin1"]

    last_exc = None
    for enc in encodings:
        try:
            # use sep=None with engine='python' to let pandas sniff delimiter
            df = pd.read_csv(
                vector_file, encoding=enc, sep=None, engine="python", **read_csv_kwargs
            )
            logger.debug(f"Read CSV {vector_file} with encoding={enc}")
            return df
        except Exception as e:
            logger.debug(f"Failed to read {vector_file} with encoding={enc}: {e}")
            last_exc = e

    logger.error(f"All attempts to read CSV {vector_file} failed.")
    if last_exc is None:
        raise ValueError(f"No encodings provided to read CSV {vector_file}")
    raise last_exc


def detect_non_spatial_csv(csv_files: list[Path]) -> list[Path]:
    """Detect CSVs and classify as non-spatial.

    Args:
        csv_files: List of Path objects pointing to CSV files.

    Returns:
        List of Paths to non-spatial CSV files.
    """
    known_csv_stems = {e.value[0].lower() for e in CSVDataRegistryForSourceCRS}

    non_spatial_files = []

    for csv_file in csv_files:
        stem = csv_file.stem.lower()

        if not get_close_matches(stem, known_csv_stems, n=1, cutoff=0.8):
            try:
                df = pd.read_csv(csv_file, nrows=3)  # Only read first 3 rows for speed
                columns_lower = [c.lower() for c in df.columns]

                lat_cols = [c.lower() for c in ColumnMappings.LATITUDE.value.alias] + [
                    ColumnMappings.LATITUDE.value.canonical
                ]
                lon_cols = [c.lower() for c in ColumnMappings.LONGITUDE.value.alias] + [
                    ColumnMappings.LONGITUDE.value.canonical
                ]

                if not any(c in columns_lower for c in lat_cols) or not any(
                    c in columns_lower for c in lon_cols
                ):
                    non_spatial_files.append(csv_file)

            except Exception:
                # If the CSV is unreadable, consider it non-spatial
                non_spatial_files.append(csv_file)

    return non_spatial_files
