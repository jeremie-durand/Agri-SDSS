#!/usr/bin/env python3
"""Compare parcel mean summer NDVI from sentinel-fetch with and without the
per-pixel SCL cloud mask (reviewer comment R2.6).

Two steps, so the parcel sample is fixed and reusable:

``sample`` picks N BDPPAD parcels spread over Quebec — one random field-sized
parcel per 0.5° grid cell, with a fixed seed — and writes them as GeoJSON.
It reads a local BDPPAD GeoParquet with DuckDB, so run it where the data is::

    python3 scripts/compare_ndvi_cloud_mask.py sample \\
        --parquet data/duckdb/bdppad_v03_an_2025_s_20260504.parquet \\
        --out ndvi_scl_parcels.geojson --n 30

``run`` calls sentinel-fetch on the deployed API for every parcel, once with
``cloud_mask: false`` and once with ``cloud_mask: true``, using the SOM form
settings (June 1 - August 31 of the year, ``cloud_cover_max`` 20, median
composite, NDVI), and writes one CSV row per call. It resumes from an existing
CSV, so an interrupted run can be restarted. Only the standard library is
needed::

    python3 scripts/compare_ndvi_cloud_mask.py run \\
        --base-url https://<host> --parcels ndvi_scl_parcels.geojson \\
        --year 2025 --out ndvi_scl_comparison.csv

``scenes`` counts, for every parcel, the Sentinel-2 L2A scenes over the same
window in the public Copernicus Data Space STAC catalogue: all of them, and
those passing the ``eo:cloud_cover`` <= 20 scene filter, i.e. the dates the
median composite is built from. It needs no openEO credentials or credits::

    python3 scripts/compare_ndvi_cloud_mask.py scenes \
        --parcels ndvi_scl_parcels.geojson --year 2025 --out ndvi_scl_scenes.csv

``summary`` prints the mean, mean absolute and maximum absolute NDVI
difference (masked - unmasked) over the parcels where both calls succeeded,
and, given the scenes CSV, the number of retained dates per parcel and the
differences split by that number::

    python3 scripts/compare_ndvi_cloud_mask.py summary --csv ndvi_scl_comparison.csv \
        --scenes ndvi_scl_scenes.csv

Each cold sentinel-fetch call takes minutes, and process-api runs one worker,
so a full run of 30 parcels (60 calls) takes a few hours and blocks other
process-api requests meanwhile: run it off-peak.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import random
import statistics
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

# Only the sample step needs DuckDB; run and summary use the standard library.
try:
    import duckdb
except ImportError:
    duckdb = None

GRID_DEGREES = 0.5
MIN_PARCEL_HA = 2.0
MAX_PARCEL_HA = 30.0
REQUEST_TIMEOUT_S = 700
CLOUD_COVER_MAX = 20
CDSE_STAC_SEARCH = "https://stac.dataspace.copernicus.eu/v1/search"
CDSE_COLLECTION = "sentinel-2-l2a"
FEW_SCENES = 3
SCENE_FIELDS = [
    "idanpar",
    "retained_items",
    "retained_dates",
    "all_dates",
    "median_cloud_cover_retained",
    "tiles",
]
CSV_FIELDS = [
    "idanpar",
    "cloud_mask",
    "ndvi_mean",
    "stac_item_id",
    "elapsed_s",
    "error",
]


def sample_parcels(parquet: Path, n: int, seed: int) -> list[dict]:
    """Return n GeoJSON features, one random parcel per grid cell."""
    if duckdb is None:
        sys.exit("The sample step needs DuckDB: pip install duckdb")
    con = duckdb.connect()
    con.execute("INSTALL spatial")
    con.execute("LOAD spatial")
    rows = con.execute(
        f"""
        SELECT idanpar, suphec,
               floor(ST_X(ST_Centroid(geometry)) / {GRID_DEGREES}) AS cx,
               floor(ST_Y(ST_Centroid(geometry)) / {GRID_DEGREES}) AS cy,
               ST_AsGeoJSON(geometry) AS geom
        FROM read_parquet(?)
        WHERE suphec BETWEEN ? AND ?
          AND ST_GeometryType(geometry) IN ('POLYGON', 'MULTIPOLYGON')
        """,
        [str(parquet), MIN_PARCEL_HA, MAX_PARCEL_HA],
    ).fetchall()
    con.close()

    by_cell: dict[tuple[float, float], list[tuple]] = {}
    for row in rows:
        by_cell.setdefault((row[2], row[3]), []).append(row)
    rng = random.Random(seed)
    cells = sorted(by_cell)
    rng.shuffle(cells)
    if len(cells) < n:
        sys.exit(f"Only {len(cells)} grid cells hold parcels; lower --n.")

    features = []
    for cell in cells[:n]:
        idanpar, suphec, _cx, _cy, geom = rng.choice(by_cell[cell])
        features.append(
            {
                "type": "Feature",
                "properties": {"idanpar": int(idanpar), "suphec": float(suphec)},
                "geometry": json.loads(geom),
            }
        )
    return features


def fetch_ndvi(
    base_url: str, geometry: dict, year: int, cloud_mask: bool
) -> tuple[float | None, str, str]:
    """Call sentinel-fetch and return (NDVI mean, STAC item id, error)."""
    body = {
        "inputs": {
            "farm_geometry": geometry,
            "temporal_extent": [f"{year}-06-01", f"{year}-08-31"],
            "output_products": ["ndvi"],
            "aggregation_method": "median",
            "cloud_cover_max": CLOUD_COVER_MAX,
            "cloud_mask": cloud_mask,
        }
    }
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}/process-api/processes/sentinel-fetch/execution?f=json",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_S) as response:
            value = json.load(response)["value"]
    except (urllib.error.URLError, TimeoutError, KeyError, ValueError) as exc:
        return None, "", str(exc)
    bands = value["stac_item"]["assets"]["ndvi"].get("bands") or [{}]
    mean = bands[0].get("statistics", {}).get("mean")
    return mean, value.get("stac_item_id", ""), ""


def run_comparison(base_url: str, parcels: Path, year: int, out: Path) -> None:
    """Call sentinel-fetch twice per parcel, appending one CSV row per call."""
    features = json.loads(parcels.read_text())["features"]
    done: set[tuple[str, str]] = set()
    if out.exists():
        with out.open(newline="") as f:
            done = {
                (row["idanpar"], row["cloud_mask"])
                for row in csv.DictReader(f)
                if not row["error"]
            }

    write_header = not out.exists()
    with out.open("a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        if write_header:
            writer.writeheader()
        for i, feature in enumerate(features, start=1):
            idanpar = str(feature["properties"]["idanpar"])
            for cloud_mask in (False, True):
                if (idanpar, str(cloud_mask)) in done:
                    continue
                start = time.monotonic()
                ndvi, item_id, error = fetch_ndvi(
                    base_url, feature["geometry"], year, cloud_mask
                )
                elapsed = round(time.monotonic() - start, 1)
                writer.writerow(
                    {
                        "idanpar": idanpar,
                        "cloud_mask": cloud_mask,
                        "ndvi_mean": "" if ndvi is None else ndvi,
                        "stac_item_id": item_id,
                        "elapsed_s": elapsed,
                        "error": error,
                    }
                )
                f.flush()
                print(
                    f"[{i}/{len(features)}] {idanpar} cloud_mask={cloud_mask} "
                    f"ndvi={ndvi} {elapsed}s {error}",
                    flush=True,
                )


def _bbox(geometry: dict) -> list[float]:
    polygons = (
        [geometry["coordinates"]]
        if geometry["type"] == "Polygon"
        else geometry["coordinates"]
    )
    points = [p for polygon in polygons for ring in polygon for p in ring]
    return [
        min(p[0] for p in points),
        min(p[1] for p in points),
        max(p[0] for p in points),
        max(p[1] for p in points),
    ]


def search_scenes(bbox: list[float], year: int, cloud_cover_max: float | None) -> list:
    """Sentinel-2 L2A items over bbox for June 1 - August 31 of year."""
    body: dict = {
        "collections": [CDSE_COLLECTION],
        "bbox": bbox,
        "datetime": f"{year}-06-01T00:00:00Z/{year}-08-31T23:59:59Z",
        "limit": 200,
    }
    if cloud_cover_max is not None:
        body["filter-lang"] = "cql2-json"
        body["filter"] = {
            "op": "<=",
            "args": [{"property": "eo:cloud_cover"}, cloud_cover_max],
        }
    request = urllib.request.Request(
        CDSE_STAC_SEARCH,
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        return json.load(response)["features"]


def count_scenes(parcels: Path, year: int, out: Path) -> None:
    """Write one row per parcel with its scene counts over the SOM form window."""
    features = json.loads(parcels.read_text())["features"]
    with out.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=SCENE_FIELDS)
        writer.writeheader()
        for i, feature in enumerate(features, start=1):
            bbox = _bbox(feature["geometry"])
            retained = search_scenes(bbox, year, CLOUD_COVER_MAX)
            every = search_scenes(bbox, year, None)
            covers = [item["properties"]["eo:cloud_cover"] for item in retained]
            row = {
                "idanpar": feature["properties"]["idanpar"],
                "retained_items": len(retained),
                "retained_dates": len(
                    {item["properties"]["datetime"][:10] for item in retained}
                ),
                "all_dates": len(
                    {item["properties"]["datetime"][:10] for item in every}
                ),
                "median_cloud_cover_retained": (
                    round(statistics.median(covers), 1) if covers else ""
                ),
                "tiles": " ".join(
                    sorted({item["properties"].get("grid:code", "") for item in every})
                ),
            }
            writer.writerow(row)
            print(
                f"[{i}/{len(features)}] {row['idanpar']}: "
                f"{row['retained_dates']}/{row['all_dates']} dates retained",
                flush=True,
            )


def summarize(csv_path: Path, scenes_path: Path | None = None) -> dict[str, float]:
    """Return NDVI difference statistics (masked - unmasked) per parcel."""
    values: dict[str, dict[str, float]] = {}
    with csv_path.open(newline="") as f:
        for row in csv.DictReader(f):
            if row["error"] or not row["ndvi_mean"]:
                continue
            ndvi = float(row["ndvi_mean"])
            if math.isfinite(ndvi):
                values.setdefault(row["idanpar"], {})[row["cloud_mask"]] = ndvi
    by_parcel = {
        idanpar: v["True"] - v["False"] for idanpar, v in values.items() if len(v) == 2
    }
    diffs = list(by_parcel.values())
    if not diffs:
        sys.exit("No parcel has both a masked and an unmasked NDVI.")
    summary: dict[str, float] = {
        "n_parcels": len(diffs),
        "mean_diff": statistics.mean(diffs),
        "mean_abs_diff": statistics.mean(abs(d) for d in diffs),
        "median_abs_diff": statistics.median(abs(d) for d in diffs),
        "max_abs_diff": max(abs(d) for d in diffs),
    }
    if scenes_path is None:
        return summary

    with scenes_path.open(newline="") as f:
        dates = {
            row["idanpar"]: int(row["retained_dates"]) for row in csv.DictReader(f)
        }
    counts = [dates[p] for p in by_parcel if p in dates]
    summary.update(
        {
            "retained_dates_min": min(counts),
            "retained_dates_median": statistics.median(counts),
            "retained_dates_max": max(counts),
        }
    )
    for label, keep in (
        (f"le{FEW_SCENES}", lambda n: n <= FEW_SCENES),
        (f"gt{FEW_SCENES}", lambda n: n > FEW_SCENES),
    ):
        group = [abs(d) for p, d in by_parcel.items() if p in dates and keep(dates[p])]
        summary[f"n_parcels_{label}_dates"] = len(group)
        if group:
            summary[f"mean_abs_diff_{label}_dates"] = statistics.mean(group)
            summary[f"max_abs_diff_{label}_dates"] = max(group)
    return summary


def parse_args() -> argparse.Namespace:
    """Parse the sample / run / scenes / summary subcommands."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)

    sample = sub.add_parser("sample", help="Pick the parcel sample.")
    sample.add_argument("--parquet", type=Path, required=True)
    sample.add_argument("--out", type=Path, required=True)
    sample.add_argument("--n", type=int, default=30)
    sample.add_argument("--seed", type=int, default=42)

    run = sub.add_parser("run", help="Call sentinel-fetch with and without mask.")
    run.add_argument("--base-url", required=True)
    run.add_argument("--parcels", type=Path, required=True)
    run.add_argument("--year", type=int, required=True)
    run.add_argument("--out", type=Path, required=True)

    scenes = sub.add_parser("scenes", help="Count Sentinel-2 scenes per parcel.")
    scenes.add_argument("--parcels", type=Path, required=True)
    scenes.add_argument("--year", type=int, required=True)
    scenes.add_argument("--out", type=Path, required=True)

    summary = sub.add_parser("summary", help="Summarize a comparison CSV.")
    summary.add_argument("--csv", type=Path, required=True)
    summary.add_argument("--scenes", type=Path)
    return parser.parse_args()


def main() -> None:
    """Dispatch the selected subcommand."""
    args = parse_args()
    if args.command == "sample":
        features = sample_parcels(args.parquet, args.n, args.seed)
        args.out.write_text(
            json.dumps({"type": "FeatureCollection", "features": features})
        )
        print(f"[OK] {len(features)} parcels → {args.out}")
    elif args.command == "run":
        run_comparison(args.base_url, args.parcels, args.year, args.out)
    elif args.command == "scenes":
        count_scenes(args.parcels, args.year, args.out)
    else:
        for key, value in summarize(args.csv, args.scenes).items():
            print(
                f"{key}: {value:.4f}" if isinstance(value, float) else f"{key}: {value}"
            )


if __name__ == "__main__":
    main()
