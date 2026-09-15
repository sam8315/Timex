"""Focused tests for the Travel Leave feature."""
import math
from datetime import date, timedelta

import jdatetime
import pytest

from core.distance_engine import haversine_km, calculate_distance_km
from web.services.travel_leave_service import (
    calculate_travel_days,
    check_quota,
    count_approved_travel_leaves_in_year,
    create_travel_leave_detail,
    get_active_cities,
    get_quota_setting,
    resolve_effective_service_location,
    validate_destination_city,
    override_travel_days,
)
from models.city import City
from models.employee_service_location import EmployeeServiceLocation
from models.leave_request import LeaveRequest
from models.travel_leave_detail import TravelLeaveDetail
from models.travel_leave_policy_rules import TravelLeavePolicyRule, TravelLeaveQuotaSetting


# ---------------------------------------------------------------------------
# Distance engine
# ---------------------------------------------------------------------------

class TestDistanceEngine:
    def test_tehran_to_mashhad(self):
        """Tehran to Mashhad ≈ 742 km straight-line."""
        d = haversine_km(35.6892, 51.3890, 36.2972, 59.6067)
        assert 740 < d < 745

    def test_same_point_is_zero(self):
        assert haversine_km(35.0, 51.0, 35.0, 51.0) == 0.0

    def test_calculate_distance_km_wrapper(self):
        d = calculate_distance_km((35.6892, 51.3890), (36.2972, 59.6067))
        assert 740 < d < 745

    def test_nan_raises(self):
        with pytest.raises(ValueError, match="not finite"):
            haversine_km(float("nan"), 51.0, 35.0, 51.0)

    def test_infinity_raises(self):
        with pytest.raises(ValueError, match="not finite"):
            haversine_km(float("inf"), 51.0, 35.0, 51.0)

    def test_lat_out_of_range(self):
        with pytest.raises(ValueError, match="out of range"):
            haversine_km(91.0, 51.0, 35.0, 51.0)

    def test_lon_out_of_range(self):
        with pytest.raises(ValueError, match="out of range"):
            haversine_km(35.0, 181.0, 35.0, 51.0)


# ---------------------------------------------------------------------------
# Travel days calculation
# ---------------------------------------------------------------------------

class TestTravelDaysCalculation:
    @pytest.fixture(autouse=True)
    def setup_rules(self, db):
        self.rules = [
            TravelLeavePolicyRule(min_km=0.0, max_km=199.99, travel_days=0, is_active=1),
            TravelLeavePolicyRule(min_km=200.0, max_km=500.0, travel_days=1, is_active=1),
            TravelLeavePolicyRule(min_km=500.01, max_km=1500.0, travel_days=2, is_active=1),
            TravelLeavePolicyRule(min_km=1500.01, max_km=99999.0, travel_days=3, is_active=1),
        ]

    def test_below_200km(self):
        days, rule = calculate_travel_days(199.0, self.rules)
        assert days == 0
        assert rule is not None

    def test_exactly_200km(self):
        days, rule = calculate_travel_days(200.0, self.rules)
        assert days == 1

    def test_500km(self):
        days, rule = calculate_travel_days(500.0, self.rules)
        assert days == 1

    def test_501km(self):
        days, rule = calculate_travel_days(501.0, self.rules)
        assert days == 2

    def test_1500km(self):
        days, rule = calculate_travel_days(1500.0, self.rules)
        assert days == 2

    def test_1501km(self):
        days, rule = calculate_travel_days(1501.0, self.rules)
        assert days == 3

    def test_large_distance(self):
        days, rule = calculate_travel_days(5000.0, self.rules)
        assert days == 3


# ---------------------------------------------------------------------------
# Service location resolution
# ---------------------------------------------------------------------------

