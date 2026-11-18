"""Terrain hydrology on a regular metric grid: fill, MFD routing, slope, LS.

Pure functions on numpy arrays, written from the published methods:

- Priority-Flood + epsilon depression filling (Barnes, Lehman & Mulla, 2014).
- Multiple-flow-direction routing with exponent 1.1 (Freeman, 1991), using
  Quinn et al. (1991) contour-length factors.
- Horn (1981) 3x3 slope.
- LS factor of Moore & Burch (1986).

Every function takes and returns 2-D float64 arrays in which NaN marks
nodata. The two sequential algorithms (fill and accumulation) walk the grid
cell by cell, so they work on a one-cell NaN-padded copy (no bounds checks,
neighbours are fixed linear offsets) and touch the numpy buffers through
``memoryview``. Indexing a memoryview returns plain Python floats several
times faster than numpy scalar indexing, without copying the grid into
Python lists.
"""

from __future__ import annotations

import heapq
import math

import numpy as np
from numpy.typing import NDArray

DEFAULT_FILL_EPSILON_M: float = 1e-4
FREEMAN_EXPONENT: float = 1.1
CARDINAL_CONTOUR_FACTOR: float = 0.5
DIAGONAL_CONTOUR_FACTOR: float = 0.354
LS_UNIT_PLOT_LENGTH_M: float = 22.13
LS_UNIT_PLOT_SIN_SLOPE: float = 0.0896
LS_AREA_EXPONENT: float = 0.4
LS_SLOPE_EXPONENT: float = 1.3
DEFAULT_SCA_CAP_M: float = 300.0

NEIGHBOUR_OFFSETS: tuple[tuple[int, int], ...] = (
    (-1, -1),
    (-1, 0),
    (-1, 1),
    (0, -1),
    (0, 1),
    (1, -1),
    (1, 0),
    (1, 1),
)


def _padded(grid: NDArray[np.float64]) -> NDArray[np.float64]:
    return np.pad(grid.astype(np.float64), 1, constant_values=np.nan)


def _linear_offsets(padded_cols: int) -> list[int]:
    return [dr * padded_cols + dc for dr, dc in NEIGHBOUR_OFFSETS]


def _unpad(padded: NDArray[np.float64]) -> NDArray[np.float64]:
    return padded[1:-1, 1:-1].copy()


def with_nodata(
    dem: NDArray[np.floating], nodata_mask: NDArray[np.bool_]
) -> NDArray[np.float64]:
    """Return ``dem`` as float64 with NaN wherever ``nodata_mask`` is set."""
    return np.where(nodata_mask, np.nan, dem.astype(np.float64))


def fill_depressions(
    dem: NDArray[np.floating],
    nodata_mask: NDArray[np.bool_],
    eps: float = DEFAULT_FILL_EPSILON_M,
) -> NDArray[np.float64]:
    """Fill every closed depression so each valid cell drains to an outlet.

    Outlets are the valid cells on the grid edge or next to a nodata cell.
    Cells are visited from the lowest outlet upwards; a cell no higher than
    the cell that reached it is raised to that cell's elevation plus ``eps``,
    so filled flats keep a strictly decreasing path to an outlet.

    Returns:
        The filled elevations, NaN on nodata cells.
    """
    padded = _padded(with_nodata(dem, nodata_mask))
    padded_cols = padded.shape[1]
    invalid = np.isnan(padded)

    outlet = np.zeros_like(invalid)
    shifted_invalid = np.pad(invalid, 1, constant_values=True)
    rows, cols = invalid.shape
    for dr, dc in NEIGHBOUR_OFFSETS:
        outlet |= shifted_invalid[1 + dr : 1 + dr + rows, 1 + dc : 1 + dc + cols]
    outlet &= ~invalid

    elevation = memoryview(padded.reshape(-1))
    visited = bytearray(invalid.reshape(-1).tobytes())
    offsets = _linear_offsets(padded_cols)

    heap: list[tuple[float, int]] = []
    for cell in np.flatnonzero(outlet).tolist():
        visited[cell] = 1
        heap.append((elevation[cell], cell))
    heapq.heapify(heap)

    heappush = heapq.heappush
    heappop = heapq.heappop
    while heap:
        level, cell = heappop(heap)
        for offset in offsets:
            neighbour = cell + offset
            if visited[neighbour]:
                continue
            visited[neighbour] = 1
            height = elevation[neighbour]
            if height <= level:
                height = level + eps
                elevation[neighbour] = height
            heappush(heap, (height, neighbour))

    return _unpad(padded)


