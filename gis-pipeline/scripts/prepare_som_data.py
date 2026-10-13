"""Prepare SOM data files for gis-pipeline ingestion.

Reads the SOM source shapefiles from SOURCE_DIR (the FieldBoundariesandAnalysis
folder) and writes to data/input/vector/ by default:
  - som_field_boundaries.shp  — field polygons with gid = OGR FID
  - som_soil_samples.shp      — soil sample points reprojected from EPSG:3978 → 4326
  - som_soil_analysis.shp     — original soil analysis points (already EPSG:4326)

Run once from the host before executing the gis-pipeline:
  python gis-pipeline/scripts/prepare_som_data.py /path/to/FieldBoundariesandAnalysis

The pipeline stamps has_gee_data on som_field_boundaries itself at the end of
every run; no post-step is needed.
"""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

import geopandas as gpd

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT_DIR = REPO_ROOT / "data" / "input" / "vector"

TARGET_CRS = "EPSG:4326"


def prepare_field_boundaries(source_dir: Path, output_dir: Path) -> None:
    """Add gid = OGR FID to field boundaries so FIELD_ID in GEE CSVs is preserved.

    The has_gee_data column is added by the gis-pipeline after it ingests this
    shapefile into PostGIS.
    """
    src = source_dir / "champs_boundary_luzerne_lcc_200322_REPROJECT.shp"
    dst = output_dir / "som_field_boundaries.shp"
    gdf = gpd.read_file(src)
    gdf.insert(0, "gid", range(len(gdf)))
    gdf.to_file(dst, driver="ESRI Shapefile")
    print(f"[OK] som_field_boundaries.shp — {len(gdf)} features → {dst}")


def prepare_soil_samples(source_dir: Path, output_dir: Path) -> None:
    """Reproject Soil_analysis_210322_updated.shp from EPSG:3978 to EPSG:4326."""
    src = source_dir / "Soil_analysis_210322_updated.shp"
    dst = output_dir / "som_soil_samples.shp"
    gdf = gpd.read_file(src).to_crs(TARGET_CRS)
    gdf.to_file(dst, driver="ESRI Shapefile")
    print(f"[OK] som_soil_samples.shp — {len(gdf)} features → {dst}")


def prepare_soil_analysis(source_dir: Path, output_dir: Path) -> None:
    """Copy OriginalSoilAnalysis.shp (already EPSG:4326) to the output directory."""
    stem = "OriginalSoilAnalysis"
    dst_stem = "som_soil_analysis"
    for ext in (".shp", ".dbf", ".shx", ".prj", ".cpg", ".sbn", ".sbx"):
        src = source_dir / f"{stem}{ext}"
        if src.exists():
            shutil.copy2(src, output_dir / f"{dst_stem}{ext}")
    print(f"[OK] som_soil_analysis.shp → {output_dir / f'{dst_stem}.shp'}")


def parse_args() -> argparse.Namespace:
    """Parse the source and output directories from the command line."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "source_dir",
        type=Path,
        help="Folder holding the SOM source shapefiles (FieldBoundariesandAnalysis).",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=f"Where to write the prepared shapefiles (default: {DEFAULT_OUTPUT_DIR}).",
    )
    return parser.parse_args()


def main() -> None:
    """Prepare every SOM shapefile for ingestion."""
    args = parse_args()
    if not args.source_dir.is_dir():
        raise SystemExit(f"Source directory not found: {args.source_dir}")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    prepare_field_boundaries(args.source_dir, args.output_dir)
    prepare_soil_samples(args.source_dir, args.output_dir)
    prepare_soil_analysis(args.source_dir, args.output_dir)
    print("\nAll SOM spatial files prepared.")
    print("Next: run gis-pipeline.")


if __name__ == "__main__":
    main()
