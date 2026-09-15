"""Tests for the admin panel: Cities CRUD, Service Locations, Travel Leave registration."""
import time
import jdatetime
import pytest

from models.city import City
from models.employee_service_location import EmployeeServiceLocation
from models.leave_request import LeaveRequest
from models.travel_leave_detail import TravelLeaveDetail
from web.services.travel_leave_service import service_location_overlaps
from .conftest import login_as


def _admin_and_user(make_user):
    admin = make_user(role="super_admin", balance_al=None)
    user = make_user(role="user", balance_al=30)
    return admin, user


def _unique_name(prefix="Test City"):
    return f"{prefix} {int(time.time() * 1000) % 100000}"


# ---------------------------------------------------------------------------
# Cities CRUD
# ---------------------------------------------------------------------------

class TestCitiesCRUD:
    @pytest.fixture(autouse=True)
    def _cleanup(self, db):
        yield
        for pattern in ("Test City %", "Add City %", "Edit City %",
                        "Debug City %", "DBG City %"):
            db.query(City).filter(City.name.like(pattern)).delete()
        db.commit()

    def _create_city(self, db, name=None, province="Qom", lat=34.64, lon=50.87):
        name = name or _unique_name()
        city = City(name=name, province=province, latitude=lat, longitude=lon)
        db.add(city)
        db.commit()
        db.refresh(city)
        return city

    def test_admin_manage_cities_permission_keys(self, db):
        from web.permissions import ALL_PERMISSIONS
        assert "manage_cities" in ALL_PERMISSIONS
        assert "manage_service_locations" in ALL_PERMISSIONS
        assert ALL_PERMISSIONS["manage_cities"]["admin"] is True
        assert ALL_PERMISSIONS["manage_cities"]["super_admin"] is True
        assert ALL_PERMISSIONS["manage_service_locations"]["admin"] is True

    def test_city_visible_in_show_all(self, client, db, make_user):
        admin, _ = _admin_and_user(make_user)
        city = self._create_city(db)
        login_as(client, admin["national_code"])
        resp = client.get("/admin/cities?show_all=1")
        assert resp.status_code == 200
        assert city.name in resp.text

    def test_admin_can_add_city(self, client, db, make_user):
        admin, _ = _admin_and_user(make_user)
        login_as(client, admin["national_code"])
        name = _unique_name("Add City")
        resp = client.post(
            "/admin/cities/add",
            data={"name": name, "province": "Fars", "latitude": "29.6",
                  "longitude": "52.5", "is_active": "on"},
            follow_redirects=False,
        )
        assert resp.status_code == 302
        assert "success=" in resp.headers["location"]
        city = db.query(City).filter(City.name == name).first()
        assert city is not None
        assert city.province == "Fars"
        assert city.is_active is True

    def test_duplicate_city_rejected(self, client, db, make_user):
        admin, _ = _admin_and_user(make_user)
        existing = self._create_city(db)
        login_as(client, admin["national_code"])
        resp = client.post(
            "/admin/cities/add",
            data={"name": existing.name, "province": existing.province,
                  "latitude": "34.0", "longitude": "50.0"},
            follow_redirects=False,
        )
        assert resp.status_code == 302
        assert "error=" in resp.headers["location"]
        assert db.query(City).filter(City.name == existing.name).count() == 1

    def test_duplicate_name_different_province_allowed(self, client, db, make_user):
        admin, _ = _admin_and_user(make_user)
        existing = self._create_city(db)
        login_as(client, admin["national_code"])
        resp = client.post(
            "/admin/cities/add",
            data={"name": existing.name, "province": "OtherProvince",
                  "latitude": "34.0", "longitude": "50.0"},
            follow_redirects=False,
        )
        assert resp.status_code == 302
        assert "success=" in resp.headers["location"]

    @pytest.mark.parametrize("lat,lon", [
        ("91", "50"), ("-91", "50"), ("34", "181"), ("34", "-181"),
        ("NaN", "50"), ("Infinity", "50"),
    ])
    def test_invalid_coordinates_rejected(self, client, db, make_user, lat, lon):
        admin, _ = _admin_and_user(make_user)
        login_as(client, admin["national_code"])
        resp = client.post(
            "/admin/cities/add",
            data={"name": _unique_name(), "province": "", "latitude": lat,
                  "longitude": lon},
            follow_redirects=False,
        )
        assert resp.status_code == 302
        assert "error=" in resp.headers["location"]

    def test_empty_name_rejected(self, client, db, make_user):
        admin, _ = _admin_and_user(make_user)
        login_as(client, admin["national_code"])
        resp = client.post(
            "/admin/cities/add",
            data={"name": "   ", "province": "", "latitude": "34",
                  "longitude": "50"},
            follow_redirects=False,
        )
        assert resp.status_code == 302
        assert "error=" in resp.headers["location"]

    def test_admin_can_edit_city(self, client, db, make_user):
        admin, _ = _admin_and_user(make_user)
        city = self._create_city(db, name=_unique_name("Edit City"))
        new_name = f"{city.name}-edited"
        login_as(client, admin["national_code"])
        resp = client.post(
            f"/admin/cities/{city.id}/edit",
            data={"name": new_name, "province": "Fars",
                  "latitude": "30.0", "longitude": "51.0", "is_active": "on"},
            follow_redirects=False,
        )
        assert resp.status_code == 302
        assert "success=" in resp.headers["location"]
        db.expire_all()
        updated = db.query(City).filter(City.id == city.id).first()
        assert updated.name == new_name
        assert updated.latitude == 30.0

    def test_admin_can_toggle_city(self, client, db, make_user):
        admin, _ = _admin_and_user(make_user)
        city = self._create_city(db)
        login_as(client, admin["national_code"])
        resp = client.post(f"/admin/cities/{city.id}/toggle", follow_redirects=False)
        assert resp.status_code == 302
        db.expire_all()
        assert db.query(City).filter(City.id == city.id).first().is_active is False

    def test_non_admin_cannot_manage_cities(self, client, db, make_user):
        admin, user = _admin_and_user(make_user)
        del admin  # use only normal user
        login_as(client, user["national_code"])
        resp = client.get("/admin/cities?show_all=1", follow_redirects=False)
        assert resp.status_code in (302, 403)


