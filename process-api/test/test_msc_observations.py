"""
Tests for the msc-observations OGC API process.

Markers:
  @pytest.mark.unit    — pure Python logic, no I/O
  @pytest.mark.mocked  — external I/O mocked (HTTP, DB)
"""

from __future__ import annotations

from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

import pytest
import requests
from processes.msc_observations import MSCObservationsProcessor
from processes.msc_observations_metadata import PROCESS_METADATA
from processes.weather_backend.msc_backend import (
    MSCBackend,
    MSCObservationCollection,
    MSCObservationFeature,
    MSCObservationProperties,
    MSCObservationsInput,
    _cache,
    _make_cache_key,
)
from pygeoapi.process.base import ProcessorExecuteError

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

_BBOX_QC = (-74.0, 45.0, -73.0, 46.0)


def _make_climate_daily_feature(
    station_id: str,
    station_name: str,
    date: str,
    lon: float = -73.5,
    lat: float = 45.5,
    *,
    tasmin: float = -5.0,
    tasmax: float = 2.0,
    pr: float = 1.5,
    snow: float = 10.0,
) -> Dict[str, Any]:
    """Build a synthetic climate-daily GeoJSON Feature."""
    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [lon, lat, 50.0]},
        "properties": {
            "CLIMATE_IDENTIFIER": station_id,
            "STATION_NAME": station_name,
            "PROVINCE_CODE": "QC",
            "LOCAL_DATE": f"{date} 00:00:00",
            "MIN_TEMPERATURE": tasmin,
            "MAX_TEMPERATURE": tasmax,
            "MEAN_TEMPERATURE": (tasmin + tasmax) / 2,
            "TOTAL_PRECIPITATION": pr,
            "TOTAL_SNOW": snow,
            "SNOW_ON_GROUND": None,
        },
    }


def _make_swob_feature(
    tc_id: str,
    stn_name: str,
    obs_time: str,
    lon: float = -73.5,
    lat: float = 45.5,
    *,
    air_temp: float = -3.0,
    pr: float = 0.0,
) -> Dict[str, Any]:
    """Build a synthetic swob-realtime GeoJSON Feature."""
    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [lon, lat, 50.0]},
        "properties": {
            "tc_id-value": tc_id,
            "stn_nam-value": stn_name,
            "obs_date_tm": obs_time,
            "air_temp": air_temp,
            "min_air_temp_pst1hr": air_temp - 1.0,
            "max_air_temp_pst1hr": air_temp + 1.0,
            "rnfl_amt_pst1hr": pr,
            "rel_hum": 75.0,
            "avg_wnd_spd_10m_pst10mts": None,
        },
    }


@pytest.fixture
def msc_backend() -> MSCBackend:
    """MSCBackend with a test base URL."""
    return MSCBackend(base_url="https://api.weather.gc.ca")


@pytest.fixture
def processor_instance() -> MSCObservationsProcessor:
    """MSCObservationsProcessor with a mocked backend."""
    MSCObservationsProcessor._backend = MSCBackend(base_url="https://api.weather.gc.ca")
    return MSCObservationsProcessor({"name": "msc-observations"})


# ---------------------------------------------------------------------------
# TestMetadata
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestMetadata:
    def test_metadata_has_required_keys(self) -> None:
        for key in ("version", "id", "title", "description", "inputs", "outputs"):
            assert key in PROCESS_METADATA

    def test_metadata_id(self) -> None:
        assert PROCESS_METADATA["id"] == "msc-observations"

    def test_metadata_inputs_defined(self) -> None:
        inputs = PROCESS_METADATA["inputs"]
        for key in (
            "location_type",
            "collection",
            "variables",
            "start_date",
            "end_date",
        ):
            assert key in inputs

    def test_metadata_outputs_defined(self) -> None:
        assert "result" in PROCESS_METADATA["outputs"]

    def test_metadata_mime_type(self) -> None:
        media_type = PROCESS_METADATA["outputs"]["result"]["schema"]["contentMediaType"]
        assert "geo+json" in media_type