def _freeman_weights(
    padded: NDArray[np.float64], cell_size: float
) -> NDArray[np.float32]:
    """Return the normalised downslope weights, shape (8, cells), float32."""
    rows, cols = padded.shape
    valid = ~np.isnan(padded)
    weights = np.zeros((len(NEIGHBOUR_OFFSETS), rows, cols), dtype=np.float32)
    framed = np.pad(padded, 1, constant_values=np.nan)
    for k, (dr, dc) in enumerate(NEIGHBOUR_OFFSETS):
        diagonal = dr != 0 and dc != 0
        distance = cell_size * (math.sqrt(2.0) if diagonal else 1.0)
        contour = DIAGONAL_CONTOUR_FACTOR if diagonal else CARDINAL_CONTOUR_FACTOR
        neighbour = framed[1 + dr : 1 + dr + rows, 1 + dc : 1 + dc + cols]
        with np.errstate(invalid="ignore"):
            drop = padded - neighbour
            downslope = valid & (drop > 0)
        gradient = np.where(downslope, drop, 0.0) / distance
        weights[k] = np.where(
            downslope, np.power(gradient, FREEMAN_EXPONENT) * contour, 0.0
        )
    total = weights.sum(axis=0)
    draining = total > 0
    weights[:, draining] /= total[draining]
    return weights.reshape(len(NEIGHBOUR_OFFSETS), -1)


def mfd_specific_catchment_area(
    filled: NDArray[np.floating], cell_size: float
) -> NDArray[np.float64]:
    """Return the specific catchment area (m) of each cell of a filled DEM.

    Each cell starts with its own area and passes everything it holds to its
    lower neighbours, split by Freeman MFD weights. Cells are processed from
    the highest down, so a cell is complete before it passes its area on. The
    result is the upslope area per unit contour width (area / cell_size).

    Returns:
        Specific catchment area in metres (m²/m), NaN on nodata cells.
    """
    padded = _padded(np.asarray(filled))
    valid = ~np.isnan(padded)
    weights = _freeman_weights(padded, cell_size)
    offsets = _linear_offsets(padded.shape[1])

    area = np.where(valid, cell_size * cell_size, 0.0).reshape(-1)
    flat_elevation = padded.reshape(-1)
    valid_cells = np.flatnonzero(valid.reshape(-1))
    order = valid_cells[np.argsort(-flat_elevation[valid_cells], kind="stable")]

    draining = weights.any(axis=0)
    accumulated = memoryview(area)
    weight_views = [memoryview(weights[k]) for k in range(len(offsets))]
    routes = list(zip(offsets, weight_views))
    is_draining = memoryview(draining.view(np.uint8))

    for cell in memoryview(order):
        if not is_draining[cell]:
            continue
        held = accumulated[cell]
        for offset, weight_view in routes:
            share = weight_view[cell]
            if share:
                accumulated[cell + offset] += held * share

    sca = area.reshape(padded.shape) / cell_size
    sca[~valid] = np.nan
    return _unpad(sca)


def horn_slope_percent(
    dem: NDArray[np.floating], cell_size: float, nodata_mask: NDArray[np.bool_]
) -> NDArray[np.float64]:
    """Return Horn (1981) slope in percent (rise / run x 100).

    A neighbour outside the grid or on nodata takes the centre cell's value,
    so edge cells always get a slope.

    Returns:
        Slope in percent, NaN on nodata cells.
    """
    centre = with_nodata(dem, nodata_mask)
    padded = _padded(centre)
    rows, cols = centre.shape

    def window(dr: int, dc: int) -> NDArray[np.float64]:
        neighbour = padded[1 + dr : 1 + dr + rows, 1 + dc : 1 + dc + cols]
        return np.where(np.isnan(neighbour), centre, neighbour)

    a, b, c = window(-1, -1), window(-1, 0), window(-1, 1)
    d, f = window(0, -1), window(0, 1)
    g, h, i = window(1, -1), window(1, 0), window(1, 1)
    dz_dx = ((c + 2 * f + i) - (a + 2 * d + g)) / (8 * cell_size)
    dz_dy = ((g + 2 * h + i) - (a + 2 * b + c)) / (8 * cell_size)
    slope = 100.0 * np.hypot(dz_dx, dz_dy)
    slope[nodata_mask] = np.nan
    return slope


def ls_factor(
    sca: NDArray[np.floating],
    slope_percent: NDArray[np.floating],
    sca_cap: float = DEFAULT_SCA_CAP_M,
) -> NDArray[np.float64]:
    """Return the dimensionless RUSLE LS factor (Moore & Burch, 1986).

    LS = (As / 22.13)^0.4 x (sin(beta) / 0.0896)^1.3, with As the specific
    catchment area capped at ``sca_cap`` (the RUSLE slope-length validity
    limit) and beta the slope angle.

    Returns:
        LS, NaN where either input is NaN.
    """
    capped = np.minimum(np.asarray(sca, dtype=np.float64), sca_cap)
    sin_slope = np.sin(np.arctan(np.asarray(slope_percent, dtype=np.float64) / 100))
    return np.power(capped / LS_UNIT_PLOT_LENGTH_M, LS_AREA_EXPONENT) * np.power(
        sin_slope / LS_UNIT_PLOT_SIN_SLOPE, LS_SLOPE_EXPONENT
    )
