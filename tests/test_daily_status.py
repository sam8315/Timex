"""Tests for daily mission/rest statuses (register / list / report)."""
from datetime import timedelta

import jdatetime

from database.init_db import migrate_data_fixes
from models.daily_status import DailyStatus
from tests.conftest import test_engine
from .conftest import jalali_range, login_as


def _add_status_as_admin(client, target_uid, date_str, code):
    return client.post(
        "/admin/daily-status/add",
        data={"user_id": target_uid, "date_str": date_str,
              "status_code": code, "description": ""},
        follow_redirects=False,
    )


def test_add_trims_status_code(client, db, make_user):
    boss = make_user(role="super_admin", balance_al=None)
    target = make_user(role="user", balance_al=None)
    login_as(client, boss["national_code"])
    from_str, _ = jalali_range(3, 0)
    resp = _add_status_as_admin(client, target["user_id"], from_str, "R ")
    assert resp.status_code == 302
    assert "success=" in resp.headers["location"]
    db.expire_all()
    row = db.query(DailyStatus).filter(
        DailyStatus.user_id == target["user_id"]).first()
    assert row is not None
    assert row.status_code == "R"


def test_add_rejects_unknown_code(client, make_user):
    boss = make_user(role="super_admin", balance_al=None)
    target = make_user(role="user", balance_al=None)
    login_as(client, boss["national_code"])
    from_str, _ = jalali_range(3, 0)
    resp = _add_status_as_admin(client, target["user_id"], from_str, "XX")
    assert resp.status_code == 302
    assert "error=" in resp.headers["location"]


def test_model_validator_strips_on_assignment(db, make_user):
    target = make_user(role="user", balance_al=None)
    row = DailyStatus(user_id=target["user_id"],
                      status_date=jdatetime.date.today().togregorian(),
                      status_code="M ")
    assert row.status_code == "M"
    row.status_code = " R"
    assert row.status_code == "R"


def test_show_all_spans_months(client, db, make_user):
    boss = make_user(role="super_admin", balance_al=None)
    target = make_user(role="user", balance_al=None)
    login_as(client, boss["national_code"])

    old_g = (jdatetime.date.today() - timedelta(days=40)).togregorian()
    old_j = jdatetime.date.fromgregorian(date=old_g).strftime("%Y/%m/%d")
    resp = _add_status_as_admin(client, target["user_id"], old_j, "R")
    assert "success=" in resp.headers["location"]

    listing = client.get("/admin/daily-status?show_all=1")
    assert listing.status_code == 200
    assert target["user_id"] in listing.text


def test_status_filter_shows_badge(client, db, make_user):
    boss = make_user(role="super_admin", balance_al=None)
    target = make_user(role="user", balance_al=None)
    login_as(client, boss["national_code"])
    from_str, _ = jalali_range(4, 0)
    _add_status_as_admin(client, target["user_id"], from_str, "R")

    day_j = jdatetime.datetime.strptime(from_str, "%Y/%m/%d").date()
    resp = client.get(
        f"/admin/daily-status?status_filter=R&year={day_j.year}"
        f"&month={day_j.month}")
    assert resp.status_code == 200
    assert target["user_id"] in resp.text
    assert "😴 استراحت" in resp.text


from contextlib import contextmanager

from sqlalchemy import text


@contextmanager
def _legacy_wide_column(db):
    """Simulate the legacy schema where status_code accepted padded codes."""
    db.execute(text(
        "ALTER TABLE daily_statuses ALTER COLUMN status_code TYPE TEXT"))
    db.commit()
    try:
        yield
    finally:
        db.execute(text(
            "ALTER TABLE daily_statuses ALTER COLUMN status_code "
            "TYPE VARCHAR(1)"))
        db.commit()


def _make_dirty_status(db, user_id, status_date):
    """Simulate legacy dirt (trailing space) via raw SQL (bypasses validator)."""
    row_id = db.execute(
        text("INSERT INTO daily_statuses (user_id, status_date, status_code) "
             "VALUES (:u, :d, 'R ') RETURNING id"),
        {"u": user_id, "d": status_date},
    ).scalar()
    db.commit()
    return row_id


def test_migrate_data_fixes_trims_codes(db, make_user):
    target = make_user(role="user", balance_al=None)
    day = jdatetime.date.today().togregorian()
    with _legacy_wide_column(db):
        row_id = _make_dirty_status(db, target["user_id"], day)
        db.expire_all()
        assert db.query(DailyStatus).filter(
            DailyStatus.id == row_id).first().status_code == "R "
        migrate_data_fixes(bind_engine=test_engine)
        db.expire_all()
        assert db.query(DailyStatus).filter(
            DailyStatus.id == row_id).first().status_code == "R"


def test_day_code_tolerates_padded_status():
    from web.routes.reports import get_day_code

    day = jdatetime.date.today().togregorian()
    assert get_day_code(day, {}, {day: "R "}, set(), False, False,
                        hire_date=None, contract_end_date=None) == "اس"
    assert get_day_code(day, {}, {day: "M "}, set(), False, False,
                        hire_date=None, contract_end_date=None) == "م"


def test_dirty_code_still_renders_badge(client, db, make_user):
    boss = make_user(role="super_admin", balance_al=None)
    target = make_user(role="user", balance_al=None)
    day_j = jdatetime.date.today() + timedelta(days=6)
    day_g = day_j.togregorian()

    with _legacy_wide_column(db):
        _make_dirty_status(db, target["user_id"], day_g)

        login_as(client, boss["national_code"])
        # بدون فیلتر وضعیت (فیلتر دقیق، رکورد کثیف را پیدا نمی‌کند)
        listing = client.get("/admin/daily-status?show_all=1")
        assert listing.status_code == 200
        assert target["user_id"] in listing.text
        # بج استراحت دقیقاً یک‌بار (برای همین رکورد) رندر شده است
        assert listing.text.count("😴 استراحت") == 1
