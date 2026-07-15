"""
PAVICS THREDDS OPeNDAP backend for CMIP6 climate projection data.

Provides CMIPBackend for the climate-timeseries and climate-indicators processes.
Datasets are accessed lazily via xarray + pydap (no API key required).
Results are cached in memory with a configurable TTL.
"""

from __future__ import annotations

import hashlib
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

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
    ClimateTimeseriesFeature,
    ClimateTimeseriesProperties,
    GeoJSONGeometry,
)

logger = logging.getLogger(__name__)

_DEFAULT_REGISTRY_PATH = (
    Path(__file__).resolve().parents[2] / "config" / "climate_datasets.yaml"
)

# ---------------------------------------------------------------------------
# In-memory TTL cache
# ---------------------------------------------------------------------------

_cache: TTLCache[ClimateTimeseriesFeature] = TTLCache(
    ttl=int(os.getenv("CLIMATE_CACHE_TTL", "3600"))
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
    scenario: str,
    model: str,
) -> str:
    """Return a stable SHA-256 hex digest for a set of query parameters."""
    raw = repr(
        (bbox, variables, start_date, end_date, aggregation, dataset, scenario, model)
    )
    return hashlib.sha256(raw.encode()).hexdigest()


# ---------------------------------------------------------------------------
# Dataset registry loader
# ---------------------------------------------------------------------------


