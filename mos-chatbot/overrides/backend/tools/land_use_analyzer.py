from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class LandUseHistory:
    parcel_id: str
    years: list[int] = field(default_factory=list)
    land_uses: list[str] = field(default_factory=list)


def merge_land_use(stac_items: list[dict], parcel: dict) -> LandUseHistory:
    """Produce a LandUseHistory from STAC items and a parcel feature."""
    parcel_id = str(parcel.get("id", "unknown"))
    years: list[int] = []
    land_uses: list[str] = []

    for item in stac_items:
        props: dict = item.get("properties", {})
        if "datetime" in props:
            years.append(datetime.fromisoformat(props["datetime"]).year)
            land_uses.append(props.get("land_use", "unknown"))
    return LandUseHistory(parcel_id=parcel_id, years=years, land_uses=land_uses)
