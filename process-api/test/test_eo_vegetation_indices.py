"""Unit tests for eo_vegetation_indices.py pure calculation functions."""

import inspect
import math

import pytest


class _MockCube:
    """Duck-typed openEO cube backed by plain floats for arithmetic testing."""

    def __init__(self, bands: dict):
        self._bands = bands

    def band(self, name: str):
        return self._bands[name]

    def filter_bands(self, names: list):
        return {n: self._bands[n] for n in names if n in self._bands}


# ------------------------------------------
# calculate_ndvi
# ------------------------------------------


@pytest.mark.unit
def test_ndvi_known_values():
    """NDVI = (NIR - Red) / (NIR + Red) with controlled scalar values."""
    from processes.eo_backend.vegetation_indices import calculate_ndvi

    cube = _MockCube({"B04": 0.2, "B08": 0.8})
    result = calculate_ndvi(cube)
    # (0.8 - 0.2) / (0.8 + 0.2) = 0.6 / 1.0 = 0.6
    assert math.isclose(result, 0.6, rel_tol=1e-9)


@pytest.mark.unit
def test_ndvi_homogeneous_scene_returns_zero():
    """When NIR == Red, NDVI = 0 (no vegetation signal)."""
    from processes.eo_backend.vegetation_indices import calculate_ndvi

    cube = _MockCube({"B04": 0.5, "B08": 0.5})
    result = calculate_ndvi(cube)
    assert math.isclose(result, 0.0, abs_tol=1e-12)


@pytest.mark.unit
def test_ndvi_full_vegetation_returns_one():
    """When Red = 0 and NIR > 0, NDVI = 1 (dense vegetation)."""
    from processes.eo_backend.vegetation_indices import calculate_ndvi

    cube = _MockCube({"B04": 0.0, "B08": 1.0})
    result = calculate_ndvi(cube)
    assert math.isclose(result, 1.0, rel_tol=1e-9)


# ------------------------------------------
# calculate_evi
# ------------------------------------------


@pytest.mark.unit
def test_evi_known_values():
    """EVI = G * (NIR - Red) / (NIR + C1*Red - C2*Blue + L) with default coefficients."""
    from processes.eo_backend.vegetation_indices import calculate_evi

    nir, red, blue = 0.5, 0.1, 0.05
    cube = _MockCube({"B02": blue, "B04": red, "B08": nir})
    result = calculate_evi(cube)
    # G=2.5, C1=6, C2=7.5, L=1.0
    expected = 2.5 * (nir - red) / (nir + 6.0 * red - 7.5 * blue + 1.0)
    assert math.isclose(result, expected, rel_tol=1e-9)


@pytest.mark.unit
def test_evi_default_coefficients():
    """EVI default arguments must match published Huete et al. values."""
    from processes.eo_backend.vegetation_indices import calculate_evi

    sig = inspect.signature(calculate_evi)
    assert sig.parameters["coeff_g"].default == 2.5
    assert sig.parameters["coeff_c1"].default == 6.0
    assert sig.parameters["coeff_c2"].default == 7.5
    assert sig.parameters["coeff_l"].default == 1.0


# ------------------------------------------
# calculate_savi
# ------------------------------------------


@pytest.mark.unit
def test_savi_known_values():
    """SAVI = Coeff * (NIR - Red) / (NIR + Red + L) with default coefficients."""
    from processes.eo_backend.vegetation_indices import calculate_savi

    nir, red = 0.8, 0.2
    cube = _MockCube({"B04": red, "B08": nir})
    result = calculate_savi(cube)
    # coeff=1.5, l=0.5
    expected = 1.5 * (nir - red) / (nir + red + 0.5)
    assert math.isclose(result, expected, rel_tol=1e-9)


@pytest.mark.unit
def test_savi_default_coefficients():
    """SAVI default arguments must match standard values."""
    from processes.eo_backend.vegetation_indices import calculate_savi

    sig = inspect.signature(calculate_savi)
    assert sig.parameters["coeff"].default == 1.5
    assert sig.parameters["l_factor"].default == 0.5


# ------------------------------------------
# get_true_color
# ------------------------------------------


@pytest.mark.unit
def test_get_true_color_extracts_rgb_bands():
    """get_true_color must request B04, B03, B02 (Red, Green, Blue)."""
    from unittest.mock import MagicMock

    from processes.eo_backend.vegetation_indices import get_true_color

    mock_cube = MagicMock()
    get_true_color(mock_cube)
    mock_cube.filter_bands.assert_called_once_with(["B04", "B03", "B02"])


# ------------------------------------------
# get_raw_bands
# ------------------------------------------


@pytest.mark.unit
def test_get_raw_bands_returns_cube_identity():
    """get_raw_bands must return the exact same object — no transform."""
    from processes.eo_backend.vegetation_indices import get_raw_bands

    sentinel = object()
    result = get_raw_bands(sentinel)
    assert result is sentinel
