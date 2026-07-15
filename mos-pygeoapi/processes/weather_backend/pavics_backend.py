"""
PAVICS THREDDS OPeNDAP backend for the weather-timeseries process.

Provides the WeatherSource Protocol and PAVICSBackend implementation.
Data is accessed lazily via xarray + pydap (no API key required).
Results are cached in memory with a configurable TTL.
"""

from __future__ import annotations

import hashlib
import logging
import os
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Protocol, Tuple, runtime_checkable

import numpy as np
import pandas as pd
import requests
import xarray as xr
import yaml
from pydap.client import open_url as pydap_open_url
from pygeoapi.process.base import ProcessorExecuteError

from ..backend_utils import apply_variable_conversions
from ..cache_utils import TTLCache
from .models import (
    GeoJSONGeometry,
    WeatherTimeseriesFeature,
    WeatherTimeseriesProperties,
)

logger = logging.getLogger(__name__)

_DEFAULT_REGISTRY_PATH = (
    Path(__file__).resolve().parents[2] / "config" / "weather_datasets.yaml"
)
# ---------------------------------------------------------------------------
# WeatherSource Protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class WeatherSource(Protocol):
    """Interface that all weather data backends must satisfy."""

    def fetch(
        self,
        bbox: Tuple[float, float, float, float],
        variables: List[str],
        start_date: str,
        end_date: str,
        aggregation: str,
        dataset: str,
        polygon_geojson: Optional[Dict[str, Any]] = None,
    ) -> WeatherTimeseriesFeature:
        """Fetch weather timeseries for a spatial extent and time range.

        Args:
            bbox: (minx, miny, maxx, maxy) in EPSG:4326.
            variables: Canonical variable names (e.g. ["tasmin", "tasmax"]).
            start_date: ISO date string "YYYY-MM-DD".
            end_date: ISO date string "YYYY-MM-DD".
            aggregation: "daily" or "monthly".
            dataset: Dataset key from the registry (e.g. "era5_land").
            polygon_geojson: Optional GeoJSON Polygon for exact spatial clip.

        Returns:
            WeatherTimeseriesFeature (valid GeoJSON Feature).
        """
        ...


# ---------------------------------------------------------------------------
# In-memory TTL cache
# ---------------------------------------------------------------------------

_cache: TTLCache[WeatherTimeseriesFeature] = TTLCache(
    ttl=int(os.getenv("WEATHER_CACHE_TTL", "3600"))
)

# ---------------------------------------------------------------------------
# Cache key
# ---------------------------------------------------------------------------


def _make_cache_key(
    bbox: Tuple[float, float, float, float],
    variables: Tuple[str, ...],
    start_date: str,
    end_date: str,
    aggregation: str,
    dataset: str,
) -> str:
    """Return a stable SHA-256 hex digest for a set of query parameters."""
    raw = repr((bbox, variables, start_date, end_date, aggregation, dataset))
    return hashlib.sha256(raw.encode()).hexdigest()


# ---------------------------------------------------------------------------
# Dataset registry loader
# ---------------------------------------------------------------------------