# ---------------------------------------------------------------------------
# TestMSCObservationsInput
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestMSCObservationsInput:
    def test_valid_bbox_input(self) -> None:
        obj = MSCObservationsInput(
            location_type="bbox",
            bbox=[-74.0, 45.0, -73.0, 46.0],
            collection="climate-daily",
            variables=["tasmin", "tasmax"],
            start_date="2024-01-01",
            end_date="2024-01-07",
        )
        assert obj.collection == "climate-daily"
        assert obj.limit == 500

    def test_invalid_bbox_minx_ge_maxx(self) -> None:
        with pytest.raises(Exception, match="minx"):
            MSCObservationsInput(
                location_type="bbox",
                bbox=[-73.0, 45.0, -74.0, 46.0],
                collection="climate-daily",
                variables=["tasmin"],
                start_date="2024-01-01",
                end_date="2024-01-07",
            )

    def test_invalid_bbox_miny_ge_maxy(self) -> None:
        with pytest.raises(Exception, match="miny"):
            MSCObservationsInput(
                location_type="bbox",
                bbox=[-74.0, 46.0, -73.0, 45.0],
                collection="climate-daily",
                variables=["tasmin"],
                start_date="2024-01-01",
                end_date="2024-01-07",
            )

    def test_invalid_variable_for_climate_daily(self) -> None:
        with pytest.raises(Exception, match="not available"):
            MSCObservationsInput(
                location_type="bbox",
                bbox=[-74.0, 45.0, -73.0, 46.0],
                collection="climate-daily",
                variables=["hurs"],  # swob-realtime only
                start_date="2024-01-01",
                end_date="2024-01-07",
            )

    def test_invalid_variable_for_swob_realtime(self) -> None:
        with pytest.raises(Exception, match="not available"):
            MSCObservationsInput(
                location_type="bbox",
                bbox=[-74.0, 45.0, -73.0, 46.0],
                collection="swob-realtime",
                variables=["snd"],  # climate-daily only
                start_date="2024-01-01",
                end_date="2024-01-07",
            )

    def test_start_date_after_end_date(self) -> None:
        with pytest.raises(Exception, match="start_date"):
            MSCObservationsInput(
                location_type="bbox",
                bbox=[-74.0, 45.0, -73.0, 46.0],
                collection="climate-daily",
                variables=["tasmin"],
                start_date="2024-01-07",
                end_date="2024-01-01",
            )

    def test_bad_date_format(self) -> None:
        with pytest.raises(Exception, match="YYYY-MM-DD"):
            MSCObservationsInput(
                location_type="bbox",
                bbox=[-74.0, 45.0, -73.0, 46.0],
                collection="climate-daily",
                variables=["tasmin"],
                start_date="01/01/2024",
                end_date="2024-01-07",
            )

    def test_missing_bbox_field(self) -> None:
        with pytest.raises(Exception, match="bbox"):
            MSCObservationsInput(
                location_type="bbox",
                collection="climate-daily",
                variables=["tasmin"],
                start_date="2024-01-01",
                end_date="2024-01-07",
            )

    def test_missing_farm_id_field(self) -> None:
        with pytest.raises(Exception, match="farm_id"):
            MSCObservationsInput(
                location_type="farm_id",
                collection="climate-daily",
                variables=["tasmin"],
                start_date="2024-01-01",
                end_date="2024-01-07",
            )

    def test_duplicate_variables_deduplicated(self) -> None:
        obj = MSCObservationsInput(
            location_type="bbox",
            bbox=[-74.0, 45.0, -73.0, 46.0],
            collection="climate-daily",
            variables=["tasmin", "tasmax", "tasmin"],
            start_date="2024-01-01",
            end_date="2024-01-07",
        )
        assert obj.variables == ["tasmin", "tasmax"]

    def test_limit_out_of_range_low(self) -> None:
        with pytest.raises(Exception):
            MSCObservationsInput(
                location_type="bbox",
                bbox=[-74.0, 45.0, -73.0, 46.0],
                collection="climate-daily",
                variables=["tasmin"],
                start_date="2024-01-01",
                end_date="2024-01-07",
                limit=0,
            )

    def test_limit_out_of_range_high(self) -> None:
        with pytest.raises(Exception):
            MSCObservationsInput(
                location_type="bbox",
                bbox=[-74.0, 45.0, -73.0, 46.0],
                collection="climate-daily",
                variables=["tasmin"],
                start_date="2024-01-01",
                end_date="2024-01-07",
                limit=5001,
            )

    def test_valid_point_input(self) -> None:
        obj = MSCObservationsInput(
            location_type="point",
            point=[-73.5, 45.5],
            collection="swob-realtime",
            variables=["tas", "pr"],
            start_date="2024-01-01",
            end_date="2024-01-07",
        )
        assert obj.point == [-73.5, 45.5]


