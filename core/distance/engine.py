"""Focused Distance Engine: Haversine straight-line distance in kilometers."""
import math
from typing import Tuple

EARTH_RADIUS_KM = 6371.0  # mean earth radius

def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate great-circle distance between two points on Earth."""
    # Validate basic coordinate ranges
    for val, name in ((lat1,"lat1"),(lat2,"lat2")):
        if not isinstance(val, (int,float)) or val < -90 or val > 90:
            raise ValueError(f"Invalid latitude {name}: {val}")
    for val, name in ((lon1,"lon1"),(lon2,"lon2")):
        if not isinstance(val, (int,float)) or val < -180 or val > 180:
            raise ValueError(f"Invalid longitude {name}: {val}")
    # Convert to radians
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlambda/2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
    return EARTH_RADIUS_KM * c

def calculate_distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Public interface: deterministic Haversine distance in km."""
    return haversine(lat1, lon1, lat2, lon2)