def _load_dataset_registry(
    config_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Load the weather_datasets.yaml dataset registry.

    Args:
        config_path: Explicit file path. Falls back to the WEATHER_DATASETS_CONFIG
            environment variable, then the default relative path.

    Returns:
        Parsed YAML dict keyed by dataset name.

    Raises:
        ProcessorExecuteError: If the registry file cannot be read or parsed.
    """
    registry_path = Path(
        config_path or os.getenv("WEATHER_DATASETS_CONFIG", str(_DEFAULT_REGISTRY_PATH))
    )
    try:
        with registry_path.open("r", encoding="utf-8") as fh:
            registry = yaml.safe_load(fh)
    except FileNotFoundError as exc:
        raise ProcessorExecuteError(
            f"Weather dataset registry not found at {registry_path}: {exc}"
        ) from exc
    except yaml.YAMLError as exc:
        raise ProcessorExecuteError(
            f"Failed to parse weather dataset registry at {registry_path}: {exc}"
        ) from exc
    if not isinstance(registry, dict):
        raise ProcessorExecuteError(
            f"Weather dataset registry at {registry_path} must be a YAML mapping"
        )
    return registry


# ---------------------------------------------------------------------------
# Rolling date helper
# ---------------------------------------------------------------------------


def _apply_rolling_dates(registry: Dict[str, Any]) -> Dict[str, Any]:
    """Replace valid_time_range.end for rolling datasets with today minus lag.

    Datasets flagged with ``rolling: true`` receive a dynamically computed end
    date based on today's date minus ``rolling_lag_days`` (default 90).  This
    prevents the hardcoded ceiling from drifting behind the actual PAVICS
    archive as ERA5-Land is updated.

    Args:
        registry: Parsed weather_datasets.yaml dict (mutated in place).

    Returns:
        The same registry dict with updated end dates.
    """
    today = date.today()
    for dataset_config in registry.values():
        if dataset_config.get("rolling"):
            lag = int(dataset_config.get("rolling_lag_days", 90))
            end = today - timedelta(days=lag)
            dataset_config.setdefault("valid_time_range", {})["end"] = end.strftime(
                "%Y-%m-%d"
            )
    return registry


# ---------------------------------------------------------------------------
# PAVICSBackend
# ---------------------------------------------------------------------------


class PAVICSBackend:
    """Weather data backend using Ouranos PAVICS THREDDS via OPeNDAP + xarray."""

    DEFAULT_TDS_BASE_URL: str = "https://pavics.ouranos.ca/twitcher/ows/proxy/thredds"
    OPENDAP_PREFIX: str = "dodsC"
    ENGINE: str = "pydap"

    def __init__(
        self,
        tds_base_url: Optional[str] = None,
        registry: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Initialise the PAVICS backend.

        Args:
            tds_base_url: Override for PAVICS THREDDS base URL. Falls back to
                WEATHER_PAVICS_TDS_BASE_URL env var, then DEFAULT_TDS_BASE_URL.
            registry: Pre-loaded dataset registry dict (useful for testing).
                If None, the registry is loaded from weather_datasets.yaml.
        """
        url = (
            tds_base_url
            if tds_base_url is not None
            else os.getenv("WEATHER_PAVICS_TDS_BASE_URL", self.DEFAULT_TDS_BASE_URL)
        )
        self._tds_base_url: str = url.rstrip("/")
        self._registry: Dict[str, Any] = _apply_rolling_dates(
            registry if registry is not None else _load_dataset_registry()
        )

    # ------------------------------------------------------------------
    # Public (satisfies WeatherSource Protocol)
    # ------------------------------------------------------------------

    def fetch(
        self,
        bbox: Tuple[float, float, float, float],
        variables: List[str],
        start_date: str,
        end_date: str,
        aggregation: str,
        dataset: str,
        polygon_geojson: Optional[Dict[str, Any]] = None,
    ) -> WeatherTimeseriesFeature:
        """Fetch timeseries; returns cached result if already cached.

        Args:
            bbox: (minx, miny, maxx, maxy) in EPSG:4326.
            variables: Canonical variable names.
            start_date: ISO date string "YYYY-MM-DD".
            end_date: ISO date string "YYYY-MM-DD".
            aggregation: "daily" or "monthly".
            dataset: Dataset key from the registry.
            polygon_geojson: Optional GeoJSON Polygon for exact clip.

        Returns:
            WeatherTimeseriesFeature (GeoJSON Feature).

        Raises:
            ProcessorExecuteError: On unknown dataset, OPeNDAP failure, or
                out-of-range request.
        """
        cache_key: str = _make_cache_key(
            bbox, tuple(variables), start_date, end_date, aggregation, dataset
        )
        cached: Optional[WeatherTimeseriesFeature] = _cache.get(cache_key)
        if cached is not None:
            logger.debug("Cache hit for key %s…", cache_key[:12])
            return cached

        result: WeatherTimeseriesFeature = self._fetch_uncached(
            bbox=bbox,
            variables=variables,
            start_date=start_date,
            end_date=end_date,
            aggregation=aggregation,
            dataset=dataset,
            polygon_geojson=polygon_geojson,
        )
        _cache.set(cache_key, result)
        return result

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_dataset_config(self, dataset: str) -> Dict[str, Any]:
        """Return registry entry for dataset.

        Raises:
            ProcessorExecuteError: If dataset key is not in the registry.
        """
        config = self._registry.get(dataset)
        if config is None:
            available = sorted(self._registry.keys())
            raise ProcessorExecuteError(
                f"Unknown dataset {dataset!r}. " f"Available datasets: {available}"
            )
        return config

    def _build_opendap_url(self, dataset_config: Dict[str, Any]) -> str:
        """Construct the full OPeNDAP URL from base URL and dataset path."""
        return (
            f"{self._tds_base_url}/{self.OPENDAP_PREFIX}/"
            f"{dataset_config['opendap_path']}"
        )

    def _resolve_variable_names(
        self, variables: List[str], dataset_config: Dict[str, Any]
    ) -> Dict[str, str]:
        """Map canonical variable names to dataset-specific NetCDF names.

        Args:
            variables: Canonical names e.g. ["tasmin", "tasmax"].
            dataset_config: Registry entry for the dataset.

        Returns:
            Mapping canonical → netcdf_name.

        Raises:
            ProcessorExecuteError: If a variable is not defined for this dataset.
        """
        var_registry: Dict[str, Any] = dataset_config.get("variables", {})
        mapping: Dict[str, str] = {}
        for var in variables:
            if var not in var_registry:
                available = sorted(var_registry.keys())
                raise ProcessorExecuteError(
                    f"Variable {var!r} is not available in dataset "
                    f"{dataset_config.get('title', '?')!r}. "
                    f"Available: {available}"
                )
            mapping[var] = var_registry[var]["netcdf_name"]
        return mapping

    def _open_dataset(self, opendap_url: str, netcdf_vars: List[str]) -> xr.Dataset:
        """Open remote OPeNDAP dataset lazily with pydap engine.

        Args:
            opendap_url: Full OPeNDAP endpoint URL.
            netcdf_vars: NetCDF variable names to keep (others are dropped).

        Returns:
            xarray Dataset with only the requested variables loaded lazily.

        Raises:
            ProcessorExecuteError: If the dataset cannot be opened.
        """
        logger.debug("Opening OPeNDAP dataset: %s", opendap_url)
        try:
            # user_charset='utf-8' is required: PAVICS DAS metadata contains
            # non-ASCII characters (e.g. degree symbols) that pydap's default
            # ASCII codec cannot decode.
            session = requests.Session()
            store = pydap_open_url(opendap_url, session=session, user_charset="utf-8")
            ds = xr.open_dataset(xr.backends.PydapDataStore(store))
        except UnicodeDecodeError as exc:
            raise ProcessorExecuteError(
                f"Encoding error reading OPeNDAP metadata from {opendap_url}: {exc}"
            ) from exc
        except OSError as exc:
            raise ProcessorExecuteError(
                f"Failed to open OPeNDAP dataset at {opendap_url}: {exc}"
            ) from exc
        except Exception as exc:
            raise ProcessorExecuteError(
                f"Unexpected error opening OPeNDAP dataset: {exc}"
            ) from exc

        missing = [v for v in netcdf_vars if v not in ds.data_vars]
        if missing:
            raise ProcessorExecuteError(
                f"Variables {missing} not found in dataset. "
                f"Available: {sorted(ds.data_vars)}"
            )

        return ds[netcdf_vars]

    def _subset_spatial_rotated(
        self,
        ds: xr.Dataset,
        bbox: Tuple[float, float, float, float],
        lat_2d: str,
        lon_2d: str,
        rlat_dim: str,
        rlon_dim: str,
    ) -> xr.Dataset:
        """Spatially subset a rotated-pole dataset using 2D lat/lon masking.

        Regular .sel(rlat=slice(...)) selects on the rotated index, not on
        geographic coordinates. Instead, we use the 2D auxiliary lat/lon arrays
        to build a mask, find the bounding row/column indices in the rotated
        grid, and subset with .isel().

        Args:
            ds: Full (lazily loaded) xarray Dataset on a rotated-pole grid.
            bbox: (minx, miny, maxx, maxy) in EPSG:4326 geographic coordinates.
            lat_2d: Name of the 2D auxiliary latitude coordinate (e.g. "lat").
            lon_2d: Name of the 2D auxiliary longitude coordinate (e.g. "lon").
            rlat_dim: Name of the rotated-latitude index dimension.
            rlon_dim: Name of the rotated-longitude index dimension.

        Returns:
            Dataset subsetted to the smallest rotated-grid rectangle that
            contains the requested bounding box.

        Raises:
            ProcessorExecuteError: If no grid points fall within the bbox.
        """
        minx, miny, maxx, maxy = bbox
        lat = ds[lat_2d]
        lon = ds[lon_2d]
        mask = (lat >= miny) & (lat <= maxy) & (lon >= minx) & (lon <= maxx)

        rlat_any = mask.any(dim=rlon_dim).values
        rlon_any = mask.any(dim=rlat_dim).values

        rlat_idx = np.where(rlat_any)[0]
        rlon_idx = np.where(rlon_any)[0]

        if rlat_idx.size == 0 or rlon_idx.size == 0:
            raise ProcessorExecuteError(
                f"No grid points found within bbox {bbox} for rotated-pole dataset"
            )

        return ds.isel(
            {
                rlat_dim: slice(int(rlat_idx[0]), int(rlat_idx[-1]) + 1),
                rlon_dim: slice(int(rlon_idx[0]), int(rlon_idx[-1]) + 1),
            }
        )

    def _subset_spatial(
        self,
        ds: xr.Dataset,
        bbox: Tuple[float, float, float, float],
        polygon_geojson: Optional[Dict[str, Any]],
        lat_dim: str,
        lon_dim: str,
    ) -> xr.Dataset:
        """Spatially subset the dataset.

        Strategy:
        - point (minx == maxx, miny == maxy): nearest-neighbour .sel()
        - bbox / farm_id polygon: .sel() with slices, then optional rioxarray clip
        - polygon: bbox pre-filter followed by rioxarray polygon clip

        Args:
            ds: Full (lazily loaded) xarray Dataset.
            bbox: (minx, miny, maxx, maxy) in EPSG:4326.
            polygon_geojson: GeoJSON Polygon for exact clip (may be None).
            lat_dim: Name of latitude dimension in the dataset.
            lon_dim: Name of longitude dimension in the dataset.

        Returns:
            Spatially subsetted xarray Dataset.

        Raises:
            ProcessorExecuteError: If rioxarray is unavailable for polygon clip.
        """
        minx, miny, maxx, maxy = bbox

        if minx == maxx and miny == maxy:
            # Point query — nearest neighbour
            return ds.sel(
                {lat_dim: maxy, lon_dim: minx},
                method="nearest",
            )

        # BBox pre-filter
        ds = ds.sel(
            {
                lat_dim: slice(miny, maxy),
                lon_dim: slice(minx, maxx),
            }
        )

        if polygon_geojson is not None:
            try:
                import rioxarray  # noqa: F401 — activates ds.rio accessor
            except ImportError as exc:
                raise ProcessorExecuteError(
                    "rioxarray is required for polygon spatial clip but is not "
                    "installed. Install it via: pip install rioxarray"
                ) from exc
            try:
                ds = (
                    ds.rio.set_spatial_dims(x_dim=lon_dim, y_dim=lat_dim)
                    .rio.write_crs("EPSG:4326")
                    .rio.clip([polygon_geojson], crs="EPSG:4326", drop=True)
                )
            except Exception as exc:
                raise ProcessorExecuteError(
                    f"Polygon spatial clip failed: {exc}"
                ) from exc

        return ds

    def _subset_temporal(
        self, ds: xr.Dataset, start_date: str, end_date: str
    ) -> xr.Dataset:
        """Slice the time dimension.

        Args:
            ds: Spatially subsetted dataset.
            start_date: "YYYY-MM-DD".
            end_date: "YYYY-MM-DD".

        Returns:
            Temporally sliced dataset.
        """
        return ds.sel(time=slice(start_date, end_date))

    def _aggregate_monthly(self, ds: xr.Dataset) -> xr.Dataset:
        """Resample dataset to monthly means.

        Uses the pandas >= 2.2 'ME' (month-end) frequency alias.
        """
        return ds.resample(time="ME").mean()

    def _aggregate_spatial(
        self, ds: xr.Dataset, lat_dim: str, lon_dim: str
    ) -> xr.Dataset:
        """Compute spatial mean over lat/lon dimensions.

        For point queries the spatial dims no longer exist after .sel(),
        so this is effectively a no-op for those cases.

        Args:
            ds: Temporally (and optionally monthly) aggregated dataset.
            lat_dim: Name of latitude dimension.
            lon_dim: Name of longitude dimension.

        Returns:
            Dataset averaged over any remaining spatial dimensions.
        """
        spatial_dims = [d for d in [lat_dim, lon_dim] if d in ds.dims]
        if spatial_dims:
            return ds.mean(dim=spatial_dims)
        return ds

    def _build_geometry(
        self, bbox: Tuple[float, float, float, float]
    ) -> GeoJSONGeometry:
        """Construct a GeoJSON Polygon geometry from a bounding box.

        For a degenerate bbox (point query), returns a GeoJSON Point.

        Args:
            bbox: (minx, miny, maxx, maxy).

        Returns:
            GeoJSONGeometry (Polygon or Point).
        """
        minx, miny, maxx, maxy = bbox
        if minx == maxx and miny == maxy:
            return GeoJSONGeometry(type="Point", coordinates=[minx, miny])
        return GeoJSONGeometry(
            type="Polygon",
            coordinates=[
                [
                    [minx, miny],
                    [maxx, miny],
                    [maxx, maxy],
                    [minx, maxy],
                    [minx, miny],
                ]
            ],
        )

    def _build_result(
        self,
        ds: xr.Dataset,
        variables: List[str],
        canonical_to_netcdf: Dict[str, str],
        dataset_config: Dict[str, Any],
        bbox: Tuple[float, float, float, float],
        aggregation: str,
        dataset: str,
        start_date: str,
        end_date: str,
    ) -> WeatherTimeseriesFeature:
        """Serialise a loaded xarray Dataset into a WeatherTimeseriesFeature.

        Args:
            ds: Fully loaded (materialised) xarray Dataset.
            variables: Canonical variable names.
            canonical_to_netcdf: Mapping canonical → netcdf_name.
            dataset_config: Registry entry for the dataset.
            bbox: Original query bounding box.
            aggregation: "daily" or "monthly".
            dataset: Dataset key.
            start_date: Query start date.
            end_date: Query end date.

        Returns:
            WeatherTimeseriesFeature (valid GeoJSON Feature).
        """
        time_values: List[str] = (
            pd.DatetimeIndex(ds["time"].values).strftime("%Y-%m-%d").tolist()
        )

        var_registry: Dict[str, Any] = dataset_config.get("variables", {})
        var_values, units = apply_variable_conversions(
            ds, canonical_to_netcdf, var_registry
        )
        data: Dict[str, Any] = {"time": time_values, **var_values}

        geometry = self._build_geometry(bbox)
        properties = WeatherTimeseriesProperties(
            provider="pavics",
            dataset=dataset,
            variables=variables,
            aggregation=aggregation,
            temporal_extent=[start_date, end_date],
            data=data,
            units=units,
        )
        return WeatherTimeseriesFeature(geometry=geometry, properties=properties)

    def _fetch_uncached(
        self,
        bbox: Tuple[float, float, float, float],
        variables: List[str],
        start_date: str,
        end_date: str,
        aggregation: str,
        dataset: str,
        polygon_geojson: Optional[Dict[str, Any]],
    ) -> WeatherTimeseriesFeature:
        """Full fetch pipeline (cache miss path).

        Steps:
        1. Load dataset config from registry.
        2. Map canonical variable names to NetCDF names.
        3. Build OPeNDAP URL.
        4. Open dataset lazily.
        5. Subset spatially.
        6. Subset temporally.
        7. Aggregate monthly (if requested).
        8. Aggregate spatially (mean over lat/lon).
        9. Materialise data into memory.
        10. Build and return GeoJSON Feature.
        """
        dataset_config = self._get_dataset_config(dataset)
        valid_range = dataset_config.get("valid_time_range", {})
        range_end = valid_range.get("end")
        if range_end and end_date > range_end:
            raise ProcessorExecuteError(
                f"Requested end_date {end_date!r} exceeds the available data "
                f"range for dataset {dataset!r} (max: {range_end!r}). "
                "For ERA5-Land, data is available up to approximately 90 days "
                "before today."
            )
        canonical_to_netcdf = self._resolve_variable_names(
            variables=variables, dataset_config=dataset_config
        )
        opendap_url = self._build_opendap_url(dataset_config=dataset_config)
        lat_dim: str = dataset_config.get("lat_dim", "lat")
        lon_dim: str = dataset_config.get("lon_dim", "lon")

        netcdf_vars = list(canonical_to_netcdf.values())
        ds = self._open_dataset(opendap_url=opendap_url, netcdf_vars=netcdf_vars)

        if dataset_config.get("rotated_pole"):
            ds = self._subset_spatial_rotated(
                ds=ds,
                bbox=bbox,
                lat_2d=dataset_config.get("lat_2d_coord", "lat"),
                lon_2d=dataset_config.get("lon_2d_coord", "lon"),
                rlat_dim=lat_dim,
                rlon_dim=lon_dim,
            )
        else:
            ds = self._subset_spatial(
                ds=ds,
                bbox=bbox,
                polygon_geojson=polygon_geojson,
                lat_dim=lat_dim,
                lon_dim=lon_dim,
            )

        ds = self._subset_temporal(ds=ds, start_date=start_date, end_date=end_date)

        if aggregation == "monthly":
            ds = self._aggregate_monthly(ds)

        ds = self._aggregate_spatial(ds=ds, lat_dim=lat_dim, lon_dim=lon_dim)
        ds.load()  # materialise — data is now in memory

        return self._build_result(
            ds=ds,
            variables=variables,
            canonical_to_netcdf=canonical_to_netcdf,
            dataset_config=dataset_config,
            bbox=bbox,
            aggregation=aggregation,
            dataset=dataset,
            start_date=start_date,
            end_date=end_date,
        )