# ---------------------------------------------------------------------------
# TestMSCBackendFetchPage
# ---------------------------------------------------------------------------


@pytest.mark.mocked
class TestMSCBackendFetchPage:
    def _mock_response(
        self, features: List[Dict], number_matched: int = None
    ) -> MagicMock:
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        payload = {
            "type": "FeatureCollection",
            "features": features,
            "numberMatched": (
                number_matched if number_matched is not None else len(features)
            ),
            "numberReturned": len(features),
        }
        resp.json.return_value = payload
        return resp

    def test_correct_url_and_params_climate_daily(
        self, msc_backend: MSCBackend
    ) -> None:
        with patch.object(msc_backend._session, "get") as mock_get:
            mock_get.return_value = self._mock_response([])
            msc_backend._fetch_page(
                collection="climate-daily",
                bbox=(-74.0, 45.0, -73.0, 46.0),
                datetime_interval="2024-01-01/2024-01-07",
                offset=0,
            )
            call_args = mock_get.call_args
            assert call_args[0][0].endswith("/collections/climate-daily/items")
            params = call_args[1]["params"]
            assert params["bbox"] == "-74.0,45.0,-73.0,46.0"
            assert params["datetime"] == "2024-01-01/2024-01-07"
            assert params["f"] == "json"
            assert params["offset"] == 0

    def test_swob_datetime_format(self, msc_backend: MSCBackend) -> None:
        interval = msc_backend._build_datetime_interval(
            "swob-realtime", "2024-01-01", "2024-01-07"
        )
        assert interval == "2024-01-01T00:00:00Z/2024-01-07T23:59:59Z"

    def test_climate_daily_datetime_format(self, msc_backend: MSCBackend) -> None:
        interval = msc_backend._build_datetime_interval(
            "climate-daily", "2024-01-01", "2024-01-07"
        )
        assert interval == "2024-01-01/2024-01-07"

    def test_http_404_raises(self, msc_backend: MSCBackend) -> None:
        resp = MagicMock()
        http_err = requests.exceptions.HTTPError(response=MagicMock(status_code=404))
        resp.raise_for_status.side_effect = http_err
        with patch.object(msc_backend._session, "get", return_value=resp):
            with pytest.raises(ProcessorExecuteError, match="HTTP error 404"):
                msc_backend._fetch_page(
                    collection="climate-daily",
                    bbox=_BBOX_QC,
                    datetime_interval="2024-01-01/2024-01-07",
                    offset=0,
                )

    def test_timeout_raises(self, msc_backend: MSCBackend) -> None:
        with patch.object(
            msc_backend._session,
            "get",
            side_effect=requests.exceptions.Timeout("timed out"),
        ):
            with pytest.raises(ProcessorExecuteError, match="timed out"):
                msc_backend._fetch_page(
                    collection="climate-daily",
                    bbox=_BBOX_QC,
                    datetime_interval="2024-01-01/2024-01-07",
                    offset=0,
                )

    def test_pagination_second_page_offset(self, msc_backend: MSCBackend) -> None:
        """Two pages: first full (PAGE_SIZE), second partial → two GET calls."""
        page1_features = [
            _make_climate_daily_feature(f"STN{i:04d}", f"Station {i}", "2024-01-01")
            for i in range(msc_backend.PAGE_SIZE)
        ]
        page2_features = [
            _make_climate_daily_feature("STN9999", "Last Station", "2024-01-02")
        ]

        responses = [
            MagicMock(
                **{
                    "raise_for_status": MagicMock(),
                    "json.return_value": {
                        "type": "FeatureCollection",
                        "features": page1_features,
                        "numberMatched": msc_backend.PAGE_SIZE + 1,
                        "numberReturned": msc_backend.PAGE_SIZE,
                    },
                }
            ),
            MagicMock(
                **{
                    "raise_for_status": MagicMock(),
                    "json.return_value": {
                        "type": "FeatureCollection",
                        "features": page2_features,
                        "numberMatched": msc_backend.PAGE_SIZE + 1,
                        "numberReturned": 1,
                    },
                }
            ),
        ]
        with patch.object(
            msc_backend._session, "get", side_effect=responses
        ) as mock_get:
            items = msc_backend._fetch_all_items(
                collection="climate-daily",
                bbox=_BBOX_QC,
                datetime_interval="2024-01-01/2024-01-07",
            )
        assert len(items) == msc_backend.PAGE_SIZE + 1
        assert mock_get.call_count == 2
        # Second call should have offset=PAGE_SIZE
        second_params = mock_get.call_args_list[1][1]["params"]
        assert second_params["offset"] == msc_backend.PAGE_SIZE


