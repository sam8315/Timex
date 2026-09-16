"""Tests for daily mission/rest statuses (register / list / report)."""
from datetime import timedelta

import jdatetime

from database.init_db import migrate_data_fixes
from models.daily_status import DailyStatus
from models.employee import Employee
from tests.conftest import test_engine
from .conftest import jalali_range, login_as


def _add_status_as_admin(client, target_uid, date_str, code):
    return client.post(
        "/admin/daily-status/add",
        data={"user_id": target_uid, "from_date": date_str,
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
    assert "استراحت" in resp.text


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
        # The legacy badge has a stable CSS/text representation without relying
        # on an emoji glyph.
        assert listing.text.count('<span class="badge bg-info text-dark">استراحت</span>') == 1


# ===== New tests for date-range registration & UX =====

def _add_status_range(client, target_uid, from_date, to_date, code):
    """Helper to post date-range form."""
    data = {"user_id": target_uid, "from_date": from_date, "status_code": code, "description": ""}
    if to_date:
        data["to_date"] = to_date
    return client.post("/admin/daily-status/add", data=data, follow_redirects=False)


def test_single_day_registration(client, db, make_user):
    """Registering with only from_date should create single-day record."""
    boss = make_user(role="super_admin", balance_al=None)
    target = make_user(role="user", balance_al=None)
    login_as(client, boss["national_code"])
    today_str, _ = jalali_range(0, 0)

    resp = _add_status_range(client, target["user_id"], today_str, None, "M")
    assert resp.status_code == 302
    assert "success=" in resp.headers["location"]

    db.expire_all()
    rows = db.query(DailyStatus).filter(DailyStatus.user_id == target["user_id"]).all()
    assert len(rows) == 1
    assert rows[0].status_code == "M"


def test_multi_day_registration(client, db, make_user):
    """Registering with from_date and to_date should create records for all days in range."""
    boss = make_user(role="super_admin", balance_al=None)
    target = make_user(role="user", balance_al=None)
    login_as(client, boss["national_code"])
    from_str = jalali_range(0, 0)[0]   # today
    to_str = jalali_range(2, 0)[0]     # 2 days from now

    resp = _add_status_range(client, target["user_id"], from_str, to_str, "R")
    assert resp.status_code == 302
    assert "success=" in resp.headers["location"]

    db.expire_all()
    rows = db.query(DailyStatus).filter(DailyStatus.user_id == target["user_id"]).all()
    assert len(rows) == 3  # 3 days inclusive
    for r in rows:
        assert r.status_code == "R"


def test_same_from_to_date(client, db, make_user):
    """from_date == to_date should create exactly one record."""
    boss = make_user(role="super_admin", balance_al=None)
    target = make_user(role="user", balance_al=None)
    login_as(client, boss["national_code"])
    today_str = jalali_range(0, 0)[0]

    resp = _add_status_range(client, target["user_id"], today_str, today_str, "M")
    assert resp.status_code == 302

    db.expire_all()
    rows = db.query(DailyStatus).filter(DailyStatus.user_id == target["user_id"]).all()
    assert len(rows) == 1


def test_invalid_date_range_rejected(client, db, make_user):
    """from_date > to_date should be rejected."""
    boss = make_user(role="super_admin", balance_al=None)
    target = make_user(role="user", balance_al=None)
    login_as(client, boss["national_code"])
    from_str = jalali_range(2, 0)[0]   # 2 days from now
    to_str = jalali_range(0, 0)[0]     # today

    resp = _add_status_range(client, target["user_id"], from_str, to_str, "M")
    assert resp.status_code == 302
    assert "error=" in resp.headers["location"]

    db.expire_all()
    rows = db.query(DailyStatus).filter(DailyStatus.user_id == target["user_id"]).all()
    assert len(rows) == 0


def test_conflict_inside_range_rejected(client, db, make_user):
    """If any date in range already has a status, whole operation should be rejected."""
    boss = make_user(role="super_admin", balance_al=None)
    target = make_user(role="user", balance_al=None)
    login_as(client, boss["national_code"])

    # Pre-create a status for day 1 (middle of range)
    mid_str = jalali_range(1, 0)[0]
    resp = _add_status_range(client, target["user_id"], mid_str, None, "M")
    assert "success=" in resp.headers["location"]

    # Now try to register a 3-day range that includes the middle day
    from_str = jalali_range(0, 0)[0]
    to_str = jalali_range(2, 0)[0]
    resp = _add_status_range(client, target["user_id"], from_str, to_str, "R")
    assert resp.status_code == 302
    assert "error=" in resp.headers["location"]

    # No new records should be created (atomic rollback)
    db.expire_all()
    rows = db.query(DailyStatus).filter(DailyStatus.user_id == target["user_id"]).all()
    assert len(rows) == 1  # Only the pre-existing one


def test_atomic_rollback_no_partial_records(client, db, make_user):
    """On conflict, no partial records should be created."""
    boss = make_user(role="super_admin", balance_al=None)
    target = make_user(role="user", balance_al=None)
    login_as(client, boss["national_code"])

    # Pre-create for day 0
    today_str, _ = jalali_range(0, 0)
    _add_status_range(client, target["user_id"], today_str, None, "M")

    # Try 3-day range including today
    from_str, _ = jalali_range(2, 0)
    to_str, _ = jalali_range(0, 0)
    resp = _add_status_range(client, target["user_id"], from_str, to_str, "R")
    assert "error=" in resp.headers["location"]

    db.expire_all()
    rows = db.query(DailyStatus).filter(DailyStatus.user_id == target["user_id"]).all()
    assert len(rows) == 1


def test_edit_daily_status(client, db, make_user):
    """Editing an existing record should update it."""
    boss = make_user(role="super_admin", balance_al=None)
    target = make_user(role="user", balance_al=None)
    login_as(client, boss["national_code"])
    today_str, _ = jalali_range(0, 0)

    # Create initial record
    resp = _add_status_range(client, target["user_id"], today_str, None, "M")
    assert "success=" in resp.headers["location"]

    db.expire_all()
    row = db.query(DailyStatus).filter(DailyStatus.user_id == target["user_id"]).first()
    assert row.status_code == "M"
    status_id = row.id

    # Edit: change to R and update description
    resp = client.post(
        f"/admin/daily-status/{status_id}/edit",
        data={"user_id": target["user_id"], "date_str": today_str,
              "status_code": "R", "description": "Updated desc"},
        follow_redirects=False
    )
    assert resp.status_code == 302
    assert "success=" in resp.headers["location"]

    db.expire_all()
    row = db.query(DailyStatus).filter(DailyStatus.id == status_id).first()
    assert row.status_code == "R"
    assert row.description == "Updated desc"


def test_delete_daily_status(client, db, make_user):
    """Deleting a record should remove it."""
    boss = make_user(role="super_admin", balance_al=None)
    target = make_user(role="user", balance_al=None)
    login_as(client, boss["national_code"])
    today_str, _ = jalali_range(0, 0)

    resp = _add_status_range(client, target["user_id"], today_str, None, "M")
    assert "success=" in resp.headers["location"]

    db.expire_all()
    row = db.query(DailyStatus).filter(DailyStatus.user_id == target["user_id"]).first()
    status_id = row.id

    # Delete
    resp = client.post(f"/admin/daily-status/{status_id}/delete", follow_redirects=False)
    assert resp.status_code == 302
    assert "success=" in resp.headers["location"]

    db.expire_all()
    row = db.query(DailyStatus).filter(DailyStatus.id == status_id).first()
    assert row is None


def test_default_current_month_display(client, db, make_user):
    """Page should default to the current Jalali month."""
    boss = make_user(role="super_admin", balance_al=None)
    target = make_user(role="user", balance_al=None)
    login_as(client, boss["national_code"])
    today_str = jalali_range(0, 0)[0]
    today = jdatetime.datetime.strptime(today_str, "%Y/%m/%d").date()

    resp = _add_status_range(client, target["user_id"], today_str, None, "M")
    assert "success=" in resp.headers["location"]

    resp = client.get("/admin/daily-status")
    assert resp.status_code == 200
    assert today_str in resp.text
    assert f'<option value="{today.year}" selected>{today.year}</option>' in resp.text
    month_names = {
        1: "فروردین", 2: "اردیبهشت", 3: "خرداد", 4: "تیر",
        5: "مرداد", 6: "شهریور", 7: "مهر", 8: "آبان",
        9: "آذر", 10: "دی", 11: "بهمن", 12: "اسفند",
    }
    assert f'<option value="{today.month}" selected>{month_names[today.month]}</option>' in resp.text


def test_filters_work(client, db, make_user):
    """Search, status, year, and month filters should work."""
    boss = make_user(role="super_admin", balance_al=None)
    target = make_user(role="user", balance_al=None)
    login_as(client, boss["national_code"])

    today_str = jalali_range(0, 0)[0]
    day_j = jdatetime.datetime.strptime(today_str, "%Y/%m/%d").date()
    employee = db.query(Employee).filter(Employee.user_id == target["user_id"]).one()

    _add_status_range(client, target["user_id"], today_str, None, "M")

    resp = client.get(f"/admin/daily-status?status_filter=M&year={day_j.year}&month={day_j.month}")
    assert resp.status_code == 200
    assert target["user_id"] in resp.text
    assert "مأموریت" in resp.text

    resp = client.get(f"/admin/daily-status?search={target['user_id']}&year={day_j.year}&month={day_j.month}")
    assert resp.status_code == 200
    assert target["user_id"] in resp.text

    resp = client.get(f"/admin/daily-status?search={employee.last_name}&year={day_j.year}&month={day_j.month}")
    assert resp.status_code == 200
    assert employee.full_name in resp.text

    resp = client.get(f"/admin/daily-status?year={day_j.year}&month={day_j.month}")
    assert resp.status_code == 200
    assert target["user_id"] in resp.text


def test_pagination(client, db, make_user):
    """Pagination should preserve the selected result set."""
    boss = make_user(role="super_admin", balance_al=None)
    target = make_user(role="user", balance_al=None)
    login_as(client, boss["national_code"])

    dates = [jalali_range(i, 0)[0] for i in range(12)]
    for day_str in dates:
        _add_status_range(client, target["user_id"], day_str, None, "M")

    first_page = client.get("/admin/daily-status?show_all=1&page=1&per_page=5")
    second_page = client.get("/admin/daily-status?show_all=1&page=2&per_page=5")
    third_page = client.get("/admin/daily-status?show_all=1&page=3&per_page=5")

    assert first_page.status_code == second_page.status_code == third_page.status_code == 200
    # Results are newest-first; each page contains five records.
    assert dates[11] in first_page.text and dates[7] in first_page.text
    assert dates[6] in second_page.text and dates[2] in second_page.text
    assert dates[1] in third_page.text and dates[0] in third_page.text
    assert dates[6] not in first_page.text and dates[1] not in second_page.text


def test_permission_protection(client, make_user):
    """Non-admin users should be denied access."""
    user = make_user(role="user", balance_al=None)
    login_as(client, user["national_code"])

    resp = client.get("/admin/daily-status")
    assert resp.status_code in (302, 403)  # Redirect or forbidden

    resp = client.post("/admin/daily-status/add", data={
        "user_id": user["user_id"], "from_date": "1405/01/01", "status_code": "M"
    }, follow_redirects=False)
    assert resp.status_code in (302, 403)
