"""Build the GEE FIELD_ID -> platform gid lookup table for the 440 SOM fields.

GEE numbers fields by the order of fields.toList(), which is a block permutation
of the shapefile row order (= platform gid, see prepare_som_data.py). This
script replays the GEE logic (gee_sentinel2_feature_extraction.js) on the source
layers, then matches each GEE field to its polygon by (sampleCount, mean_SOM,
stdDev_SOM, soilTypes). Ambiguous pairs are resolved with the offset of the
neighbouring uniquely-matched FIELD_IDs, then by elimination.

Run from the host whenever the source layers or the GEE export change:
  python gis-pipeline/scripts/build_field_id_map.py /path/to/Remote-Sensing-Project
"""

from __future__ import annotations

import argparse
from pathlib import Path

import geopandas as gpd
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = (
    REPO_ROOT
    / "gis-pipeline"
    / "src"
    / "gis_pipeline"
    / "resources"
    / "som_field_id_to_gid.csv"
)

EXPECTED_FIELDS = 440
EXPECTED_SAMPLES = 1406


def replay_gee_field_stats(source_dir: Path) -> pd.DataFrame:
    """Recompute per-gid SOM statistics the way the GEE script does.

    Fields x samples are spatially joined, samples are labelled with their soil
    type, and only fields with at least one soil type are kept.
    """
    boundaries_dir = source_dir / "FieldBoundariesandAnalysis"
    fields = gpd.read_file(
        boundaries_dir / "champs_boundary_luzerne_lcc_200322_REPROJECT.shp"
    )
    samples = gpd.read_file(boundaries_dir / "OriginalSoilAnalysis.shp")
    pedo = gpd.read_file(
        source_dir / "QC Soil Boundries" / "couverture_pedo_2022.shp",
        columns=["SYMBOL"],
    ).to_crs(4326)

    fields["gid"] = range(len(fields))
    samples["pid"] = range(len(samples))

    joined = gpd.sjoin(
        fields[["gid", "geometry"]],
        samples[["pid", "SOM", "geometry"]],
        predicate="intersects",
    )
    soil_types = gpd.sjoin(
        samples[["pid", "geometry"]], pedo, predicate="intersects"
    ).drop_duplicates("pid")[["pid", "SYMBOL"]]
    joined = joined.merge(soil_types, on="pid", how="left")
    stats = (
        joined.groupby("gid")
        .agg(
            n=("SOM", "count"),
            m=("SOM", "mean"),
            sd=("SOM", lambda x: x.std(ddof=0)),
            types=("SYMBOL", lambda x: "|".join(sorted(set(x.dropna())))),
        )
        .reset_index()
    )
    return stats[stats.types != ""]


def _match_key(
    df: pd.DataFrame, n: str, m: str, sd: str
) -> list[tuple[int, float, float, str]]:
    """Return the (count, mean, sd, soil types) key used to pair fields."""
    return list(zip(df[n], df[m].round(6), df[sd].round(6), df.types))


def match_field_ids(gee: pd.DataFrame, stats: pd.DataFrame) -> pd.DataFrame:
    """Pair each GEE FIELD_ID with one gid.

    Unique key matches come first. An ambiguous FIELD_ID takes the candidate
    whose offset equals a neighbouring block offset, otherwise the only
    candidate still free. Repeats until every FIELD_ID is resolved.
    """
    gee = gee.copy()
    gee["types"] = (
        gee.soilTypes.str.strip("[]")
        .str.split(", ")
        .apply(lambda types: "|".join(sorted(types)))
    )
    stats = stats.copy()
    stats["key"] = _match_key(stats, "n", "m", "sd")
    gee["key"] = _match_key(gee, "sampleCount", "mean_SOM", "stdDev_SOM")
    candidates = gee[["FIELD_ID", "key"]].merge(stats[["gid", "key"]], on="key")
    assert candidates.FIELD_ID.nunique() == EXPECTED_FIELDS

    counts = candidates.groupby("FIELD_ID").gid.transform("size")
    mapping = candidates[counts == 1][["FIELD_ID", "gid"]].assign(method="unique")
    unique = mapping.set_index("FIELD_ID").gid
    offsets = (unique.index - unique).sort_index()

    ambiguous = {
        fid: list(group.gid)
        for fid, group in candidates[counts > 1].groupby("FIELD_ID")
    }
    used = set(unique)
    rows: list[tuple[int, int, str]] = []
    while ambiguous:
        progress = False
        for fid, gids in list(ambiguous.items()):
            free = [g for g in gids if g not in used]
            lower = offsets[offsets.index < fid]
            upper = offsets[offsets.index > fid]
            near = {
                lower.iloc[-1] if len(lower) else None,
                upper.iloc[0] if len(upper) else None,
            }
            pick = [g for g in free if fid - g in near]
            if len(pick) == 1:
                rows.append((fid, pick[0], "block_offset"))
            elif len(free) == 1:
                rows.append((fid, free[0], "elimination"))
            else:
                continue
            used.add(rows[-1][1])
            del ambiguous[fid]
            progress = True
        assert progress, ambiguous

    mapping = pd.concat(
        [mapping, pd.DataFrame(rows, columns=["FIELD_ID", "gid", "method"])]
    )
    mapping["FIELD_ID"] = mapping.FIELD_ID.astype(int)
    assert mapping.FIELD_ID.is_unique and mapping.gid.is_unique
    assert len(mapping) == EXPECTED_FIELDS
    return (
        mapping.merge(stats[["gid", "n"]], on="gid")
        .rename(columns={"n": "sampleCount"})
        .sort_values("FIELD_ID")
    )


def parse_args() -> argparse.Namespace:
    """Parse the source directory and output path from the command line."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "source_dir",
        type=Path,
        help="Remote-Sensing-Project folder (FieldBoundariesandAnalysis, "
        "QC Soil Boundries, CSV_GEE_OUTPUT).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"Where to write the lookup CSV (default: {DEFAULT_OUTPUT}).",
    )
    return parser.parse_args()


def main() -> None:
    """Build and write the FIELD_ID -> gid lookup table."""
    args = parse_args()
    if not args.source_dir.is_dir():
        raise SystemExit(f"Source directory not found: {args.source_dir}")

    gee = pd.read_csv(
        args.source_dir / "CSV_GEE_OUTPUT" / "Field_SOM_Stats_Filtered.csv"
    )
    stats = replay_gee_field_stats(args.source_dir)
    assert len(stats) == len(gee) == EXPECTED_FIELDS
    assert stats.n.sum() == gee.sampleCount.sum() == EXPECTED_SAMPLES

    mapping = match_field_ids(gee, stats)
    mapping.to_csv(args.output, index=False)
    print(f"[OK] {len(mapping)} rows → {args.output}")
    print(mapping.method.value_counts().to_dict())


if __name__ == "__main__":
    main()