# ---------------------------------------------------------------------------
# TestMSCBackendBboxEdgeCases
# ---------------------------------------------------------------------------


@pytest.mark.mocked
class TestMSCBackendBboxEdgeCases:
    def _patch_fetch_all(self, msc_backend: MSCBackend, items: List[Dict]):
        return patch.object(msc_backend, "_fetch_all_items", return_value=items)

    def test_normal_bbox_returns_feature_collection(
        self, msc_backend: MSCBackend
    ) -> None:
        items = [
            _make_climate_daily_feature("7025251", "MONTREAL", "2024-01-01"),
            _make_climate_daily_feature("7025251", "MONTREAL", "2024-01-02"),
        ]
        with self._patch_fetch_all(msc_backend, items):
            result = msc_backend.fetch(
                bbox=_BBOX_QC,
                collection="climate-daily",
                variables=["tasmin", "tasmax"],
                start_date="2024-01-01",
                end_date="2024-01-02",
            )
        geojson = result.to_geojson()
        assert geojson["type"] == "FeatureCollection"
        assert len(geojson["features"]) == 1
        assert geojson["features"][0]["properties"]["station_id"] == "7025251"
        assert len(geojson["features"][0]["properties"]["data"]["time"]) == 2

    def test_bbox_with_no_stations_raises(self, msc_backend: MSCBackend) -> None:
        with self._patch_fetch_all(msc_backend, []):
            with pytest.raises(ProcessorExecuteError, match="No data found"):
                msc_backend.fetch(
                    bbox=(-10.0, -10.0, -9.0, -9.0),
                    collection="climate-daily",
                    variables=["tasmin"],
                    start_date="2024-01-01",
                    end_date="2024-01-07",
                )

    def test_bbox_multiple_stations(self, msc_backend: MSCBackend) -> None:
        items = [
            _make_climate_daily_feature(
                "7025251", "MONTREAL", "2024-01-01", lon=-73.5, lat=45.5
            ),
            _make_climate_daily_feature(
                "7026675", "LAVAL", "2024-01-01", lon=-73.7, lat=45.6
            ),
        ]
        with self._patch_fetch_all(msc_backend, items):
            result = msc_backend.fetch(
                bbox=_BBOX_QC,
                collection="climate-daily",
                variables=["tasmin"],
                start_date="2024-01-01",
                end_date="2024-01-01",
            )
        assert len(result.features) == 2

    def test_station_limit_caps_output(self, msc_backend: MSCBackend) -> None:
        """limit=1 should return only one station even if multiple are found."""
        items = [
            _make_climate_daily_feature("7025251", "MONTREAL", "2024-01-01"),
            _make_climate_daily_feature("7026675", "LAVAL", "2024-01-01"),
            _make_climate_daily_feature("7027320", "LONGUEUIL", "2024-01-01"),
        ]
        with self._patch_fetch_all(msc_backend, items):
            result = msc_backend.fetch(
                bbox=_BBOX_QC,
                collection="climate-daily",
                variables=["tasmin"],
                start_date="2024-01-01",
                end_date="2024-01-01",
                limit=1,
            )
        assert len(result.features) == 1

    def test_small_bbox_expanded_before_api_call(self, msc_backend: MSCBackend) -> None:
        """Any bbox smaller than MIN_BBOX_DEG is center-expanded before the API call."""
        items = [_make_climate_daily_feature("7025251", "MONTREAL", "2024-01-01")]
        lon, lat = -73.5, 45.5
        half = msc_backend.MIN_BBOX_DEG / 2
        with self._patch_fetch_all(msc_backend, items) as mock_fetch:
            msc_backend.fetch(
                bbox=(lon, lat, lon, lat),
                collection="climate-daily",
                variables=["tasmin"],
                start_date="2024-01-01",
                end_date="2024-01-01",
            )
        # _fetch_all_items(collection, bbox, datetime_interval) — positional args
        called_bbox = mock_fetch.call_args.args[1]
        assert called_bbox == (lon - half, lat - half, lon + half, lat + half)

    def test_large_bbox_not_expanded(self, msc_backend: MSCBackend) -> None:
        """A bbox already larger than MIN_BBOX_DEG must not be modified."""
        bbox = (-74.0, 45.0, -73.0, 46.0)
        assert msc_backend._ensure_min_bbox(bbox) == bbox

    def test_point_bbox_expanded_to_min(self, msc_backend: MSCBackend) -> None:
        """A degenerate point bbox must be center-expanded to MIN_BBOX_DEG."""
        lon, lat = -73.5, 45.5
        half = msc_backend.MIN_BBOX_DEG / 2
        result = msc_backend._ensure_min_bbox((lon, lat, lon, lat))
        assert result == (lon - half, lat - half, lon + half, lat + half)

    def test_small_farm_bbox_expanded_to_min(self, msc_backend: MSCBackend) -> None:
        """A small polygon bbox (e.g. a farm) must also be expanded."""
        # ~500m × 400m farm bbox
        farm_bbox = (-68.914, 47.553, -68.907, 47.559)
        result = msc_backend._ensure_min_bbox(farm_bbox)
        cx = (-68.914 + -68.907) / 2
        cy = (47.553 + 47.559) / 2
        half = msc_backend.MIN_BBOX_DEG / 2
        assert result == (cx - half, cy - half, cx + half, cy + half)

    def test_result_metadata_fields(self, msc_backend: MSCBackend) -> None:
        items = [_make_climate_daily_feature("7025251", "MONTREAL", "2024-01-01")]
        with self._patch_fetch_all(msc_backend, items):
            result = msc_backend.fetch(
                bbox=_BBOX_QC,
                collection="climate-daily",
                variables=["tasmin"],
                start_date="2024-01-01",
                end_date="2024-01-07",
            )
        assert result.provider == "msc-geomet"
        assert result.collection == "climate-daily"
        assert result.temporal_extent == ["2024-01-01", "2024-01-07"]
        assert result.variables == ["tasmin"]