# ---------------------------------------------------------------------------
# Service Locations
# ---------------------------------------------------------------------------

class TestServiceLocations:
    def test_admin_can_add_service_location(self, client, db, make_user):
        admin, user = _admin_and_user(make_user)
        city = db.query(City).filter(City.is_active == True).first()
        if not city:
            pytest.skip("No active cities seeded")

        login_as(client, admin["national_code"])
        from_j = (jdatetime.date.today() + jdatetime.timedelta(days=5)).strftime("%Y/%m/%d")
        resp = client.post(
            "/admin/service-locations/add",
            data={
                "user_id": user["user_id"],
                "city_id": str(city.id),
                "address_text": "Head Office",
                "effective_from_str": from_j,
                "effective_to_str": "",
            },
            follow_redirects=False,
        )
        assert resp.status_code == 302
        assert "success=" in resp.headers["location"]
        loc = db.query(EmployeeServiceLocation).filter(
            EmployeeServiceLocation.user_id == user["user_id"]).first()
        assert loc is not None
        assert loc.city_id == city.id

    def test_overlap_rejected(self, client, db, make_user):
        admin, user = _admin_and_user(make_user)
        cities = db.query(City).filter(City.is_active == True).all()
        if len(cities) < 2:
            pytest.skip("Need 2 active cities")

        # Existing open-ended assignment starting tomorrow
        from_g = jdatetime.date.today().togregorian() + jdatetime.timedelta(days=1)
        db.add(EmployeeServiceLocation(
            user_id=user["user_id"], city_id=cities[0].id,
            effective_from=from_g,
        ))
        db.commit()

        login_as(client, admin["national_code"])
        from_j = from_g.strftime("%Y/%m/%d")
        to_j = (from_g + jdatetime.timedelta(days=10)).strftime("%Y/%m/%d")
        resp = client.post(
            "/admin/service-locations/add",
            data={
                "user_id": user["user_id"],
                "city_id": str(cities[1].id),
                "address_text": "",
                "effective_from_str": from_j,
                "effective_to_str": to_j,
            },
            follow_redirects=False,
        )
        assert resp.status_code == 302
        assert "error=" in resp.headers["location"]
        assert db.query(EmployeeServiceLocation).filter(
            EmployeeServiceLocation.user_id == user["user_id"]).count() == 1

    def test_service_location_overlap_helper(self, db, make_user):
        user = make_user()
        city = db.query(City).filter(City.is_active == True).first()
        if not city:
            pytest.skip("No cities")
        from_g = jdatetime.date.today().togregorian() + jdatetime.timedelta(days=1)
        later = from_g + jdatetime.timedelta(days=30)

        # A: closed interval [from_g, from_g+10)
        loc_a = EmployeeServiceLocation(
            user_id=user["user_id"], city_id=city.id,
            effective_from=from_g, effective_to=from_g + jdatetime.timedelta(days=10),
        )
        db.add(loc_a)
        db.commit()

        # New open-ended assignment starting inside A → overlap
        assert service_location_overlaps(db, user["user_id"], from_g + jdatetime.timedelta(days=2), None) is not None

        # A ends exactly at from_g+10 → period starting there does NOT overlap
        after_a = from_g + jdatetime.timedelta(days=10)
        assert service_location_overlaps(db, user["user_id"], after_a, after_a + jdatetime.timedelta(days=2)) is None

        # B starts 30 days later · gap between A end and B start is free
        loc_b = EmployeeServiceLocation(
            user_id=user["user_id"], city_id=city.id,
            effective_from=later, effective_to=later + jdatetime.timedelta(days=5),
        )
        db.add(loc_b)
        db.commit()

        gap_start = later - jdatetime.timedelta(days=5)
        gap_end = later - jdatetime.timedelta(days=1)
        assert service_location_overlaps(db, user["user_id"], gap_start, gap_end) is None

    def test_admin_can_end_open_assignment(self, client, db, make_user):
        admin, user = _admin_and_user(make_user)
        city = db.query(City).filter(City.is_active == True).first()
        if not city:
            pytest.skip("No cities")
        loc = EmployeeServiceLocation(
            user_id=user["user_id"], city_id=city.id,
            effective_from=jdatetime.date.today().togregorian() - jdatetime.timedelta(days=10),
        )
        db.add(loc)
        db.commit()

        login_as(client, admin["national_code"])
        resp = client.post(f"/admin/service-locations/{loc.id}/end", follow_redirects=False)
        assert resp.status_code == 302
        assert "success=" in resp.headers["location"]
        db.expire_all()
        ended = db.query(EmployeeServiceLocation).filter(
            EmployeeServiceLocation.id == loc.id).first()
        assert ended.effective_to is not None

    def test_service_locations_page_requires_permission(self, client, db, make_user):
        admin, user = _admin_and_user(make_user)
        login_as(client, user["national_code"])
        resp = client.get("/admin/service-locations", follow_redirects=False)
        assert resp.status_code in (302, 403)


