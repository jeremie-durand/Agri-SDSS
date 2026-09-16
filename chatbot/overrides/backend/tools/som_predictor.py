from dataclasses import dataclass


@dataclass
class SomPrediction:
    lat: float
    lon: float
    land_use: str
    som_value: float
    unit: str


def enrich_som(raw: dict, lat: float, lon: float, land_use: str) -> SomPrediction:
    """Wrap a raw raster-api response into a typed prediction object."""
    return SomPrediction(
        lat=lat,
        lon=lon,
        land_use=land_use,
        som_value=raw.get("value", 0.0),
        unit=raw.get("unit", "g/kg"),
    )
