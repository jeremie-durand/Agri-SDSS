"""Prepare SOM data files for gis-pipeline ingestion.

Writes prepared files to data/input/vector/:
  - som_field_boundaries.shp  — field polygons with gid = OGR FID + has_gee_data flag
  - som_soil_samples.shp      — soil sample points reprojected from EPSG:3978 → 4326
  - som_soil_analysis.shp     — original soil analysis points (already EPSG:4326)

Run once before executing the gis-pipeline:
  python gis-pipeline/scripts/prepare_som_data.py

After the pipeline runs, also run migrate_gee_flags.py inside the gis-pipeline
container if the table already exists and needs the has_gee_data column updated:
  docker compose run --rm gis-pipeline python gis-pipeline/scripts/migrate_gee_flags.py
"""

from __future__ import annotations

import shutil
from pathlib import Path

import geopandas as gpd

SOM_DIR = Path(__file__).parent
FIELD_BOUNDARIES_DIR = SOM_DIR / "FieldBoundariesandAnalysis"
OUTPUT_DIR = Path(__file__).parent.parent / "input" / "vector"

TARGET_CRS = "EPSG:4326"


def prepare_field_boundaries() -> None:
    """Add gid = OGR FID to field boundaries so FIELD_ID in GEE CSVs is preserved.

    The has_gee_data column is added separately by migrate_gee_flags.py after
    the gis-pipeline has ingested this shapefile into PostGIS.
    """
    src = FIELD_BOUNDARIES_DIR / "champs_boundary_luzerne_lcc_200322_REPROJECT.shp"
    dst = OUTPUT_DIR / "som_field_boundaries.shp"
    gdf = gpd.read_file(src)
    gdf.insert(0, "gid", range(len(gdf)))
    gdf.to_file(dst, driver="ESRI Shapefile")
    print(f"[OK] som_field_boundaries.shp — {len(gdf)} features → {dst}")


def prepare_soil_samples() -> None:
    """Reproject Soil_analysis_210322_updated.shp from EPSG:3978 to EPSG:4326."""
    src = FIELD_BOUNDARIES_DIR / "Soil_analysis_210322_updated.shp"
    dst = OUTPUT_DIR / "som_soil_samples.shp"
    gdf = gpd.read_file(src).to_crs(TARGET_CRS)
    gdf.to_file(dst, driver="ESRI Shapefile")
    print(f"[OK] som_soil_samples.shp — {len(gdf)} features → {dst}")


def prepare_soil_analysis() -> None:
    """Copy OriginalSoilAnalysis.shp (already EPSG:4326) to input/vector/."""
    stem = "OriginalSoilAnalysis"
    dst_stem = "som_soil_analysis"
    for ext in (".shp", ".dbf", ".shx", ".prj", ".cpg", ".sbn", ".sbx"):
        src = FIELD_BOUNDARIES_DIR / f"{stem}{ext}"
        if src.exists():
            shutil.copy2(src, OUTPUT_DIR / f"{dst_stem}{ext}")
    print(f"[OK] som_soil_analysis.shp → {OUTPUT_DIR / f'{dst_stem}.shp'}")


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    prepare_field_boundaries()
    prepare_soil_samples()
    prepare_soil_analysis()
    print("\nAll SOM spatial files prepared.")
    print("Next: run gis-pipeline, then migrate_gee_flags.py inside the container.")


if __name__ == "__main__":
    main()
