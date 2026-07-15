"""
Climate data backend package.

Provides CMIP6 climate projection access via PAVICS THREDDS OPeNDAP
and agronomic climate indicator computations.
"""

from .cmip_backend import CMIPBackend
from .indicators import calc_growing_degree_days
from .models import (
    ClimateIndicatorsFeature,
    ClimateIndicatorsInput,
    ClimateTimeseriesFeature,
    ClimateTimeseriesInput,
    CMIPModel,
    Dataset,
    Indicator,
)

__all__ = [
    "CMIPBackend",
    "ClimateIndicatorsFeature",
    "ClimateIndicatorsInput",
    "ClimateTimeseriesFeature",
    "ClimateTimeseriesInput",
    "CMIPModel",
    "Dataset",
    "Indicator",
    "calc_growing_degree_days",
]
