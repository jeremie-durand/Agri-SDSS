"""
Tests for the hydro_backend terrain functions on small synthetic DEMs.

Markers:
  @pytest.mark.unit    — pure numpy logic, no I/O
"""

from __future__ import annotations

import math

import numpy as np
import pytest
from processes.hydro_backend import (
    fill_depressions,
    horn_slope_percent,
    ls_factor,
    mfd_specific_catchment_area,
)
from processes.hydro_backend.terrain import (
    NEIGHBOUR_OFFSETS,
    _freeman_weights,
    _padded,
)

CELL_M = 2.0
EPS = 1e-4


def _no_nodata(dem: np.ndarray) -> np.ndarray:
    return np.zeros(dem.shape, dtype=bool)


def _plane_falling_south(
    rows: int, cols: int, drop_per_cell: float = 0.1
) -> np.ndarray:
    return np.repeat((rows - np.arange(rows, dtype=float))[:, None], cols, axis=1) * (
        drop_per_cell
    )


def _interior_local_minima(filled: np.ndarray) -> int:
    rows, cols = filled.shape
    padded = np.pad(filled, 1, constant_values=np.nan)
    count = 0
    for r in range(1, rows - 1):
        for c in range(1, cols - 1):
            if np.isnan(filled[r, c]):
                continue
            neighbours = [
                padded[r + 1 + dr, c + 1 + dc] for dr, dc in NEIGHBOUR_OFFSETS
            ]
            if all(np.isnan(n) or n >= filled[r, c] for n in neighbours):
                count += 1
    return count


@pytest.mark.unit
def test_fill_raises_one_cell_pit_to_spill_level_plus_eps():
    dem = _plane_falling_south(5, 5)
    spill = dem[3, 2]
    dem[2, 2] -= 1.0

    filled = fill_depressions(dem, _no_nodata(dem), eps=EPS)

    assert filled[2, 2] == pytest.approx(spill + EPS)
    unchanged = np.ones(dem.shape, dtype=bool)
    unchanged[2, 2] = False
    np.testing.assert_array_equal(filled[unchanged], dem[unchanged])


@pytest.mark.unit
def test_fill_drains_closed_basin_without_interior_minimum():
    rows = cols = 11
    yy, xx = np.mgrid[0:rows, 0:cols]
    dem = np.hypot(yy - 5, xx - 5) * 0.5
    dem[0, :] += 5.0
    dem[-1, :] += 5.0
    dem[:, 0] += 5.0
    dem[:, -1] += 5.0

    filled = fill_depressions(dem, _no_nodata(dem), eps=EPS)

    assert np.all(filled >= dem)
    assert _interior_local_minima(filled) == 0


@pytest.mark.unit
def test_fill_treats_nodata_neighbours_as_outlets():
    dem = np.full((5, 5), 10.0)
    dem[2, 2] = 1.0
    nodata = np.zeros(dem.shape, dtype=bool)
    nodata[2, 3] = True

    filled = fill_depressions(dem, nodata, eps=EPS)

    assert filled[2, 2] == 1.0
    assert np.isnan(filled[2, 3])


@pytest.mark.unit
def test_fill_leaves_drained_plane_unchanged():
    dem = _plane_falling_south(20, 10)

    filled = fill_depressions(dem, _no_nodata(dem), eps=EPS)

    np.testing.assert_array_equal(filled, dem)


@pytest.mark.unit
def test_sca_rises_downslope_on_plane_and_reaches_profile_length():
    dem = _plane_falling_south(100, 40)
    filled = fill_depressions(dem, _no_nodata(dem))

    sca = mfd_specific_catchment_area(filled, CELL_M)

    middle = sca[:, 20]
    assert np.all(np.diff(middle) > 0)
    assert middle[-1] == pytest.approx(100 * CELL_M, rel=0.05)


@pytest.mark.unit
def test_sca_conserves_area_at_outlets():
    rng = np.random.default_rng(42)
    dem = _plane_falling_south(30, 25) + rng.normal(0, 0.3, (30, 25))
    nodata = np.zeros(dem.shape, dtype=bool)
    nodata[10:13, 8:11] = True
    filled = fill_depressions(dem, nodata)

    sca = mfd_specific_catchment_area(filled, CELL_M)

    padded = np.pad(filled, 1, constant_values=np.nan)
    rows, cols = filled.shape
    terminal = np.zeros(filled.shape, dtype=bool)
    for r in range(rows):
        for c in range(cols):
            if np.isnan(filled[r, c]):
                continue
            neighbours = [
                padded[r + 1 + dr, c + 1 + dc] for dr, dc in NEIGHBOUR_OFFSETS
            ]
            terminal[r, c] = not any(
                not np.isnan(n) and n < filled[r, c] for n in neighbours
            )
    valid_cells = int((~nodata).sum())
    outlet_area = float(sca[terminal].sum() * CELL_M)
    assert outlet_area == pytest.approx(valid_cells * CELL_M * CELL_M, rel=1e-6)
    assert np.isnan(sca[nodata]).all()


