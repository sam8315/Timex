"""Deterministic Haversine distance engine (no external services)."""
import math
from typing import Tuple


_EARTH_RADIUS_KM = 6371.0


def haversine_km(
    lat1: float, lon1: float,
    lat2: float, lon2: float,
) -> float:
    """Return the straight-line great-circle distance in km between two points.

    Coordinates must be finite numbers in degree units.
    Raises ValueError if coordinates are non-finite or out of range.
    """
    for name, val in [("lat1", lat1), ("lon1", lon1), ("lat2", lat2), ("lon2", lon2)]:
        if not math.isfinite(val):
            raise ValueError(f"{name} is not finite: {val}")
        if abs(val) > 90 and name.startswith("lat"):
            raise ValueError(f"{name} out of range [-90, 90]: {val}")
        if abs(val) > 180 and name.startswith("lon"):
            raise ValueError(f"{name} out of range [-180, 180]: {val}")

    lat1_r = math.radians(lat1)
    lat2_r = math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)

    a = (
        math.sin(dlat / 2.0) ** 2
        + math.cos(lat1_r) * math.cos(lat2_r) * math.sin(dlon / 2.0) ** 2
    )
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return _EARTH_RADIUS_KM * c


def calculate_distance_km(
    origin: Tuple[float, float],
    destination: Tuple[float, float],
) -> float:
    """Convenience wrapper: calculate_distance_km((lat,lon), (lat,lon))."""
    return haversine_km(origin[0], origin[1], destination[0], destination[1])
