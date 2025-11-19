"""
Module defining Pydantic models for STAC metadata representation.
It is currently not used in the main processing pipeline but may be useful for future enhancements or replaccing some mapping logic.
"""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, field_validator


class RasterBandModel(BaseModel):
    nodata: Optional[float]
    data_type: str
    spatial_resolution: float


class AssetModel(BaseModel):
    href: str
    type: str
    roles: List[str]
    title: str
    raster_bands: List[RasterBandModel]


class COGMetadataModel(BaseModel):
    id: str
    geometry: Dict[str, Any]
    bbox: List[float]
    datetime: str
    properties: Dict[str, Any]
    assets: Dict[str, AssetModel]
    stac_extensions: List[str]
    file_url: str

    @field_validator("bbox")
    def check_bbox_length(self, v):
        if len(v) != 4:
            raise ValueError("bbox must be a list of 4 floats")
        return v