def _load_dataset_registry(
    config_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Load the climate_datasets.yaml dataset registry.

    Args:
        config_path: Explicit file path. Falls back to CLIMATE_DATASETS_CONFIG
            environment variable, then the default relative path.

    Returns:
        Parsed YAML dict keyed by dataset name.

    Raises:
        ProcessorExecuteError: If the registry file cannot be read or parsed.
    """
    registry_path = Path(
        config_path or os.getenv("CLIMATE_DATASETS_CONFIG", str(_DEFAULT_REGISTRY_PATH))
    )
    try:
        with registry_path.open("r", encoding="utf-8") as fh:
            registry = yaml.safe_load(fh)
    except FileNotFoundError as exc:
        raise ProcessorExecuteError(
            f"Climate dataset registry not found at {registry_path}: {exc}"
        ) from exc
    except yaml.YAMLError as exc:
        raise ProcessorExecuteError(
            f"Failed to parse climate dataset registry at {registry_path}: {exc}"
        ) from exc
    if not isinstance(registry, dict):
        raise ProcessorExecuteError(
            f"Climate dataset registry at {registry_path} must be a YAML mapping"
        )
    return registry


# ---------------------------------------------------------------------------
# CMIPBackend
# ---------------------------------------------------------------------------


class CMIPBackend:
    """CMIP6 climate projection backend using PAVICS THREDDS via OPeNDAP + xarray."""

    DEFAULT_TDS_BASE_URL: str = "https://pavics.ouranos.ca/twitcher/ows/proxy/thredds"
    OPENDAP_PREFIX: str = "dodsC"

    def __init__(
        self,
        tds_base_url: Optional[str] = None,
        registry: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Initialise the CMIP backend.

        Args:
            tds_base_url: Override for PAVICS THREDDS base URL. Falls back to
                CLIMATE_PAVICS_TDS_BASE_URL env var, then DEFAULT_TDS_BASE_URL.
            registry: Pre-loaded dataset registry dict (useful for testing).
                If None, the registry is loaded from climate_datasets.yaml.
        """
        url = (
            tds_base_url
            if tds_base_url is not None
            else os.getenv("CLIMATE_PAVICS_TDS_BASE_URL", self.DEFAULT_TDS_BASE_URL)
        )
        self._tds_base_url: str = url.rstrip("/")
        self._registry: Dict[str, Any] = (
            registry if registry is not None else _load_dataset_registry()
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def fetch(
        self,
        bbox: Tuple[float, float, float, float],
        variables: List[str],
        start_date: str,
        end_date: str,
        aggregation: str,
        dataset: str,
        scenario: str,
        model: str,
        polygon_geojson: Optional[Dict[str, Any]] = None,
    ) -> ClimateTimeseriesFeature:
        """Fetch CMIP6 timeseries; returns cached result if already cached.

        Args:
            bbox: (minx, miny, maxx, maxy) in EPSG:4326.
            variables: Canonical variable names (e.g. ["tasmin", "tasmax"]).
            start_date: ISO date string "YYYY-MM-DD".
            end_date: ISO date string "YYYY-MM-DD".
            aggregation: "daily" or "monthly".
            dataset: Dataset key from the registry (e.g. "cmip6_espo_g6_r2").
            scenario: Emissions scenario ("ssp245", "ssp370", "ssp585").
            model: CMIP6 model name (e.g. "MPI-ESM1-2-LR").
            polygon_geojson: Optional GeoJSON Polygon for exact spatial clip.

        Returns:
            ClimateTimeseriesFeature (GeoJSON Feature).

        Raises:
            ProcessorExecuteError: On unknown dataset/model/scenario,
                OPeNDAP failure, or out-of-range request.
        """
        cache_key: str = _make_cache_key(
            bbox,
            tuple(variables),
            start_date,
            end_date,
            aggregation,
            dataset,
            scenario,
            model,
        )
        cached: Optional[ClimateTimeseriesFeature] = _cache.get(cache_key)
        if cached is not None:
            logger.debug("Cache hit for key %s…", cache_key[:12])
            return cached

        result: ClimateTimeseriesFeature = self._fetch_uncached(
            bbox=bbox,
            variables=variables,
            start_date=start_date,
            end_date=end_date,
            aggregation=aggregation,
            dataset=dataset,
            scenario=scenario,
            model=model,
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
                f"Unknown dataset {dataset!r}. Available datasets: {available}"
            )
        return config

    @staticmethod
    def _get_model_config(
        dataset_config: Dict[str, Any], model: str, scenario: str
    ) -> Dict[str, Any]:
        """Validate model + scenario and return per-model metadata.

        Args:
            dataset_config: Top-level registry entry.
            model: CMIP6 model name.
            scenario: Emissions scenario.

        Returns:
            Per-model metadata dict (institution, member_id, date_range, ...).

        Raises:
            ProcessorExecuteError: If model or scenario is not supported.
        """
        models: Dict[str, Any] = dataset_config.get("models", {})
        if model not in models:
            available = sorted(models.keys())
            raise ProcessorExecuteError(
                f"Unknown model {model!r}. Available models: {available}"
            )
        model_meta = models[model]

        # Per-model scenario override takes priority over dataset-level list
        supported = model_meta.get(
            "supported_scenarios", dataset_config.get("supported_scenarios", [])
        )
        if scenario not in supported:
            raise ProcessorExecuteError(
                f"Scenario {scenario!r} is not available for model {model!r}. "
                f"Supported: {supported}"
            )
        return model_meta

    def _build_opendap_url(
        self,
        dataset_config: Dict[str, Any],
        model_config: Dict[str, Any],
        model: str,
        scenario: str,
    ) -> str:
        """Construct the full OPeNDAP URL from template fields.

        Args:
            dataset_config: Top-level registry entry.
            model_config: Per-model metadata dict.
            model: CMIP6 model name.
            scenario: Emissions scenario.

        Returns:
            Full OPeNDAP URL string.
        """
        filename = dataset_config["filename_template"].format(
            institution=model_config["institution"],
            model=model.value if hasattr(model, "value") else model,
            scenario=scenario.value if hasattr(scenario, "value") else scenario,
            member_id=model_config["member_id"],
            date_range=model_config["date_range"],
        )
        catalog_path = dataset_config["catalog_path"].rstrip("/")
        return f"{self._tds_base_url}/{self.OPENDAP_PREFIX}/{catalog_path}/{filename}"

    def _resolve_variable_names(
        self, variables: List[str], dataset_config: Dict[str, Any]
    ) -> Dict[str, str]:
        """Map canonical variable names to dataset-specific NetCDF names.

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
            netcdf_vars: NetCDF variable names to keep.

        Returns:
            xarray Dataset with only the requested variables loaded lazily.

        Raises:
            ProcessorExecuteError: If the dataset cannot be opened.
        """
        logger.debug("Opening OPeNDAP dataset: %s", opendap_url)
        try:
            # user_charset='utf-8' required: PAVICS DAS metadata may contain
            # non-ASCII characters that pydap's default ASCII codec cannot decode.
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
        """Subset a rotated-pole grid using 2D lat/lon auxiliary coordinates.

        Builds a geographic mask over the 2D lat/lon arrays and selects the
        bounding rectangular index range in rotated-pole space.
        """
        minx, miny, maxx, maxy = bbox
        lat = ds[lat_2d]
        lon = ds[lon_2d]
        mask = (lat >= miny) & (lat <= maxy) & (lon >= minx) & (lon <= maxx)
        rlat_idx = np.where(mask.any(dim=rlon_dim))[0]
        rlon_idx = np.where(mask.any(dim=rlat_dim))[0]
        if rlat_idx.size == 0 or rlon_idx.size == 0:
            raise ProcessorExecuteError(
                f"No data found within bbox {bbox} — check that the bbox "
                "intersects the dataset domain."
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
        lat_2d: Optional[str] = None,
        lon_2d: Optional[str] = None,
    ) -> xr.Dataset:
        """Spatially subset the dataset.

        Delegates to rotated-pole subsetting when lat_2d/lon_2d are provided
        (dimensions are rotated-pole index coords, not geographic). Otherwise
        uses numpy-index-based isel on 1-D geographic coordinates.
        """
        minx, miny, maxx, maxy = bbox

        if lat_2d is not None and lon_2d is not None:
            ds = self._subset_spatial_rotated(
                ds, bbox, lat_2d, lon_2d, lat_dim, lon_dim
            )
        else:
            lat_vals = ds[lat_dim].values
            lon_vals = ds[lon_dim].values

            if minx == maxx and miny == maxy:
                lat_idx = int(np.argmin(np.abs(lat_vals - maxy)))
                lon_idx = int(np.argmin(np.abs(lon_vals - minx)))
                return ds.isel({lat_dim: lat_idx, lon_dim: lon_idx})

            lat_indices = np.where((lat_vals >= miny) & (lat_vals <= maxy))[0]
            lon_indices = np.where((lon_vals >= minx) & (lon_vals <= maxx))[0]

            if lat_indices.size == 0 or lon_indices.size == 0:
                raise ProcessorExecuteError(
                    f"No data found within bbox {bbox} — check that the bbox "
                    "intersects the dataset domain."
                )
            ds = ds.isel({lat_dim: lat_indices, lon_dim: lon_indices})

        if polygon_geojson is not None:
            try:
                import rioxarray  # noqa: F401
            except ImportError as exc:
                raise ProcessorExecuteError(
                    "rioxarray is required for polygon spatial clip but is not installed."
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
        """Slice the time dimension."""
        return ds.sel(time=slice(start_date, end_date))

    def _aggregate_monthly(self, ds: xr.Dataset) -> xr.Dataset:
        """Resample dataset to monthly means (pandas >= 2.2 'ME' alias)."""
        return ds.resample(time="ME").mean()

    def _aggregate_spatial(
        self, ds: xr.Dataset, lat_dim: str, lon_dim: str
    ) -> xr.Dataset:
        """Compute spatial mean over lat/lon dimensions."""
        spatial_dims = [d for d in [lat_dim, lon_dim] if d in ds.dims]
        if spatial_dims:
            return ds.mean(dim=spatial_dims)
        return ds

    def _build_geometry(
        self, bbox: Tuple[float, float, float, float]
    ) -> GeoJSONGeometry:
        """Construct a GeoJSON Polygon or Point geometry from a bounding box."""
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
        scenario: str,
        model: str,
        start_date: str,
        end_date: str,
    ) -> ClimateTimeseriesFeature:
        """Serialise a loaded xarray Dataset into a ClimateTimeseriesFeature."""
        raw_time = ds["time"].values
        # cftime objects (e.g. noleap calendar) are not directly convertible
        # via pd.DatetimeIndex — use xarray's built-in conversion instead.
        try:
            time_values: List[str] = (
                pd.DatetimeIndex(raw_time).strftime("%Y-%m-%d").tolist()
            )
        except Exception:
            time_values = [str(t)[:10] for t in ds["time"].to_index()]

        var_registry: Dict[str, Any] = dataset_config.get("variables", {})
        var_values, units = apply_variable_conversions(
            ds, canonical_to_netcdf, var_registry
        )
        data: Dict[str, Any] = {"time": time_values, **var_values}

        geometry = self._build_geometry(bbox)
        properties = ClimateTimeseriesProperties(
            provider="pavics",
            dataset=dataset,
            scenario=scenario,
            model=model,
            variables=variables,
            aggregation=aggregation,
            temporal_extent=[start_date, end_date],
            data=data,
            units=units,
        )
        return ClimateTimeseriesFeature(geometry=geometry, properties=properties)

    def _fetch_uncached(
        self,
        bbox: Tuple[float, float, float, float],
        variables: List[str],
        start_date: str,
        end_date: str,
        aggregation: str,
        dataset: str,
        scenario: str,
        model: str,
        polygon_geojson: Optional[Dict[str, Any]],
    ) -> ClimateTimeseriesFeature:
        """Full fetch pipeline (cache miss path)."""
        dataset_config = self._get_dataset_config(dataset)
        model_config = self._get_model_config(
            dataset_config=dataset_config, model=model, scenario=scenario
        )
        canonical_to_netcdf = self._resolve_variable_names(
            variables=variables, dataset_config=dataset_config
        )
        opendap_url = self._build_opendap_url(
            dataset_config=dataset_config,
            model_config=model_config,
            model=model,
            scenario=scenario,
        )
        lat_dim: str = dataset_config.get("lat_dim", "lat")
        lon_dim: str = dataset_config.get("lon_dim", "lon")
        lat_2d: Optional[str] = dataset_config.get("lat_2d_coord")
        lon_2d: Optional[str] = dataset_config.get("lon_2d_coord")

        netcdf_vars = list(canonical_to_netcdf.values())
        ds = self._open_dataset(opendap_url=opendap_url, netcdf_vars=netcdf_vars)
        ds = self._subset_spatial(
            ds=ds,
            bbox=bbox,
            polygon_geojson=polygon_geojson,
            lat_dim=lat_dim,
            lon_dim=lon_dim,
            lat_2d=lat_2d,
            lon_2d=lon_2d,
        )
        ds = self._subset_temporal(ds=ds, start_date=start_date, end_date=end_date)

        if aggregation == "monthly":
            ds = self._aggregate_monthly(ds)

        ds = self._aggregate_spatial(ds=ds, lat_dim=lat_dim, lon_dim=lon_dim)
        ds.load()

        return self._build_result(
            ds=ds,
            variables=variables,
            canonical_to_netcdf=canonical_to_netcdf,
            dataset_config=dataset_config,
            bbox=bbox,
            aggregation=aggregation,
            dataset=dataset,
            scenario=scenario,
            model=model,
            start_date=start_date,
            end_date=end_date,
        )