# ---------------------------------------------------------------------------
# TestMSCBackendGroupByStation
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestMSCBackendGroupByStation:
    def _group(
        self,
        backend: MSCBackend,
        items: List[Dict],
        variables: List[str],
        collection: str = "climate-daily",
    ) -> List[MSCObservationFeature]:
        from processes.weather_backend.msc_backend import COLLECTION_CONFIG

        config = COLLECTION_CONFIG[collection]
        return backend._group_by_station(items, collection, config, variables)

    def test_two_items_same_station_merged(self, msc_backend: MSCBackend) -> None:
        items = [
            _make_climate_daily_feature("7025251", "MONTREAL", "2024-01-01"),
            _make_climate_daily_feature("7025251", "MONTREAL", "2024-01-02"),
        ]
        features = self._group(msc_backend, items, ["tasmin", "tasmax"])
        assert len(features) == 1
        data = features[0].properties.data
        assert data["time"] == ["2024-01-01", "2024-01-02"]
        assert len(data["tasmin"]) == 2

    def test_two_different_stations(self, msc_backend: MSCBackend) -> None:
        items = [
            _make_climate_daily_feature("7025251", "MONTREAL", "2024-01-01"),
            _make_climate_daily_feature("7026675", "LAVAL", "2024-01-01"),
        ]
        features = self._group(msc_backend, items, ["tasmin"])
        assert len(features) == 2

    def test_null_variable_value_becomes_none(self, msc_backend: MSCBackend) -> None:
        """SNOW_ON_GROUND is None in the fixture → snd should be None in data."""
        items = [_make_climate_daily_feature("7025251", "MONTREAL", "2024-01-01")]
        features = self._group(msc_backend, items, ["snd"])
        assert features[0].properties.data["snd"] == [None]

    def test_items_sorted_by_time_ascending(self, msc_backend: MSCBackend) -> None:
        items = [
            _make_climate_daily_feature("7025251", "MONTREAL", "2024-01-03"),
            _make_climate_daily_feature("7025251", "MONTREAL", "2024-01-01"),
            _make_climate_daily_feature("7025251", "MONTREAL", "2024-01-02"),
        ]
        features = self._group(msc_backend, items, ["tasmin"])
        assert features[0].properties.data["time"] == [
            "2024-01-01",
            "2024-01-02",
            "2024-01-03",
        ]

    def test_climate_daily_time_field_truncated(self, msc_backend: MSCBackend) -> None:
        """LOCAL_DATE '1975-03-03 00:00:00' must be truncated to '1975-03-03'."""
        assert (
            msc_backend._parse_time("1975-03-03 00:00:00", "climate-daily")
            == "1975-03-03"
        )

    def test_swob_time_field_kept_as_is(self, msc_backend: MSCBackend) -> None:
        raw = "2026-03-12T02:57:00.000Z"
        assert msc_backend._parse_time(raw, "swob-realtime") == raw

    def test_swob_realtime_grouping(self, msc_backend: MSCBackend) -> None:
        items = [
            _make_swob_feature("YUL", "MONTREAL", "2026-03-12T01:00:00.000Z"),
            _make_swob_feature("YUL", "MONTREAL", "2026-03-12T02:00:00.000Z"),
        ]
        from processes.weather_backend.msc_backend import COLLECTION_CONFIG

        config = COLLECTION_CONFIG["swob-realtime"]
        features = msc_backend._group_by_station(
            items, "swob-realtime", config, ["tas", "pr"]
        )
        assert len(features) == 1
        data = features[0].properties.data
        assert len(data["time"]) == 2

    def test_province_included_for_climate_daily(self, msc_backend: MSCBackend) -> None:
        items = [_make_climate_daily_feature("7025251", "MONTREAL", "2024-01-01")]
        features = self._group(msc_backend, items, ["tasmin"])
        assert features[0].properties.province == "QC"

    def test_province_not_included_for_swob(self, msc_backend: MSCBackend) -> None:
        items = [_make_swob_feature("YUL", "MONTREAL", "2026-03-12T01:00:00.000Z")]
        from processes.weather_backend.msc_backend import COLLECTION_CONFIG

        config = COLLECTION_CONFIG["swob-realtime"]
        features = msc_backend._group_by_station(
            items, "swob-realtime", config, ["tas"]
        )
        assert features[0].properties.province is None

    def test_geometry_uses_lon_lat_only(self, msc_backend: MSCBackend) -> None:
        """3D coordinates [lon, lat, elev] must be trimmed to [lon, lat]."""
        items = [
            _make_climate_daily_feature(
                "7025251", "MONTREAL", "2024-01-01", lon=-73.5, lat=45.5
            )
        ]
        features = self._group(msc_backend, items, ["tasmin"])
        coords = features[0].geometry.coordinates
        assert len(coords) == 2
        assert coords == [-73.5, 45.5]


