"""
Weather data backend implementations.

- PAVICSBackend: gridded reanalysis and reforecast data via PAVICS THREDDS (OPeNDAP)
- MSCBackend: surface station observations via MSC GeoMet OGC API
"""

from .models import (
    GeoJSONGeometry,
    WeatherTimeseriesFeature,
    WeatherTimeseriesInput,
    WeatherTimeseriesProperties,
)
from .msc_backend import (
    MSCBackend,
    MSCObservationCollection,
    MSCObservationFeature,
    MSCObservationProperties,
    MSCObservationsInput,
)
from .pavics_backend import PAVICSBackend, WeatherSource

__all__ = [
    "GeoJSONGeometry",
    "MSCBackend",
    "MSCObservationCollection",
    "MSCObservationFeature",
    "MSCObservationProperties",
    "MSCObservationsInput",
    "PAVICSBackend",
    "WeatherSource",
    "WeatherTimeseriesFeature",
    "WeatherTimeseriesInput",
    "WeatherTimeseriesProperties",
]
