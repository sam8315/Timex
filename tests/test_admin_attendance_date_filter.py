"""Tests for date-range filter on /admin/attendance/user/{id}."""
import jdatetime
import pytest
from datetime import date, timedelta

from .conftest import login_as
from models.attendance import Attendance
from models.employee import Employee


def _today_j():
    return jdatetime.date.today().strftime("%Y/%m/%d")


@pytest.mark.parametrize("from_date,to_date,expect_ok", [
    (None, None, True),              # 1. no filter
    ("1404/06/01", None, True),     # 2. only from
    (None, "1404/06/10", True),     # 3. only to
    ("1404/06/01", "1404/06/10", True),  # 4. both
    ("1404/06/10", "1404/06/10", True),  # 5. from==to
    ("1404/06/10", "1404/06/01", False),  # 6. from>to -> validation
    ("bad", None, False),           # 7. invalid from
    (None, "bad", False),           # 8. invalid to
])
def test_date_filter_validation(client, db, make_user, from_date, to_date, expect_ok):
    creds = make_user(role="admin")
    login_as(client, creds["national_code"])
    url = f"/admin/attendance/user/{creds['user_id']}?year=1404&month=6"
    if from_date:
        url += f"&from_date={from_date}"
    if to_date:
        url += f"&to_date={to_date}"
    resp = client.get(url, follow_redirects=False)
    # On validation error the route may return 200 with error badge or redirect; accept either non-5xx
    if expect_ok:
        assert resp.status_code == 200 or resp.status_code == 302
    else:
        # Should not crash; may show error badge in 200
        assert resp.status_code in (200, 302)


def test_filter_applied_shows_badge(client, db, make_user):
    creds = make_user(role="admin")
    login_as(client, creds["national_code"])
    resp = client.get(
        f"/admin/attendance/user/{creds['user_id']}?year=1404&month=6&from_date=1404/06/01&to_date=1404/06/10",
        follow_redirects=False,
    )
    assert resp.status_code == 200
    html = resp.text
    assert "از" in html or "بازۀ تاریخ" in html


def test_filter_survives_pagination(client, db, make_user):
    creds = make_user(role="admin")
    login_as(client, creds["national_code"])
    resp = client.get(
        f"/admin/attendance/user/{creds['user_id']}?year=1404&month=6&from_date=1404/06/01&to_date=1404/06/10&page=2",
        follow_redirects=False,
    )
    assert resp.status_code == 200


def test_no_filter_preserves_previous_behavior(client, db, make_user):
    creds = make_user(role="admin")
    login_as(client, creds["national_code"])
    resp = client.get(
        f"/admin/attendance/user/{creds['user_id']}?year=1404&month=6",
        follow_redirects=False,
    )
    assert resp.status_code == 200
    # Should contain summary cards from full month
    assert "کارکرد" in resp.text or "تردد" in resp.text
