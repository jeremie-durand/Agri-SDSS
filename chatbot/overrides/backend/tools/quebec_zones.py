REGION_BBOX: dict[str, str] = {
    "estrie": "-72.5,45.0,-71.0,45.8",
    "montérégie": "-74.0,45.0,-72.5,45.7",
    "chaudière-appalaches": "-71.5,45.8,-70.0,46.8",
    "bas-saint-laurent": "-69.5,47.0,-67.0,48.5",
}


def bbox_for_region(region_name: str) -> str:
    """Return a 'min_lon,min_lat,max_lon,max_lat' string for a known region.

    Raises ValueError for unknown regions.
    """
    key = region_name.lower().strip()
    if key not in REGION_BBOX:
        known = ", ".join(REGION_BBOX.keys())
        raise ValueError(f"Unknown region '{region_name}'. Known regions: {known}")
    return REGION_BBOX[key]