class TestServiceLocationResolution:
    def test_no_location_returns_none(self, db, make_user):
        u = make_user()
        result = resolve_effective_service_location(db, u["user_id"], date.today())
        assert result is None

    def test_single_effective_location(self, db, make_user):
        u = make_user()
        city = db.query(City).first()
        if not city:
            pytest.skip("No cities seeded")
        esl = EmployeeServiceLocation(
            user_id=u["user_id"], city_id=city.id,
            effective_from=date(2020, 1, 1),
        )
        db.add(esl)
        db.commit()

        result = resolve_effective_service_location(db, u["user_id"], date(2025, 6, 1))
        assert result is not None
        assert result.city_id == city.id

    def test_expired_location_returns_none(self, db, make_user):
        u = make_user()
        city = db.query(City).first()
        if not city:
            pytest.skip("No cities seeded")
        esl = EmployeeServiceLocation(
            user_id=u["user_id"], city_id=city.id,
            effective_from=date(2020, 1, 1),
            effective_to=date(2021, 1, 1),
        )
        db.add(esl)
        db.commit()

        result = resolve_effective_service_location(db, u["user_id"], date(2025, 6, 1))
        assert result is None


# ---------------------------------------------------------------------------
# Destination validation
# ---------------------------------------------------------------------------

class TestDestinationValidation:
    def test_valid_active_city(self, db):
        city = db.query(City).filter(City.is_active == True).first()
        if not city:
            pytest.skip("No active cities")
        result = validate_destination_city(db, city.id)
        assert result is not None
        assert result.id == city.id

    def test_nonexistent_city(self, db):
        result = validate_destination_city(db, 999999)
        assert result is None


# ---------------------------------------------------------------------------
# Quota
# ---------------------------------------------------------------------------

class TestQuota:
    def test_check_quota_initial(self, db, make_user):
        u = make_user()
        allowed, used, max_allowed = check_quota(db, u["user_id"], 1405)
        assert allowed is True
        assert used == 0
        assert max_allowed >= 1


# ---------------------------------------------------------------------------
# Integration: create_travel_leave_detail
# ---------------------------------------------------------------------------

class TestCreateTravelLeaveDetail:
    def _setup_travel_leave(self, db, user_id):
        """Helper: set up city, ESL, and return (origin_city, dest_city)."""
        cities = get_active_cities(db)
        if len(cities) < 2:
            pytest.skip("Need at least 2 active cities")
        origin_city = cities[0]
        dest_city = cities[1]

        esl = EmployeeServiceLocation(
            user_id=user_id, city_id=origin_city.id,
            effective_from=date(2020, 1, 1),
        )
        db.add(esl)
        db.commit()
        return origin_city, dest_city

    def test_successful_creation(self, db, make_user):
        u = make_user()
        origin_city, dest_city = self._setup_travel_leave(db, u["user_id"])

        today_j = jdatetime.date.today()
        from_j = today_j + timedelta(days=5)
        from_g = from_j.togregorian()

        lr = LeaveRequest(
            user_id=u["user_id"], leave_type="AL",
            from_date=from_g, to_date=from_g,
            days_count=1, status="P",
        )
        db.add(lr)
        db.commit()

        detail = create_travel_leave_detail(db, lr, dest_city.id)
        assert detail is not None
        assert detail.leave_request_id == lr.id
        assert detail.distance_km > 0
        assert detail.calculated_travel_days >= 0
        assert detail.final_travel_days >= 0
        assert detail.jalali_year == from_j.year

    def test_rejects_non_al(self, db, make_user):
        u = make_user()
        origin_city, dest_city = self._setup_travel_leave(db, u["user_id"])

        lr = LeaveRequest(
            user_id=u["user_id"], leave_type="SL",
            from_date=date.today(), to_date=date.today(),
            days_count=1, status="P",
        )
        db.add(lr)
        db.commit()

        with pytest.raises(ValueError, match="only available for Annual Leave"):
            create_travel_leave_detail(db, lr, dest_city.id)

    def test_rejects_no_service_location(self, db, make_user):
        u = make_user()
        cities = get_active_cities(db)
        if not cities:
            pytest.skip("No cities")
        dest_city = cities[0]

        today_j = jdatetime.date.today()
        from_g = (today_j + timedelta(days=5)).togregorian()

        lr = LeaveRequest(
            user_id=u["user_id"], leave_type="AL",
            from_date=from_g, to_date=from_g,
            days_count=1, status="P",
        )
        db.add(lr)
        db.commit()

        with pytest.raises(ValueError, match="محل خدمت"):
            create_travel_leave_detail(db, lr, dest_city.id)


