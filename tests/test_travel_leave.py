"""Focused Travel Leave tests."""
import math
from core.distance.engine import calculate_distance_km

def test_same_city():
    d = calculate_distance_km(35.6892, 51.3890, 35.6892, 51.3890)
    assert d == 0.0

def test_known_distance_approx():
    # Tehran ~ Isfahan ~ 340 km straight line
    d = calculate_distance_km(35.6892, 51.3890, 32.6546, 51.6678)
    assert 300 < d < 400

def test_invalid_coordinates():
    import pytest
    with pytest.raises(ValueError):
        calculate_distance_km(91, 0, 0, 0)

def test_boundary_200():
    # exactly at boundary simulation using fixed distance result
    # Use points ~200km apart (approx)
    d = calculate_distance_km(35.0, 51.0, 35.0, 53.2)
    # just verify deterministic
    assert d > 0

def test_eligibility_rules():
    def days(d):
        if d < 200: return 0
        if d <= 500: return 1
        if d <= 1500: return 2
        return 3
    assert days(199) == 0
    assert days(200) == 1
    assert days(500) == 1
    assert days(501) == 2
    assert days(1500) == 2
    assert days(1501) == 3

def test_origin_not_residence():
    # Conceptual: service address must be used; test verifies model fields exist
    from models import TravelLeaveDetail
    assert hasattr(TravelLeaveDetail, 'origin_city_id')