class TestAdminPagesRender:
    def test_register_form_renders_tl_section(self, client, db, make_user):
        admin, user = _admin_and_user(make_user)
        login_as(client, admin["national_code"])
        resp = client.get("/admin/leave-requests/register")
        assert resp.status_code == 200
        assert resp.text.count('id="tlSection"') == 1
        assert 'name="travel_leave_enabled"' in resp.text
        assert 'name="destination_city_id"' in resp.text

    def test_service_locations_page_renders_for_admin(self, client, db, make_user):
        admin, user = _admin_and_user(make_user)
        city = db.query(City).filter(City.is_active == True).first()
        if not city:
            pytest.skip("No active cities")
        loc = EmployeeServiceLocation(
            user_id=user["user_id"], city_id=city.id,
            effective_from=(jdatetime.date.today().togregorian()
                            - jdatetime.timedelta(days=1)),
        )
        db.add(loc)
        db.commit()
        login_as(client, admin["national_code"])
        resp = client.get(f"/admin/service-locations?user_id={user['user_id']}")
        assert resp.status_code == 200
        assert city.name in resp.text
        assert "تاریخچه محل خدمت" in resp.text


# ---------------------------------------------------------------------------
# Travel Leave via admin register
# ---------------------------------------------------------------------------

class TestAdminTravelLeaveRegister:
    def _dest_city(self, db):
        city = db.query(City).filter(City.is_active == True).first()
        if not city:
            pytest.skip("No active cities")
        return city

    def test_admin_post_travel_leave_creates_detail(self, client, db, make_user):
        admin, user = _admin_and_user(make_user)
        origin_city = db.query(City).filter(City.is_active == True).first()
        if len(db.query(City).filter(City.is_active == True).all()) < 2:
            pytest.skip("Need 2 active cities")
        dest_city = db.query(City).filter(City.is_active == True).all()[1]

        from_g = jdatetime.date.today().togregorian() + jdatetime.timedelta(days=5)
        db.add(EmployeeServiceLocation(
            user_id=user["user_id"], city_id=origin_city.id, effective_from=from_g,
        ))
        db.commit()

        from_j = from_g.strftime("%Y/%m/%d")
        to_j = (from_g + jdatetime.timedelta(days=2)).strftime("%Y/%m/%d")

        login_as(client, admin["national_code"])
        resp = client.post(
            "/admin/leave-requests/register",
            data={
                "target_user_id": user["user_id"],
                "leave_type": "AL",
                "from_date_str": from_j,
                "to_date_str": to_j,
                "reason": "tour",
                "travel_leave_enabled": "on",
                "destination_city_id": str(dest_city.id),
            },
            follow_redirects=False,
        )
        assert resp.status_code == 302
        assert "success=" in resp.headers["location"]

        lr = db.query(LeaveRequest).filter(
            LeaveRequest.user_id == user["user_id"]).first()
        assert lr is not None
        assert lr.status == "P"
        detail = db.query(TravelLeaveDetail).filter(
            TravelLeaveDetail.leave_request_id == lr.id).first()
        assert detail is not None
        assert detail.destination_city_id == dest_city.id
        assert detail.origin_city_id == origin_city.id

    def test_admin_travel_leave_requires_destination(self, client, db, make_user):
        admin, user = _admin_and_user(make_user)
        from_g = jdatetime.date.today().togregorian() + jdatetime.timedelta(days=5)
        from_j = from_g.strftime("%Y/%m/%d")
        to_j = (from_g + jdatetime.timedelta(days=2)).strftime("%Y/%m/%d")

        login_as(client, admin["national_code"])
        resp = client.post(
            "/admin/leave-requests/register",
            data={
                "target_user_id": user["user_id"],
                "leave_type": "AL",
                "from_date_str": from_j,
                "to_date_str": to_j,
                "reason": "",
                "travel_leave_enabled": "on",
                "destination_city_id": "",
            },
            follow_redirects=False,
        )
        assert resp.status_code == 302
        assert "error=" in resp.headers["location"]
        assert db.query(LeaveRequest).filter(
            LeaveRequest.user_id == user["user_id"]).count() == 0

    def test_admin_normal_leave_without_tl(self, client, db, make_user):
        admin, user = _admin_and_user(make_user)
        from_g = jdatetime.date.today().togregorian() + jdatetime.timedelta(days=5)
        from_j = from_g.strftime("%Y/%m/%d")
        to_j = (from_g + jdatetime.timedelta(days=2)).strftime("%Y/%m/%d")

        login_as(client, admin["national_code"])
        resp = client.post(
            "/admin/leave-requests/register",
            data={
                "target_user_id": user["user_id"],
                "leave_type": "AL",
                "from_date_str": from_j,
                "to_date_str": to_j,
                "reason": "",
                "travel_leave_enabled": "off",
                "destination_city_id": "",
            },
            follow_redirects=False,
        )
        assert resp.status_code == 302
        assert "success=" in resp.headers["location"]
        lr = db.query(LeaveRequest).filter(
            LeaveRequest.user_id == user["user_id"]).first()
        assert lr is not None
        detail = db.query(TravelLeaveDetail).filter(
            TravelLeaveDetail.leave_request_id == lr.id).first()
        assert detail is None

    def test_admin_travel_preview_endpoint(self, client, db, make_user):
        admin, user = _admin_and_user(make_user)
        origin_city = db.query(City).filter(City.is_active == True).first()
        if not origin_city:
            pytest.skip("No active cities")
        from_g = jdatetime.date.today().togregorian() + jdatetime.timedelta(days=5)
        db.add(EmployeeServiceLocation(
            user_id=user["user_id"], city_id=origin_city.id,
            effective_from=from_g,
        ))
        db.commit()

        login_as(client, admin["national_code"])
        from_j = from_g.strftime("%Y/%m/%d")
        resp = client.get(
            f"/admin/leave-requests/travel-preview?target_user_id={user['user_id']}"
            f"&from_date={from_j}&destination_city_id={origin_city.id}"
        )
        data = resp.json()
        assert data["success"] is True
        assert "distance_km" in data
        assert "travel_days" in data
        assert data["origin_city"] == origin_city.name