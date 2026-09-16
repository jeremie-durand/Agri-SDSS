"""
Vegetation Indices Calculation Module

This module provides functions to calculate various vegetation indices
from Sentinel-2 data cubes using openEO.
"""

from typing import Any


def calculate_ndvi(cube: Any) -> Any:
    """Calculate Normalized Difference Vegetation Index (NDVI)

    NDVI = (NIR - Red) / (NIR + Red)

    Args:
        cube: openEO data cube with B04 (Red) and B08 (NIR) bands

    Returns:
        Data cube with NDVI values ranging from -1 to 1
    """
    red = cube.band("B04")
    nir = cube.band("B08")
    return (nir - red) / (nir + red)


def calculate_evi(
    cube: Any,
    coeff_g: float = 2.5,
    coeff_c1: float = 6.0,
    coeff_c2: float = 7.5,
    coeff_l: float = 1.0,
) -> Any:
    """Calculate Enhanced Vegetation Index (EVI)

    EVI = G * (NIR - Red) / (NIR + C1*Red - C2*Blue + L)

    Args:
        cube: openEO data cube with B02 (Blue), B04 (Red), B08 (NIR) bands
        coeff_g: Gain factor (default: 2.5)
        coeff_c1: Red coefficient (default: 6.0)
        coeff_c2: Blue coefficient (default: 7.5)
        coeff_l: Canopy background adjustment (default: 1.0)

    Returns:
        Data cube with EVI values
    """
    blue = cube.band("B02")
    red = cube.band("B04")
    nir = cube.band("B08")
    return coeff_g * (nir - red) / (nir + coeff_c1 * red - coeff_c2 * blue + coeff_l)


def calculate_savi(cube: Any, coeff: float = 1.5, l_factor: float = 0.5) -> Any:
    """Calculate Soil Adjusted Vegetation Index (SAVI)

    SAVI = Coeff * (NIR - Red) / (NIR + Red + L)

    Args:
        cube: openEO data cube with B04 (Red) and B08 (NIR) bands
        coeff: SAVI coefficient (default: 1.5)
        l_factor: Soil brightness correction factor (default: 0.5)

    Returns:
        Data cube with SAVI values
    """
    red = cube.band("B04")
    nir = cube.band("B08")
    return coeff * (nir - red) / (nir + red + l_factor)


def get_true_color(cube: Any) -> Any:
    """Extract RGB bands for true color composite

    Args:
        cube: openEO data cube with B02 (Blue), B03 (Green), B04 (Red) bands

    Returns:
        Data cube filtered to RGB bands (B04, B03, B02)
    """
    return cube.filter_bands(["B04", "B03", "B02"])


def get_raw_bands(cube: Any) -> Any:
    """Return raw bands without processing

    Args:
        cube: openEO data cube

    Returns:
        Unmodified data cube
    """
    return cube