# ---------------------------------------------------------------------------
# TestMSCBackendFetch (cache)
# ---------------------------------------------------------------------------


@pytest.mark.mocked
class TestMSCBackendFetch:
    def test_cache_miss_calls_fetch_all(self, msc_backend: MSCBackend) -> None:
        _cache.clear()
        items = [_make_climate_daily_feature("7025251", "MONTREAL", "2024-01-01")]
        with patch.object(
            msc_backend, "_fetch_all_items", return_value=items
        ) as mock_fetch:
            msc_backend.fetch(
                bbox=_BBOX_QC,
                collection="climate-daily",
                variables=["tasmin"],
                start_date="2024-01-01",
                end_date="2024-01-01",
            )
        mock_fetch.assert_called_once()

    def test_cache_hit_skips_fetch(self, msc_backend: MSCBackend) -> None:
        _cache.clear()
        cached_result = MSCObservationCollection(
            collection="climate-daily",
            temporal_extent=["2024-02-01", "2024-02-07"],
            variables=["tasmin"],
            features=[],
        )
        key = _make_cache_key(
            _BBOX_QC, "climate-daily", ("tasmin",), "2024-02-01", "2024-02-07", 500
        )
        _cache.set(key, cached_result)

        with patch.object(msc_backend, "_fetch_all_items") as mock_fetch:
            result = msc_backend.fetch(
                bbox=_BBOX_QC,
                collection="climate-daily",
                variables=["tasmin"],
                start_date="2024-02-01",
                end_date="2024-02-07",
            )
        mock_fetch.assert_not_called()
        assert result is cached_result

    def test_unknown_collection_raises(self, msc_backend: MSCBackend) -> None:
        with pytest.raises(ProcessorExecuteError, match="Unknown MSC collection"):
            msc_backend._get_collection_config("nonexistent-collection")


