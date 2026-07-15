"""
MSC GeoMet OGC API backend for the msc-observations process.

Queries the Meteorological Service of Canada (ECCC) open data API
at https://api.weather.gc.ca for near real-time and historical
surface weather observations. No authentication required.
"""

from __future__ import annotations

import hashlib
import logging
import os
from typing import Any, Dict, List, Literal, Optional, Tuple

import requests
from pydantic import BaseModel, Field, field_validator, model_validator
from pygeoapi.process.base import ProcessorExecuteError

from ..backend_utils import LocationType, LocationValidatorMixin
from ..cache_utils import TTLCache
from .models import GeoJSONGeometry

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Collection configuration
# ---------------------------------------------------------------------------

COLLECTION_CONFIG: Dict[str, Dict[str, Any]] = {
    "climate-daily": {
        "station_id_field": "CLIMATE_IDENTIFIER",
        "station_name_field": "STATION_NAME",
        "province_field": "PROVINCE_CODE",
        "time_field": "LOCAL_DATE",
        "variables": {
            "tasmin": {"field": "MIN_TEMPERATURE", "units": "degC"},
            "tasmax": {"field": "MAX_TEMPERATURE", "units": "degC"},
            "tas": {"field": "MEAN_TEMPERATURE", "units": "degC"},
            "pr": {"field": "TOTAL_PRECIPITATION", "units": "mm"},
            "prsn": {"field": "TOTAL_SNOW", "units": "mm"},
            "snd": {"field": "SNOW_ON_GROUND", "units": "cm"},
        },
    },
    "swob-realtime": {
        "station_id_field": "tc_id-value",
        "station_name_field": "stn_nam-value",
        "province_field": None,
        "time_field": "obs_date_tm",
        "variables": {
            "tas": {"field": "air_temp", "units": "degC"},
            "tasmin": {"field": "min_air_temp_pst1hr", "units": "degC"},
            "tasmax": {"field": "max_air_temp_pst1hr", "units": "degC"},
            "pr": {"field": "rnfl_amt_pst1hr", "units": "mm"},
            "hurs": {"field": "rel_hum", "units": "%"},
            "wss": {"field": "avg_wnd_spd_10m_pst10mts", "units": "km/h"},
        },
    },
}

COLLECTION_VARIABLES: Dict[str, frozenset] = {
    k: frozenset(v["variables"].keys()) for k, v in COLLECTION_CONFIG.items()
}

# ---------------------------------------------------------------------------
# Pydantic input model
# ---------------------------------------------------------------------------


class MSCObservationsInput(LocationValidatorMixin):
    """Validated input for the msc-observations process."""

    location_type: LocationType
    farm_id: Optional[str] = None
    point: Optional[List[float]] = Field(default=None, min_length=2, max_length=2)
    bbox: Optional[List[float]] = Field(default=None, min_length=4, max_length=4)
    polygon: Optional[Dict[str, Any]] = None
    collection: Literal["climate-daily", "swob-realtime"] = "climate-daily"
    variables: List[str] = Field(min_length=1)
    start_date: str
    end_date: str
    limit: int = Field(default=500, ge=1, le=5000)

    @field_validator("variables")
    @classmethod
    def deduplicate_variables(cls, v: List[str]) -> List[str]:
        """Remove duplicate variables while preserving order."""
        return list(dict.fromkeys(v))

    @field_validator("start_date", "end_date")
    @classmethod
    def validate_date_format(cls, v: str) -> str:
        """Ensure dates are valid ISO 8601 (YYYY-MM-DD) strings."""
        from datetime import date

        try:
            date.fromisoformat(v)
        except ValueError as exc:
            raise ValueError(
                f"Invalid date format (expected YYYY-MM-DD): {v!r}"
            ) from exc
        return v

    @model_validator(mode="after")
    def check_date_order(self) -> "MSCObservationsInput":
        """Ensure start_date <= end_date."""
        from datetime import date

        start = date.fromisoformat(self.start_date)
        end = date.fromisoformat(self.end_date)
        if start > end:
            raise ValueError(
                f"'start_date' ({self.start_date}) must be <= 'end_date' ({self.end_date})"
            )
        return self

    @model_validator(mode="after")
    def check_variables_for_collection(self) -> "MSCObservationsInput":
        """Ensure all requested variables are available for the selected collection."""
        valid = COLLECTION_VARIABLES.get(self.collection, frozenset())
        invalid = [v for v in self.variables if v not in valid]
        if invalid:
            raise ValueError(
                f"Variable(s) {invalid} not available for collection "
                f"{self.collection!r}. Available: {sorted(valid)}"
            )
        return self


# ---------------------------------------------------------------------------
# GeoJSON output models
# ---------------------------------------------------------------------------


