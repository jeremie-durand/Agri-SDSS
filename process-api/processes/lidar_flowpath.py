"""
Quebec LiDAR flow paths and LS factor process (lidar-flowpath).

Fetches the MRNF LiDAR DTM over a field plus an upstream margin, resamples it
to 2 m in EPSG:32198, fills depressions, routes flow (MFD), and derives slope
and the RUSLE LS factor. The four layers are cropped to the field, written as
COGs and published to the ``lidar_flowpath`` STAC collection.

Algorithms: see processes/hydro_backend/terrain.py and
process-api/docs/LIDAR_FLOWPATH_SPECS.md.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import tempfile
import time
from typing import Any, NoReturn

import numpy as np
import rasterio
import rasterio.shutil
from numpy.typing import NDArray
from pygeoapi.process.base import ProcessorExecuteError
from rasterio.io import MemoryFile
from rasterio.transform import Affine
from rasterio.warp import transform_bounds
from shapely.geometry import box, mapping, shape
from shapely.geometry.base import BaseGeometry

from agri_i18n import _

from .asset_url_utils import cog_href
from .backend_utils import LocationType
from .hydro_backend import (
    fill_depressions,
    horn_slope_percent,
    ls_factor,
    mfd_specific_catchment_area,
)
from .hydro_backend.field_grid import (
    GEOGRAPHIC_CRS,
    GRID_CRS,
    Bounds,
    crop_slices,
    field_summary,
    grid_shape,
    grid_transform,
    inside_mask,
    prepare_zones,
    snap_outwards,
    to_grid_crs,
    widen,
    zone_summaries,
)
from .hydro_backend.models import FlowpathInputs
from .hydro_backend.terrain import (
    DEFAULT_FILL_EPSILON_M,
    DEFAULT_SCA_CAP_M,
    FREEMAN_EXPONENT,
)
from .lidar_backend.quebec_lidar_tile_index import LidarTileIndex
from .lidar_flowpath_metadata import PROCESS_METADATA
from .quebec_lidar_fetch import LidarFetchProcessor
from .spatial_backend import parse_inputs, prepare_geometry

logger = logging.getLogger(__name__)

LayerArrays = dict[str, NDArray[np.float64]]


class LidarFlowpathProcessor(LidarFetchProcessor):
    """Processor for field-scale flow paths and LS from the MRNF LiDAR DTM."""

    STAC_COLLECTION_ID: str = "lidar_flowpath"
    STAC_COLLECTION_TITLE: str = "Quebec LiDAR Flow Paths and LS Factor"
    STAC_COLLECTION_DESCRIPTION: str = (
        "Field-scale flow-path layers computed from the Quebec MRNF LiDAR DTM "
        "at 2 m in EPSG:32198: filled DTM, specific catchment area (MFD), "
        "slope in percent and the RUSLE LS factor, clipped to each field."
    )
    STAC_PROJ_CODE: str = GRID_CRS
    ITEM_ID_PREFIX: str = "lidar_flowpath"
    PROCESS_METADATA_DEF: dict[str, Any] = PROCESS_METADATA

    MAX_FIELD_AREA_KM2: float = 5.0
    # Field bbox plus margin at 2 m; about the benchmarked worst case (4.49 M
    # cells, 706 MB). A thin field passes the area cap but not this one.
    MAX_GRID_CELLS: int = 4_500_000
    RESOLUTION_M: float = 2.0
    RESAMPLING: str = "average"
    # Bump whenever the output values change, so cached COGs are not served.
    ALGORITHM_VERSION: int = 1
    LAYERS: tuple[str, ...] = ("filled_dtm", "sca", "slope", "ls")
    SHEETS_PROPERTY: str = "agri_sdss:sheets"
    SOURCE_DATASET: str = "Produits dérivés de base du LiDAR (MRNF)"
    SOURCE_URL: str = (
        "https://www.donneesquebec.ca/recherche/dataset/"
        "produits-derives-de-base-du-lidar"
    )
    MNT_SHEET_PATTERN: re.Pattern[str] = re.compile(r"MNT_([^/]+)\.tif$")

    LAYER_TITLES: dict[str, str] = {
        "filled_dtm": "Filled DTM (depressions filled)",
        "sca": "Specific catchment area (MFD)",
        "slope": "Slope (percent)",
        "ls": "RUSLE LS factor",
    }
    LAYER_UNITS: dict[str, str] = {"filled_dtm": "m", "sca": "m", "slope": "%"}
    LAYER_DESCRIPTIONS: dict[str, str] = {
        "filled_dtm": "2 m DTM with closed depressions filled (Priority-Flood+e)",
        "sca": "Upslope area per unit contour width, Freeman MFD (m2/m)",
        "slope": "Horn slope of the unfilled 2 m DTM, rise / run x 100",
        "ls": "Moore & Burch LS, specific catchment area capped at 300 m",
    }

    # ------------------------------------------------------------------
    # Public entrypoint
    # ------------------------------------------------------------------

    def execute(
        self, data: dict[str, Any], outputs: Any | None = None
    ) -> tuple[str, dict[str, Any]]:
        """Compute (or reuse) the flow-path layers of one field.

        Returns:
            Tuple of (mimetype, result dict).
        """
        deadline = time.monotonic() + self.PROCESS_TIME_BUDGET_SECONDS
        try:
            inputs = parse_inputs(FlowpathInputs, data)
            field_geojson = self._field_geometry(inputs)
            field = to_grid_crs(field_geojson).buffer(0)
            field_bounds = snap_outwards(field.bounds, self.RESOLUTION_M)
            self._check_area(field_bounds)

            margin = inputs.upstream_margin_m
            margin_bounds = snap_outwards(
                widen(field_bounds, margin), self.RESOLUTION_M
            )
            self._check_grid(margin_bounds)
            zones = (
                prepare_zones(inputs.zones, field) if inputs.zones is not None else None
            )
            identifier = self._field_identifier(inputs, field_geojson)
            cog_paths = {
                layer: os.path.join(
                    self.output_dir, f"{self._file_stem(layer, identifier, margin)}.tif"
                )
                for layer in self.LAYERS
            }

            all_cached = all(os.path.exists(path) for path in cog_paths.values())
            sheets = self._cached_sheets(cog_paths) if all_cached else None
            if sheets is None:
                tile_urls = self._dtm_tile_urls(margin_bounds, field_geojson)
                sheets = self._sheet_ids(tile_urls)
                if not all_cached:
                    self._build_layers(
                        tile_urls,
                        cog_paths,
                        field,
                        field_geojson,
                        field_bounds,
                        margin_bounds,
                        deadline,
                    )
            else:
                logger.info("Cache hit: reusing flow-path layers for %s", identifier)

            layers, transform = self._read_layers(cog_paths)
            field_pixels = inside_mask(field, transform, layers["ls"].shape) & (
                np.isfinite(layers["ls"])
            )
            summary = field_summary(field_pixels, layers["slope"], layers["ls"])
            if zones is not None:
                summary["zones"] = zone_summaries(
                    zones,
                    field_pixels,
                    transform,
                    layers["slope"],
                    layers["ls"],
                    self.RESOLUTION_M,
                )

            bbox = shape(field_geojson).bounds
            assets: dict[str, dict[str, Any]] = {}
            stac_items: list[str] = []
            for layer in self.LAYERS:
                values = layers[layer][field_pixels]
                mean = float(values.mean()) if values.size else None
                assets[layer], item_id = self._layer_asset(
                    layer, cog_paths[layer], mean, field_geojson, bbox, sheets
                )
                stac_items.append(item_id)

            return "application/json", {
                "stac_items": stac_items,
                "assets": assets,
                "bbox": list(bbox),
                "summary": summary,
                "parameters": self._parameters(margin),
                "source": {
                    "dataset": self.SOURCE_DATASET,
                    "url": self.SOURCE_URL,
                    "sheets": sheets,
                },
            }

        except ProcessorExecuteError:
            raise
        except Exception as exc:
            logger.error(
                "Unexpected error in LidarFlowpathProcessor: %s", exc, exc_info=True
            )
            raise ProcessorExecuteError(
                _("An unexpected error occurred while running this process.")
            ) from exc

    # ------------------------------------------------------------------
    # Inputs, identity and limits
    # ------------------------------------------------------------------

    @staticmethod
    def _field_geometry(inputs: FlowpathInputs) -> dict[str, Any]:
        """Return the field as a valid polygonal GeoJSON geometry in EPSG:4326."""
        if inputs.location_type == LocationType.BBOX:
            return mapping(box(*inputs.bbox))  # type: ignore[misc]
        return prepare_geometry(inputs)  # type: ignore[arg-type]

    @staticmethod
    def _field_identifier(inputs: FlowpathInputs, field_geojson: dict[str, Any]) -> str:
        """Return ``farm_<id>``, or a hash of the exact field geometry."""
        if inputs.location_type == LocationType.FARM_ID:
            return f"farm_{int(inputs.farm_id)}"  # type: ignore[arg-type]
        digest = hashlib.md5(shape(field_geojson).wkb).hexdigest()[:16]
        return f"geom_{digest}"

    def _file_stem(self, layer: str, identifier: str, margin: int) -> str:
        return (
            f"{self.ITEM_ID_PREFIX}_{layer}_{identifier}"
            f"_m{margin}_v{self.ALGORITHM_VERSION}"
        )

    def _check_area(self, field_bounds: Bounds) -> None:
        west, south, east, north = field_bounds
        area_km2 = (east - west) * (north - south) / 1_000_000
        if area_km2 > self.MAX_FIELD_AREA_KM2:
            raise ProcessorExecuteError(
                _(
                    "Farm area ({area} km²) exceeds maximum allowed ({maximum} km²)"
                ).format(area=f"{area_km2:.1f}", maximum=self.MAX_FIELD_AREA_KM2)
            )

    def _check_grid(self, margin_bounds: Bounds) -> None:
        rows, cols = grid_shape(margin_bounds, self.RESOLUTION_M)
        if rows * cols > self.MAX_GRID_CELLS:
            raise ProcessorExecuteError(
                _(
                    "The field and its upstream margin cover {cells} million cells "
                    "at 2 m, above the limit of {maximum} million. Reduce "
                    "'upstream_margin_m' or split the field."
                ).format(
                    cells=f"{rows * cols / 1e6:.1f}",
                    maximum=f"{self.MAX_GRID_CELLS / 1e6:.1f}",
                )
            )

    def _parameters(self, margin: int) -> dict[str, Any]:
        return {
            "upstream_margin_m": margin,
            "resolution_m": self.RESOLUTION_M,
            "crs": GRID_CRS,
            "resampling": self.RESAMPLING,
            "sca_cap_m": DEFAULT_SCA_CAP_M,
            "mfd_exponent": FREEMAN_EXPONENT,
            "fill_epsilon_m": DEFAULT_FILL_EPSILON_M,
            "algorithm_version": self.ALGORITHM_VERSION,
        }

    # ------------------------------------------------------------------
    # Tiles and sheets
    # ------------------------------------------------------------------

    def _dtm_tile_urls(
        self, margin_bounds: Bounds, field_geojson: dict[str, Any]
    ) -> list[str]:
        """Return the MRNF DTM tile URLs covering the margin bounds.

        Raises:
            ProcessorExecuteError: When no DTM tile covers the area.
        """
        lookup_bbox = transform_bounds(GRID_CRS, GEOGRAPHIC_CRS, *margin_bounds)
        urls = LidarTileIndex().get_tile_urls(lookup_bbox, ["dtm"]).get("dtm", [])
        if not urls:
            self._raise_no_coverage(field_geojson)
        return urls

    @staticmethod
    def _raise_no_coverage(field_geojson: dict[str, Any]) -> NoReturn:
        raise ProcessorExecuteError(
            _(
                "No LiDAR tiles found for the supplied geometry "
                "(bbox={bbox}). The area may not be covered by MRNF "
                "LiDAR data."
            ).format(bbox=shape(field_geojson).bounds)
        )

    @classmethod
    def _sheet_ids(cls, tile_urls: list[str]) -> list[str]:
        """Return the sorted MRNF ``Feuillet20K`` ids named in the DTM URLs."""
        sheets = {
            match.group(1)
            for url in tile_urls
            if (match := cls.MNT_SHEET_PATTERN.search(url)) is not None
        }
        return sorted(sheets)

    def _cached_sheets(self, cog_paths: dict[str, str]) -> list[str] | None:
        """Return the sheets recorded with the published items, if any."""
        for layer in self.LAYERS:
            item = self._load_cached_stac_item(self._stac_marker_path(cog_paths[layer]))
            sheets = (item or {}).get("properties", {}).get(self.SHEETS_PROPERTY)
            if isinstance(sheets, list):
                return sheets
        return None

    # ------------------------------------------------------------------
    # Layer computation and COG I/O
    # ------------------------------------------------------------------

    def _build_layers(
        self,
        tile_urls: list[str],
        cog_paths: dict[str, str],
        field: BaseGeometry,
        field_geojson: dict[str, Any],
        field_bounds: Bounds,
        margin_bounds: Bounds,
        deadline: float,
    ) -> None:
        """Warp the DTM, run the hydrology and write the four field COGs."""
        with tempfile.TemporaryDirectory(prefix="lidar_flowpath_") as workdir:
            warp_path = os.path.join(workdir, "dtm_2m.tif")
            self._warp_dtm(tile_urls, warp_path, margin_bounds, deadline)
            with rasterio.open(warp_path) as src:
                dem = src.read(1).astype(np.float64)
                nodata = src.nodata

        nodata_mask = ~np.isfinite(dem)
        if nodata is not None:
            nodata_mask |= dem == nodata

        rows, cols = crop_slices(margin_bounds, field_bounds, self.RESOLUTION_M)
        field_transform = grid_transform(field_bounds, self.RESOLUTION_M)
        inside = inside_mask(
            field, field_transform, grid_shape(field_bounds, self.RESOLUTION_M)
        )
        if not (inside & ~nodata_mask[rows, cols]).any():
            self._raise_no_coverage(field_geojson)
        if time.monotonic() > deadline:
            logger.error(
                "Flow-path computation stopped: time budget of %s s exhausted",
                self.PROCESS_TIME_BUDGET_SECONDS,
            )
            raise ProcessorExecuteError(
                _(
                    "LiDAR processing exceeded the time limit of {seconds} seconds. "
                    "Try a smaller area or fewer products."
                ).format(seconds=self.PROCESS_TIME_BUDGET_SECONDS)
            )

        logger.info(
            "Computing flow-path layers on a %d x %d grid", dem.shape[0], dem.shape[1]
        )
        filled = fill_depressions(dem, nodata_mask)
        sca = mfd_specific_catchment_area(filled, self.RESOLUTION_M)
        slope = horn_slope_percent(dem, self.RESOLUTION_M, nodata_mask)
        arrays: LayerArrays = {
            "filled_dtm": filled,
            "sca": sca,
            "slope": slope,
            "ls": ls_factor(sca, slope),
        }

        for layer, array in arrays.items():
            cropped = array[rows, cols]
            masked = np.where(
                inside & np.isfinite(cropped), cropped, self.DEFAULT_NODATA
            ).astype(np.float32)
            self._get_or_build_cog(
                cog_paths[layer],
                layer,
                lambda output_path, values=masked: self._write_cog(
                    values, field_transform, output_path
                ),
            )

    def _warp_dtm(
        self,
        tile_urls: list[str],
        output_path: str,
        margin_bounds: Bounds,
        deadline: float,
    ) -> None:
        """Mosaic and average the 1 m MNT tiles onto the 2 m EPSG:32198 grid."""
        resolution = str(self.RESOLUTION_M)
        cmd: list[str] = [
            "gdalwarp",
            "-t_srs",
            GRID_CRS,
            "-tr",
            resolution,
            resolution,
            "-te",
            *(str(value) for value in margin_bounds),
            "-r",
            self.RESAMPLING,
            "-dstnodata",
            str(self.DEFAULT_NODATA),
            "-of",
            "GTiff",
            "-overwrite",
            *(f"/vsicurl/{url}" for url in tile_urls),
            output_path,
        ]
        result = self._run_gdal(cmd, deadline)
        if result.returncode != 0:
            logger.error("gdalwarp flow-path DTM warp failed: %s", result.stderr)
            raise ProcessorExecuteError(
                _("Could not prepare the terrain model for the flow-path computation.")
            )

    def _write_cog(
        self, values: NDArray[np.float32], transform: Affine, output_path: str
    ) -> None:
        profile = {
            "driver": "GTiff",
            "height": values.shape[0],
            "width": values.shape[1],
            "count": 1,
            "dtype": "float32",
            "crs": GRID_CRS,
            "transform": transform,
            "nodata": self.DEFAULT_NODATA,
        }
        with MemoryFile() as memfile:
            with memfile.open(**profile) as dataset:
                dataset.write(values, 1)
            with memfile.open() as dataset:
                rasterio.shutil.copy(
                    dataset,
                    output_path,
                    driver="COG",
                    COMPRESS=self.COG_COMPRESSION,
                    BLOCKSIZE=self.COG_BLOCKSIZE,
                    OVERVIEWS=self.COG_OVERVIEWS,
                    OVERVIEW_RESAMPLING=self.COG_OVERVIEW_RESAMPLING,
                )

    def _read_layers(self, cog_paths: dict[str, str]) -> tuple[LayerArrays, Affine]:
        """Read the four COGs back as float64 arrays with NaN for nodata."""
        layers: LayerArrays = {}
        transform: Affine | None = None
        for layer, path in cog_paths.items():
            with rasterio.open(path) as src:
                band = src.read(1, masked=True)
                transform = src.transform
            layers[layer] = band.astype(np.float64).filled(np.nan)
        return layers, transform  # type: ignore[return-value]

    # ------------------------------------------------------------------
    # STAC
    # ------------------------------------------------------------------

    def _layer_asset(
        self,
        layer: str,
        cog_path: str,
        mean: float | None,
        field_geojson: dict[str, Any],
        bbox: tuple[float, float, float, float],
        sheets: list[str],
    ) -> tuple[dict[str, Any], str]:
        """Return the result asset for one layer and its published STAC item id.

        The item is (re)published unless a marker from a previous publish of
        the same COG, asset set and sheets exists.
        """
        band: dict[str, Any] = {
            "name": layer,
            "data_type": "float32",
            "nodata": self.DEFAULT_NODATA,
            "description": self.LAYER_DESCRIPTIONS[layer],
        }
        if layer in self.LAYER_UNITS:
            band["unit"] = self.LAYER_UNITS[layer]
        if mean is not None:
            band["statistics"] = {"mean": mean}
        asset: dict[str, Any] = {
            "href": cog_href(cog_path),
            "type": "image/tiff; application=geotiff; profile=cloud-optimized",
            "roles": ["data"],
            "title": self.LAYER_TITLES[layer],
            "bands": [band],
        }

        marker_path = self._stac_marker_path(cog_path)
        item = self._load_cached_stac_item(marker_path)
        expected_assets = {layer, self.PREVIEW_ASSET_KEY, self.TILEJSON_ASSET_KEY}
        if (
            item is None
            or set(item.get("assets", {})) != expected_assets
            or item.get("properties", {}).get(self.SHEETS_PROPERTY) != sheets
        ):
            item = self._create_stac_item(
                item_id=os.path.splitext(os.path.basename(cog_path))[0],
                geometry=field_geojson,
                bbox=bbox,
                product=layer,
                asset=asset,
                cog_path=cog_path,
                marker_path=marker_path,
                extra_properties={self.SHEETS_PROPERTY: sheets},
            )

        rendered = item["assets"]
        return (
            {
                **asset,
                self.PREVIEW_ASSET_KEY: rendered[self.PREVIEW_ASSET_KEY]["href"],
                self.TILEJSON_ASSET_KEY: rendered[self.TILEJSON_ASSET_KEY]["href"],
            },
            item["id"],
        )