# ---------------------------------------------------------------------------
# TestMSCObservationsProcessorExecute
# ---------------------------------------------------------------------------


@pytest.mark.mocked
class TestMSCObservationsProcessorExecute:
    def _sample_result(self) -> MSCObservationCollection:
        from processes.weather_backend.models import GeoJSONGeometry

        return MSCObservationCollection(
            collection="climate-daily",
            temporal_extent=["2024-01-01", "2024-01-07"],
            variables=["tasmin", "tasmax"],
            features=[
                MSCObservationFeature(
                    geometry=GeoJSONGeometry(type="Point", coordinates=[-73.5, 45.5]),
                    properties=MSCObservationProperties(
                        station_name="MONTREAL",
                        station_id="7025251",
                        province="QC",
                        variables=["tasmin", "tasmax"],
                        data={
                            "time": ["2024-01-01"],
                            "tasmin": [-5.0],
                            "tasmax": [2.0],
                        },
                        units={"tasmin": "degC", "tasmax": "degC"},
                    ),
                )
            ],
        )

    def test_bbox_execute_returns_feature_collection(
        self, processor_instance: MSCObservationsProcessor
    ) -> None:
        result = self._sample_result()
        with patch.object(
            MSCObservationsProcessor._backend, "fetch", return_value=result  # type: ignore[union-attr]
        ):
            mime, output = processor_instance.execute(
                {
                    "location_type": "bbox",
                    "bbox": [-74.0, 45.0, -73.0, 46.0],
                    "collection": "climate-daily",
                    "variables": ["tasmin", "tasmax"],
                    "start_date": "2024-01-01",
                    "end_date": "2024-01-07",
                }
            )
        assert mime == "application/geo+json"
        assert output["id"] == "result"
        assert output["value"]["type"] == "FeatureCollection"

    def test_farm_id_triggers_db_lookup(
        self, processor_instance: MSCObservationsProcessor
    ) -> None:
        result = self._sample_result()
        with (
            patch("processes.location_utils.psycopg.connect") as mock_connect,
            patch.object(
                MSCObservationsProcessor._backend, "fetch", return_value=result  # type: ignore[union-attr]
            ),
        ):
            mock_cursor = MagicMock()
            mock_cursor.fetchone.return_value = (
                '{"type":"Polygon","coordinates":[[[-74,45],[-73,45],[-73,46],[-74,46],[-74,45]]]}',
            )
            mock_connect.return_value.__enter__.return_value.cursor.return_value.__enter__.return_value = (
                mock_cursor
            )
            processor_instance.execute(
                {
                    "location_type": "farm_id",
                    "farm_id": "42",
                    "collection": "climate-daily",
                    "variables": ["tasmin"],
                    "start_date": "2024-01-01",
                    "end_date": "2024-01-07",
                }
            )
        mock_cursor.execute.assert_called_once()

    def test_invalid_collection_raises(
        self, processor_instance: MSCObservationsProcessor
    ) -> None:
        with pytest.raises(ProcessorExecuteError, match="Invalid inputs"):
            processor_instance.execute(
                {
                    "location_type": "bbox",
                    "bbox": [-74.0, 45.0, -73.0, 46.0],
                    "collection": "unknown-collection",
                    "variables": ["tasmin"],
                    "start_date": "2024-01-01",
                    "end_date": "2024-01-07",
                }
            )

    def test_backend_error_propagates(
        self, processor_instance: MSCObservationsProcessor
    ) -> None:
        with patch.object(
            MSCObservationsProcessor._backend,  # type: ignore[union-attr]
            "fetch",
            side_effect=ProcessorExecuteError("No data found"),
        ):
            with pytest.raises(ProcessorExecuteError, match="No data found"):
                processor_instance.execute(
                    {
                        "location_type": "bbox",
                        "bbox": [-74.0, 45.0, -73.0, 46.0],
                        "collection": "climate-daily",
                        "variables": ["tasmin"],
                        "start_date": "2024-01-01",
                        "end_date": "2024-01-07",
                    }
                )

    def test_model_round_trip(self) -> None:
        """MSCObservationCollection.to_geojson() must produce the correct dict structure."""
        model = self._sample_result()
        geojson = model.to_geojson()
        assert geojson["type"] == "FeatureCollection"
        assert geojson["provider"] == "msc-geomet"
        assert geojson["collection"] == "climate-daily"
        assert geojson["temporal_extent"] == ["2024-01-01", "2024-01-07"]
        assert geojson["variables"] == ["tasmin", "tasmax"]
        assert len(geojson["features"]) == 1
        feature = geojson["features"][0]
        assert feature["type"] == "Feature"
        assert feature["geometry"]["coordinates"] == [-73.5, 45.5]
        assert feature["properties"]["station_id"] == "7025251"
        assert feature["properties"]["data"]["tasmin"] == [-5.0]

    def test_processor_repr(self, processor_instance: MSCObservationsProcessor) -> None:
        assert "MSCObservationsProcessor" in repr(processor_instance)