# ---------------------------------------------------------------------------
# Admin override
# ---------------------------------------------------------------------------

class TestAdminOverride:
    def test_override_pending_request(self, db, make_user):
        u = make_user()
        cities = get_active_cities(db)
        if len(cities) < 2:
            pytest.skip("Need cities")

        origin_city, dest_city = cities[0], cities[1]
        esl = EmployeeServiceLocation(
            user_id=u["user_id"], city_id=origin_city.id,
            effective_from=date(2020, 1, 1),
        )
        db.add(esl)
        db.commit()

        today_j = jdatetime.date.today()
        from_g = (today_j + timedelta(days=5)).togregorian()

        lr = LeaveRequest(
            user_id=u["user_id"], leave_type="AL",
            from_date=from_g, to_date=from_g,
            days_count=1, status="P",
        )
        db.add(lr)
        db.commit()

        detail = create_travel_leave_detail(db, lr, dest_city.id)
        db.commit()

        original_calc = detail.calculated_travel_days
        override_travel_days(db, detail.id, 2, "admin001", "Need more days")
        db.commit()

        db.refresh(detail)
        assert detail.manual_override is True
        assert detail.final_travel_days == 2
        assert detail.calculated_travel_days == original_calc
        assert detail.overridden_by == "admin001"
        assert detail.override_reason == "Need more days"
        assert detail.overridden_at is not None

    def test_override_rejects_approved_request(self, db, make_user):
        u = make_user()
        cities = get_active_cities(db)
        if len(cities) < 2:
            pytest.skip("Need cities")

        origin_city, dest_city = cities[0], cities[1]
        esl = EmployeeServiceLocation(
            user_id=u["user_id"], city_id=origin_city.id,
            effective_from=date(2020, 1, 1),
        )
        db.add(esl)
        db.commit()

        today_j = jdatetime.date.today()
        from_g = (today_j + timedelta(days=5)).togregorian()

        lr = LeaveRequest(
            user_id=u["user_id"], leave_type="AL",
            from_date=from_g, to_date=from_g,
            days_count=1, status="A",
        )
        db.add(lr)
        db.commit()

        detail = create_travel_leave_detail(db, lr, dest_city.id)
        db.commit()

        with pytest.raises(ValueError, match="در انتظار"):
            override_travel_days(db, detail.id, 2, "admin001", "Reason")

    def test_override_rejects_empty_reason(self, db, make_user):
        u = make_user()
        cities = get_active_cities(db)
        if len(cities) < 2:
            pytest.skip("Need cities")

        origin_city, dest_city = cities[0], cities[1]
        esl = EmployeeServiceLocation(
            user_id=u["user_id"], city_id=origin_city.id,
            effective_from=date(2020, 1, 1),
        )
        db.add(esl)
        db.commit()

        today_j = jdatetime.date.today()
        from_g = (today_j + timedelta(days=5)).togregorian()

        lr = LeaveRequest(
            user_id=u["user_id"], leave_type="AL",
            from_date=from_g, to_date=from_g,
            days_count=1, status="P",
        )
        db.add(lr)
        db.commit()

        detail = create_travel_leave_detail(db, lr, dest_city.id)
        db.commit()

        with pytest.raises(ValueError, match="دلیل"):
            override_travel_days(db, detail.id, 2, "admin001", "")