class MSCObservationProperties(BaseModel):
    """Properties block of a single station Feature."""

    provider: Literal["msc-geomet"] = "msc-geomet"
    station_name: str
    station_id: str
    province: Optional[str] = None
    variables: List[str]
    data: Dict[str, List[Any]]
    units: Dict[str, str]


class MSCObservationFeature(BaseModel):
    """Valid GeoJSON Feature for one weather station with a timeseries."""

    type: Literal["Feature"] = "Feature"
    geometry: GeoJSONGeometry
    properties: MSCObservationProperties


class MSCObservationCollection(BaseModel):
    """Valid GeoJSON FeatureCollection of station observations."""

    type: Literal["FeatureCollection"] = "FeatureCollection"
    provider: Literal["msc-geomet"] = "msc-geomet"
    collection: str
    temporal_extent: List[str] = Field(min_length=2, max_length=2)
    variables: List[str]
    features: List[MSCObservationFeature]

    def to_geojson(self) -> Dict[str, Any]:
        """Serialise to a plain dict suitable for JSON encoding."""
        return self.model_dump()


# ---------------------------------------------------------------------------
# In-memory TTL cache
# ---------------------------------------------------------------------------

_cache: TTLCache[MSCObservationCollection] = TTLCache(
    ttl=int(os.getenv("MSC_CACHE_TTL", "900"))  # 15 min default
)

# ---------------------------------------------------------------------------
# Cache key
# ---------------------------------------------------------------------------


def _make_cache_key(*args: Any) -> str:
    """Return a stable SHA-256 hex digest for a set of query parameters."""
    raw = repr(args)
    return hashlib.sha256(raw.encode()).hexdigest()


# ---------------------------------------------------------------------------
# MSCBackend
# ---------------------------------------------------------------------------


