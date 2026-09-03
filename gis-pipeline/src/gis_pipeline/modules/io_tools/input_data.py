import sqlite3
from difflib import get_close_matches
from pathlib import Path
from typing import Dict, List

import pandas as pd
import structlog
from gis_pipeline.core.config import Config
from gis_pipeline.core.utils import harmonize_name
from gis_pipeline.services.mapping import (
    ColumnMappings,
    CSVDataRegistryForSourceCRS,
    NamingPatterns,
    SupportedRasterFormats,
    SupportedVectorFormats,
)

logger = structlog.get_logger()


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

    for item in input_path.rglob("*"):
        # Handle directories for GeoDatabases (.gdb)
        if item.is_dir():
            if item.suffix.lower() in vector_extensions:
                vectors.append(item)
                continue  # .gdb is a directory-based vector format; process as a single unit, not by its contents

        else:
            if item.suffix.lower() in raster_extensions:
                rasters.append(item)
            elif item.suffix.lower() in vector_extensions:
                vectors.append(item)

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


def extract_gpkg_fk_schema(
    gpkg_path: Path,
    layer_name_map: dict[str, str],
) -> list[dict]:
    """Extract foreign key relationships from a GeoPackage file.

    Reads SQLite PRAGMA foreign_key_list for each layer in layer_name_map,
    maps table and column names through harmonize_name(), and returns FK
    definitions ready for PostGISManager.apply_foreign_keys().

    Args:
        gpkg_path: Path to the .gpkg file.
        layer_name_map: {original SQLite layer name → harmonized PostgreSQL table name}.
            Built by the caller using the same harmonization applied during ingestion.

    Returns:
        List of dicts with keys {from_table, from_col, to_table, to_col}, all pg-safe.
        Never raises. A layer that cannot be read is skipped and logged as
        gpkg_fk_layer_failed, so the result may be partial — gpkg_fk_partial_extraction
        then reports which layers were lost. A file that cannot be opened at all
        yields an empty list, logged as gpkg_fk_extraction_failed.
    """

    def _h(name: str) -> str:
        return harmonize_name(
            name, NamingPatterns.PATTERN_GDF_NAME.value, Config.POSTGRES_MAX_NAME_LENGTH
        )

    fk_defs: list[dict] = []
    failed_layers: list[str] = []
    try:
        with sqlite3.connect(str(gpkg_path)) as conn:
            cursor = conn.cursor()
            for sqlite_table, pg_table in layer_name_map.items():
                try:
                    cursor.execute(f'PRAGMA foreign_key_list("{sqlite_table}")')
                    for row in cursor.fetchall():
                        # PRAGMA columns: id, seq, table, from, to, on_update,
                        # on_delete, match
                        _, _, ref_table, from_col, to_col = row[:5]
                        pg_ref = layer_name_map.get(ref_table)
                        if pg_ref is None:
                            logger.warning(
                                "gpkg_fk_unknown_ref_table",
                                from_table=sqlite_table,
                                ref_table=ref_table,
                                path=str(gpkg_path),
                            )
                            continue
                        fk_defs.append(
                            {
                                "from_table": pg_table,
                                "from_col": _h(from_col),
                                "to_table": pg_ref,
                                "to_col": _h(to_col),
                            }
                        )
                except Exception as exc:
                    failed_layers.append(sqlite_table)
                    logger.warning(
                        "gpkg_fk_layer_failed",
                        layer=sqlite_table,
                        path=str(gpkg_path),
                        error=str(exc),
                    )
    except Exception as exc:
        logger.warning(
            "gpkg_fk_extraction_failed",
            path=str(gpkg_path),
            error=str(exc),
        )

    if failed_layers:
        logger.warning(
            "gpkg_fk_partial_extraction",
            path=str(gpkg_path),
            failed_layers=failed_layers,
            extracted=len(fk_defs),
        )
    return fk_defs


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
