"""
Agronomic climate indicator functions.

All functions operate on numpy arrays in °C or mm/day (after unit conversion).
Scalar indicators (frost_days, heat_stress_days, pr_total, pr_days) return a
single int or float summarising the full period. Array indicators (gdd) return
an array of the same length as the input time axis.
"""

from __future__ import annotations

import numpy as np


def calc_growing_degree_days(
    tasmax: np.ndarray,
    tasmin: np.ndarray,
    base_temp: float = 5.0,
) -> np.ndarray:
    """Compute daily Growing Degree Days (GDD).

    GDD_i = max(0, (tasmax_i + tasmin_i) / 2 - base_temp)

    Args:
        tasmax: Daily maximum temperature array in °C.
        tasmin: Daily minimum temperature array in °C.
        base_temp: Base temperature threshold in °C (default 5.0).

    Returns:
        Array of daily GDD values (same length as inputs, dtype float64).
    """
    mean_temp = (
        np.asarray(tasmax, dtype=np.float64) + np.asarray(tasmin, dtype=np.float64)
    ) / 2.0
    return np.maximum(0.0, mean_temp - base_temp)


def calc_frost_days(tasmin: np.ndarray) -> int:
    """Count days where daily minimum temperature is below 0 °C.

    Args:
        tasmin: Daily minimum temperature array in °C.

    Returns:
        Number of frost days (integer).
    """
    arr = np.asarray(tasmin, dtype=np.float64)
    return int(np.sum(arr < 0.0))


def calc_heat_stress_days(tasmax: np.ndarray, threshold: float = 30.0) -> int:
    """Count days where daily maximum temperature exceeds a threshold.

    Args:
        tasmax: Daily maximum temperature array in °C.
        threshold: Heat stress threshold in °C (default 30.0).

    Returns:
        Number of heat stress days (integer).
    """
    arr = np.asarray(tasmax, dtype=np.float64)
    return int(np.sum(arr > threshold))


def calc_precipitation_total(pr: np.ndarray) -> float:
    """Compute total precipitation over the period.

    Args:
        pr: Daily precipitation array in mm/day.

    Returns:
        Total precipitation in mm (float, NaN values ignored).
    """
    arr = np.asarray(pr, dtype=np.float64)
    return float(np.nansum(arr))


def calc_precipitation_days(pr: np.ndarray, threshold: float = 1.0) -> int:
    """Count days with precipitation above a threshold.

    Args:
        pr: Daily precipitation array in mm/day.
        threshold: Minimum precipitation to count a wet day in mm/day (default 1.0).

    Returns:
        Number of precipitation days (integer).
    """
    arr = np.asarray(pr, dtype=np.float64)
    return int(np.sum(arr > threshold))
