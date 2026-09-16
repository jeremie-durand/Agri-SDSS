"""
Earth Observation backend for the sentinel-fetch OGC process.
"""

from .vegetation_indices import (
    calculate_evi,
    calculate_ndvi,
    calculate_savi,
    get_raw_bands,
    get_true_color,
)

__all__ = [
    "calculate_evi",
    "calculate_ndvi",
    "calculate_savi",
    "get_raw_bands",
    "get_true_color",
]