@pytest.mark.unit
def test_sca_routes_filled_flat_to_outlet():
    dem = np.full((7, 7), 5.0)
    dem[1:6, 1:6] = 1.0
    dem[6, 3] = 0.0
    filled = fill_depressions(dem, _no_nodata(dem))

    sca = mfd_specific_catchment_area(filled, CELL_M)

    assert sca[6, 3] * CELL_M == pytest.approx(dem.size * CELL_M * CELL_M)


@pytest.mark.unit
def test_freeman_weights_follow_exponent_contour_and_diagonal_distance():
    patch = np.full((3, 3), 11.0)
    patch[1, 1] = 10.0
    patch[2, 1] = 9.9
    patch[2, 2] = 9.9
    padded = _padded(patch)

    weights = _freeman_weights(padded, CELL_M)

    centre = 2 * padded.shape[1] + 2
    south = NEIGHBOUR_OFFSETS.index((1, 0))
    south_east = NEIGHBOUR_OFFSETS.index((1, 1))
    expected_south = (0.1 / CELL_M) ** 1.1 * 0.5
    expected_south_east = (0.1 / (CELL_M * math.sqrt(2.0))) ** 1.1 * 0.354
    assert weights[south, centre] / weights[south_east, centre] == pytest.approx(
        expected_south / expected_south_east, rel=1e-5
    )
    assert weights[:, centre].sum() == pytest.approx(1.0, rel=1e-6)


@pytest.mark.unit
def test_horn_slope_on_oblique_plane_combines_both_axes():
    rows, cols = 9, 9
    y_m, x_m = np.mgrid[0:rows, 0:cols].astype(float) * CELL_M
    dem = 0.03 * x_m + 0.04 * y_m

    slope = horn_slope_percent(dem, CELL_M, _no_nodata(dem))

    np.testing.assert_allclose(slope[1:-1, 1:-1], 5.0)


@pytest.mark.unit
def test_horn_slope_on_one_in_twenty_plane_is_five_percent():
    rows, cols = 9, 9
    dem = np.repeat((np.arange(cols, dtype=float) * CELL_M / 20.0)[None, :], rows, 0)

    slope = horn_slope_percent(dem, CELL_M, _no_nodata(dem))

    np.testing.assert_allclose(slope[1:-1, 1:-1], 5.0)


@pytest.mark.unit
def test_horn_slope_never_nodata_on_edges_or_next_to_nodata():
    dem = _plane_falling_south(6, 6)
    nodata = np.zeros(dem.shape, dtype=bool)
    nodata[3, 3] = True

    slope = horn_slope_percent(dem, CELL_M, nodata)

    assert np.isnan(slope[3, 3])
    assert np.isfinite(slope[~nodata]).all()


@pytest.mark.unit
def test_ls_equals_one_on_unit_plot():
    ls = ls_factor(np.array([22.13]), np.array([9.0]))

    assert ls[0] == pytest.approx(1.0, rel=0.02)


@pytest.mark.unit
def test_ls_matches_closed_form_away_from_unit_plot():
    slope_percent = 100 * math.tan(math.asin(2 * 0.0896))

    ls = ls_factor(np.array([4 * 22.13]), np.array([slope_percent]))

    assert ls[0] == pytest.approx(4**0.4 * 2**1.3, rel=1e-9)


@pytest.mark.unit
def test_ls_uses_sine_of_slope_angle_on_steep_slope():
    ls = ls_factor(np.array([22.13]), np.array([50.0]))

    expected = (math.sin(math.atan(0.5)) / 0.0896) ** 1.3
    assert ls[0] == pytest.approx(expected, rel=1e-9)


@pytest.mark.unit
def test_ls_caps_catchment_area_at_300_m_without_touching_sca():
    sca = np.array([299.0, 300.0, 5000.0])

    ls = ls_factor(sca, np.array([9.0, 9.0, 9.0]))

    expected_cap = (300 / 22.13) ** 0.4 * (math.sin(math.atan(0.09)) / 0.0896) ** 1.3
    assert ls[0] < ls[1]
    assert ls[1] == pytest.approx(expected_cap, rel=1e-9)
    assert ls[2] == pytest.approx(expected_cap, rel=1e-9)
    assert sca[2] == 5000.0


@pytest.mark.unit
def test_ls_propagates_nodata():
    ls = ls_factor(np.array([np.nan, 10.0]), np.array([5.0, np.nan]))

    assert np.isnan(ls).all()