class MSCBackend:
    """Weather station observation backend using the MSC GeoMet OGC API."""

    DEFAULT_BASE_URL: str = "https://api.weather.gc.ca"
    FETCH_TIMEOUT: int = 30
    PAGE_SIZE: int = 1000
    MAX_TOTAL_ITEMS: int = 10_000
    # Minimum bbox extent (degrees) guaranteed before querying the MSC API.
    # Weather stations are sparse — a farm polygon or point produces a bbox far
    # too small to contain any station. ~1° ≈ 100 km gives a reliable search radius.
    MIN_BBOX_DEG: float = 1.0

    def __init__(self, base_url: Optional[str] = None) -> None:
        """Initialise the MSC backend.

        Args:
            base_url: Override for the MSC GeoMet API base URL. Falls back to
                the MSC_API_BASE_URL env var, then DEFAULT_BASE_URL.
        """
        url = (
            base_url
            if base_url is not None
            else os.getenv("MSC_API_BASE_URL", self.DEFAULT_BASE_URL)
        )
        self._base_url = url.rstrip("/")
        self._session = requests.Session()
        self._session.headers.update({"Accept": "application/geo+json"})

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def fetch(
        self,
        bbox: Tuple[float, float, float, float],
        collection: str,
        variables: List[str],
        start_date: str,
        end_date: str,
        limit: int = 500,
    ) -> MSCObservationCollection:
        """Fetch station observations; returns cached result if already cached.

        Args:
            bbox: (minx, miny, maxx, maxy) in EPSG:4326.
            collection: MSC collection key (e.g. "climate-daily").
            variables: Canonical variable names (e.g. ["tasmin", "tasmax"]).
            start_date: ISO date string "YYYY-MM-DD".
            end_date: ISO date string "YYYY-MM-DD".
            limit: Maximum number of stations to include in the response.

        Returns:
            MSCObservationCollection (valid GeoJSON FeatureCollection).

        Raises:
            ProcessorExecuteError: On unknown collection, network error, or
                no data found.
        """
        cache_key: str = _make_cache_key(
            bbox, collection, tuple(variables), start_date, end_date, limit
        )
        cached: Optional[MSCObservationCollection] = _cache.get(cache_key)
        if cached is not None:
            logger.debug("Cache hit for MSC query %s…", cache_key[:12])
            return cached

        result: MSCObservationCollection = self._fetch_uncached(
            bbox=bbox,
            collection=collection,
            variables=variables,
            start_date=start_date,
            end_date=end_date,
            limit=limit,
        )
        _cache.set(cache_key, result)
        return result

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _ensure_min_bbox(
        self, bbox: Tuple[float, float, float, float]
    ) -> Tuple[float, float, float, float]:
        """Guarantee a minimum bbox extent before sending to the MSC OGC API.

        Weather stations are sparse — a point (zero area) or a small farm polygon
        bbox will contain no station geometries. This method center-expands any bbox
        whose width or height falls below MIN_BBOX_DEG so that the spatial search
        always covers at least ~100 km in each direction.

        Args:
            bbox: (minx, miny, maxx, maxy) in EPSG:4326.

        Returns:
            Original bbox if already large enough; otherwise a center-expanded bbox
            with width and height of at least MIN_BBOX_DEG.
        """
        minx, miny, maxx, maxy = bbox
        width = maxx - minx
        height = maxy - miny
        if width >= self.MIN_BBOX_DEG and height >= self.MIN_BBOX_DEG:
            return bbox
        cx = (minx + maxx) / 2
        cy = (miny + maxy) / 2
        half = self.MIN_BBOX_DEG / 2
        return (cx - half, cy - half, cx + half, cy + half)

    def _get_collection_config(self, collection: str) -> Dict[str, Any]:
        """Return the collection configuration entry.

        Raises:
            ProcessorExecuteError: If the collection is not registered.
        """
        config = COLLECTION_CONFIG.get(collection)
        if config is None:
            raise ProcessorExecuteError(
                f"Unknown MSC collection {collection!r}. "
                f"Available: {sorted(COLLECTION_CONFIG.keys())}"
            )
        return config

    def _build_datetime_interval(
        self, collection: str, start_date: str, end_date: str
    ) -> str:
        """Build the OGC API datetime interval string for the collection.

        Args:
            collection: MSC collection key.
            start_date: "YYYY-MM-DD".
            end_date: "YYYY-MM-DD".

        Returns:
            RFC 3339 interval string suitable for the ``datetime`` query param.
        """
        if collection == "swob-realtime":
            return f"{start_date}T00:00:00Z/{end_date}T23:59:59Z"
        return f"{start_date}/{end_date}"

    def _fetch_page(
        self,
        collection: str,
        bbox: Tuple[float, float, float, float],
        datetime_interval: str,
        offset: int,
    ) -> Dict[str, Any]:
        """Fetch one page of items from the MSC OGC API Features endpoint.

        Args:
            collection: MSC collection key.
            bbox: (minx, miny, maxx, maxy).
            datetime_interval: RFC 3339 interval string.
            offset: Pagination offset (0-based).

        Returns:
            GeoJSON FeatureCollection dict for this page.

        Raises:
            ProcessorExecuteError: On HTTP error or network failure.
        """
        url = f"{self._base_url}/collections/{collection}/items"
        params: Dict[str, Any] = {
            "f": "json",
            "bbox": f"{bbox[0]},{bbox[1]},{bbox[2]},{bbox[3]}",
            "datetime": datetime_interval,
            "limit": self.PAGE_SIZE,
            "offset": offset,
        }
        logger.debug("MSC GeoMet GET %s offset=%d bbox=%s", collection, offset, bbox)
        try:
            resp = self._session.get(url, params=params, timeout=self.FETCH_TIMEOUT)
            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.Timeout as exc:
            raise ProcessorExecuteError(
                f"MSC GeoMet API request timed out for collection {collection!r}: {exc}"
            ) from exc
        except requests.exceptions.HTTPError as exc:
            raise ProcessorExecuteError(
                f"MSC GeoMet API HTTP error {exc.response.status_code} "
                f"for collection {collection!r}: {exc}"
            ) from exc
        except requests.exceptions.RequestException as exc:
            raise ProcessorExecuteError(
                f"MSC GeoMet API request failed for collection {collection!r}: {exc}"
            ) from exc

    def _fetch_all_items(
        self,
        collection: str,
        bbox: Tuple[float, float, float, float],
        datetime_interval: str,
    ) -> List[Dict[str, Any]]:
        """Fetch all matching items via offset pagination, capped at MAX_TOTAL_ITEMS.

        Args:
            collection: MSC collection key.
            bbox: Bounding box.
            datetime_interval: RFC 3339 interval string.

        Returns:
            List of GeoJSON Feature dicts.
        """
        all_items: List[Dict[str, Any]] = []
        offset = 0
        while True:
            page = self._fetch_page(collection, bbox, datetime_interval, offset)
            features = page.get("features", [])
            all_items.extend(features)
            number_matched = page.get("numberMatched", len(all_items))
            fetched = len(features)
            if fetched < self.PAGE_SIZE:
                break
            if len(all_items) >= min(number_matched, self.MAX_TOTAL_ITEMS):
                logger.warning(
                    "MSC query hit MAX_TOTAL_ITEMS=%d cap; response may be truncated",
                    self.MAX_TOTAL_ITEMS,
                )
                break
            offset += self.PAGE_SIZE
        return all_items

    @staticmethod
    def _parse_time(raw: str, collection: str) -> str:
        """Normalise a raw time string from the API.

        Args:
            raw: Raw time string from the API property field.
            collection: MSC collection key (drives the parsing strategy).

        Returns:
            - ``climate-daily``: "YYYY-MM-DD" (truncate SQL timestamp)
            - ``swob-realtime``: ISO 8601 string kept as-is
        """
        if collection == "climate-daily":
            # "1975-03-03 00:00:00" → "1975-03-03"
            return raw[:10]
        # swob-realtime: "2026-03-12T02:57:00.000Z"
        return raw

    @staticmethod
    def _group_by_station(
        items: List[Dict[str, Any]],
        collection: str,
        config: Dict[str, Any],
        variables: List[str],
    ) -> List[MSCObservationFeature]:
        """Group raw API items by station and build a timeseries per station.

        Args:
            items: Raw GeoJSON Feature dicts from the API.
            collection: MSC collection key.
            config: Collection configuration from COLLECTION_CONFIG.
            variables: Canonical variable names requested.

        Returns:
            List of MSCObservationFeature instances, one per station.
        """
        station_id_field = config["station_id_field"]
        station_name_field = config["station_name_field"]
        province_field = config.get("province_field")
        time_field = config["time_field"]
        var_config: Dict[str, Any] = config["variables"]

        # Only keep variables that are registered for this collection
        var_mapping: Dict[str, Dict[str, str]] = {
            v: var_config[v] for v in variables if v in var_config
        }
        units: Dict[str, str] = {v: meta["units"] for v, meta in var_mapping.items()}

        # Accumulate rows per station
        stations: Dict[str, Dict[str, Any]] = {}

        for feature in items:
            props = feature.get("properties", {})
            geom = feature.get("geometry", {})

            station_id = str(props.get(station_id_field, ""))
            if not station_id:
                continue

            if station_id not in stations:
                coords = geom.get("coordinates", [0.0, 0.0])
                stations[station_id] = {
                    "geometry": {"type": "Point", "coordinates": coords[:2]},
                    "station_name": str(props.get(station_name_field, "")),
                    "station_id": station_id,
                    "province": (
                        str(props.get(province_field, "")) if province_field else None
                    ),
                    "rows": [],
                }

            raw_time = str(props.get(time_field, ""))
            time_str = MSCBackend._parse_time(raw_time, collection)

            row: Dict[str, Any] = {"time": time_str}
            for canonical, meta in var_mapping.items():
                raw_val = props.get(meta["field"])
                row[canonical] = (
                    round(float(raw_val), 4) if raw_val is not None else None
                )
            stations[station_id]["rows"].append(row)

        # Build Pydantic features sorted by time within each station
        features: List[MSCObservationFeature] = []
        for station_data in stations.values():
            rows: List[Dict[str, Any]] = sorted(
                station_data["rows"], key=lambda r: r["time"]
            )
            data: Dict[str, List[Any]] = {"time": [r["time"] for r in rows]}
            for canonical in variables:
                if canonical in var_mapping:
                    data[canonical] = [r.get(canonical) for r in rows]

            coords: List[float] = station_data["geometry"]["coordinates"]
            features.append(
                MSCObservationFeature(
                    geometry=GeoJSONGeometry(type="Point", coordinates=coords),
                    properties=MSCObservationProperties(
                        station_name=station_data["station_name"],
                        station_id=station_data["station_id"],
                        province=station_data["province"],
                        variables=variables,
                        data=data,
                        units=units,
                    ),
                )
            )

        return features

    def _fetch_uncached(
        self,
        bbox: Tuple[float, float, float, float],
        collection: str,
        variables: List[str],
        start_date: str,
        end_date: str,
        limit: int,
    ) -> MSCObservationCollection:
        """Full fetch pipeline (cache miss path).

        Steps:
        1. Validate collection.
        2. Build datetime interval.
        3. Fetch all pages up to MAX_TOTAL_ITEMS.
        4. Group by station and build per-station timeseries.
        5. Apply station limit.
        6. Return MSCObservationCollection.
        """
        config = self._get_collection_config(collection)
        datetime_interval = self._build_datetime_interval(
            collection, start_date, end_date
        )
        query_bbox = self._ensure_min_bbox(bbox)
        items = self._fetch_all_items(collection, query_bbox, datetime_interval)

        if not items:
            raise ProcessorExecuteError(
                f"No data found in MSC collection {collection!r} "
                f"for bbox {bbox} and period {start_date}/{end_date}. "
                "Possible causes: no active stations in this area for the requested period "
                "(climate-daily stations may have closed — try an earlier date range or "
                "switch to 'swob-realtime' for near real-time data within the last 30 days), "
                "or the area is outside MSC coverage (Canada only)."
            )

        station_features = self._group_by_station(
            items=items,
            collection=collection,
            config=config,
            variables=variables,
        )
        station_features = station_features[:limit]

        return MSCObservationCollection(
            collection=collection,
            temporal_extent=[start_date, end_date],
            variables=variables,
            features=station_features,
        )
