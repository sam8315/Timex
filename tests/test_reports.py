"""Tests for monthly-stats intro (معرفی) / settlement (تسویه) logic
and Travel Leave (توراهی) day mapping."""
from datetime import date, timedelta
from types import SimpleNamespace

import jdatetime

from models.city import City
from models.contract import Contract
from models.employee import Employee
from models.holiday import Holiday
from models.leave_request import LeaveRequest
from models.travel_leave_detail import TravelLeaveDetail
from web.routes.reports import (
    build_monthly_stats_leaves_map,
    display_holiday_dates,
    fetch_monthly_stats_leave_data,
    get_day_code,
    resolve_intro_settle_dates,
)
from web.services.travel_leave_service import LEAVE_TYPE_TRAVEL
from .conftest import login_as


def _bounds(year, month):
    start_j = jdatetime.date(year, month, 1)
    if month == 12:
        end_j = jdatetime.date(year, 12, 29)
    else:
        end_j = jdatetime.date(year, month + 1, 1) - timedelta(days=1)
    return start_j.togregorian(), end_j.togregorian()


def _contract(start, end):
    return SimpleNamespace(start_date=start, end_date=end)


def test_no_contract_falls_back_to_hire_and_termination():
    ms, me = _bounds(1405, 5)
    hire = ms + timedelta(days=2)
    term = ms + timedelta(days=5)
    assert resolve_intro_settle_dates([], hire, term, ms, me) == (hire, term)


def test_no_contract_no_dates_returns_nones():
    ms, me = _bounds(1405, 5)
    assert resolve_intro_settle_dates([], None, None, ms, me) == (None, None)


def test_contract_start_in_month_is_intro():
    ms, me = _bounds(1405, 5)
    start = ms + timedelta(days=1)
    intro, settle = resolve_intro_settle_dates(
        [_contract(start, None)], date(1400, 1, 1), None, ms, me)
    assert intro == start
    assert settle is None


def test_spanning_contract_has_no_markers():
    ms, me = _bounds(1405, 5)
    intro, settle = resolve_intro_settle_dates(
        [_contract(ms - timedelta(days=40), me + timedelta(days=40))],
        ms - timedelta(days=100), None, ms, me)
    assert (intro, settle) == (None, None)


def test_contract_end_in_month_is_settle():
    ms, me = _bounds(1405, 5)
    end = ms + timedelta(days=4)
    intro, settle = resolve_intro_settle_dates(
        [_contract(ms - timedelta(days=40), end)], None, None, ms, me)
    assert settle == end


def test_back_to_back_contract_suppresses_settle():
    ms, me = _bounds(1405, 5)
    end = ms + timedelta(days=4)
    contracts = [_contract(ms - timedelta(days=40), end),
                 _contract(end + timedelta(days=1), None)]
    intro, settle = resolve_intro_settle_dates(
        contracts, None, None, ms, me)
    assert settle is None


def test_out_of_month_contract_dates_ignored():
    ms, me = _bounds(1405, 5)
    intro, settle = resolve_intro_settle_dates(
        [_contract(ms - timedelta(days=60), ms - timedelta(days=1))],
        None, None, ms, me)
    assert (intro, settle) == (None, None)


def test_day_code_intro_beats_settle_and_holiday():
    day = date(2026, 9, 3)
    assert get_day_code(day, {}, {}, set(), False, True,
                        hire_date=day, contract_end_date=day) == 'معرفی'
    assert get_day_code(day, {}, {}, set(), False, False,
                        hire_date=None,
                        contract_end_date=day) == 'تسویه'
    assert get_day_code(day, {}, {}, set(), False, True,
                        hire_date=None,
                        contract_end_date=None) == ''


def _set_employment(db, user_id, hire, term):
    db.query(Employee).filter(Employee.user_id == user_id).update(
        {"hire_date": hire, "termination_date": term})
    db.commit()


def test_monthly_stats_fallback_without_contract(client, db, make_user):
    admin = make_user(role="super_admin", balance_al=None)
    user = make_user(role="user", balance_al=None)
    today_j = jdatetime.date.today()
    ms, me = _bounds(today_j.year, today_j.month)
    _set_employment(db, user["user_id"], ms + timedelta(days=2),
                    ms + timedelta(days=5))

    login_as(client, admin["national_code"])
    resp = client.post(
        "/reports/monthly-stats",
        data={"year": str(today_j.year), "month": str(today_j.month),
              "department": "all"},
    )
    assert resp.status_code == 200
    assert "معرفی" in resp.text
    assert "تسویه" in resp.text


def test_monthly_stats_contract_markers(client, db, make_user):
    admin = make_user(role="super_admin", balance_al=None)
    user = make_user(role="user", balance_al=None)
    today_j = jdatetime.date.today()
    ms, me = _bounds(today_j.year, today_j.month)
    _set_employment(db, user["user_id"], ms - timedelta(days=100), None)
    db.add(Contract(
        user_id=user["user_id"], contract_type_code="4",
        start_date=ms + timedelta(days=1), end_date=ms + timedelta(days=4),
        annual_leave_days=30, sick_leave_days=0, service_deduction_days=0,
    ))
    db.commit()

    login_as(client, admin["national_code"])
    resp = client.post(
        "/reports/monthly-stats",
        data={"year": str(today_j.year), "month": str(today_j.month),
              "department": "all"},
    )
    assert resp.status_code == 200
    assert "معرفی" in resp.text
    assert "تسویه" in resp.text


def test_monthly_stats_excel_exports(client, make_user):
    admin = make_user(role="super_admin", balance_al=None)
    today_j = jdatetime.date.today()
    login_as(client, admin["national_code"])
    resp = client.get(
        "/reports/monthly-stats/excel",
        params={"year": today_j.year, "month": today_j.month,
                "department": "all"},
    )
    assert resp.status_code == 200
    assert "spreadsheetml" in resp.headers["content-type"]


# ---------------------------------------------------------------------------
# Travel Leave (توراهی) mapping for the monthly statistics report
# ---------------------------------------------------------------------------
# Reference week: 2024-01-01 (Mon) .. 2024-01-07 (Sun); 2024-01-05 is Friday.
D0 = date(2024, 1, 1)
D1 = date(2024, 1, 2)
D2 = date(2024, 1, 3)
D3 = date(2024, 1, 4)
FRI = date(2024, 1, 5)
D5 = date(2024, 1, 6)
D6 = date(2024, 1, 7)


def _leave(from_d, to_d, leave_type="AL", detail=None, user_id="U1"):
    return SimpleNamespace(
        user_id=user_id,
        from_date=from_d,
        to_date=to_d,
        leave_type=leave_type,
        travel_leave_detail=detail,
    )


def _tl_detail(final_travel_days):
    return SimpleNamespace(final_travel_days=final_travel_days)


def _holiday(d, group_id=None):
    return SimpleNamespace(holiday_date=d, group_id=group_id)


def _map(leaves, holidays=None, departments=None, start=D0, end=D6):
    return build_monthly_stats_leaves_map(
        leaves,
        holidays or [],
        departments if departments is not None else {"U1": "1"},
        start,
        end,
    )


def test_al_without_travel_detail_stays_al():
    mapping = _map([_leave(D0, D3)], start=D0, end=D3)["U1"]
    assert mapping == {D0: "AL", D1: "AL", D2: "AL", D3: "AL"}
    assert get_day_code(D0, mapping, {}, set(), False, False) == "ص"


def test_travel_leave_splits_first_two_working_days():
    # Mon..Sat: 5 working days (Friday skipped) -> TL, TL, AL, AL, AL
    mapping = _map(
        [_leave(D0, D5, detail=_tl_detail(2))], start=D0, end=D5
    )["U1"]
    assert mapping == {
        D0: LEAVE_TYPE_TRAVEL,
        D1: LEAVE_TYPE_TRAVEL,
        D2: "AL",
        D3: "AL",
        D5: "AL",
    }


def test_friday_does_not_consume_travel_days():
    # Thu, Fri, Sat with final_travel_days=2: both working days are TL.
    mapping = _map(
        [_leave(D3, D5, detail=_tl_detail(2))], start=D3, end=D5
    )["U1"]
    assert FRI not in mapping
    assert mapping[D3] == LEAVE_TYPE_TRAVEL
    assert mapping[D5] == LEAVE_TYPE_TRAVEL


def test_holiday_does_not_consume_travel_days():
    mapping = _map(
        [_leave(D0, D3, detail=_tl_detail(2))],
        holidays=[_holiday(D2)],
        start=D0,
        end=D3,
    )["U1"]
    assert D2 not in mapping
    assert mapping[D0] == LEAVE_TYPE_TRAVEL
    assert mapping[D1] == LEAVE_TYPE_TRAVEL
    assert mapping[D3] == "AL"


def test_group_holiday_of_own_department_does_not_consume_travel_days():
    mapping = _map(
        [_leave(D0, D2, detail=_tl_detail(2))],
        holidays=[_holiday(D1, group_id="1")],
        departments={"U1": "1"},
        start=D0,
        end=D2,
    )["U1"]
    assert D1 not in mapping
    assert mapping[D0] == LEAVE_TYPE_TRAVEL
    assert mapping[D2] == LEAVE_TYPE_TRAVEL


def test_holiday_of_other_group_is_still_a_working_day():
    mapping = _map(
        [_leave(D0, D2, detail=_tl_detail(2))],
        holidays=[_holiday(D1, group_id="2")],
        departments={"U1": "1"},
        start=D0,
        end=D2,
    )["U1"]
    assert mapping == {
        D0: LEAVE_TYPE_TRAVEL,
        D1: LEAVE_TYPE_TRAVEL,
        D2: "AL",
    }


def test_cross_month_travel_days_counted_from_original_start():
    # Leave: Tue 2024-01-30 .. Mon 2024-02-05, final_travel_days=2.
    # First two working days are 01-30 and 01-31 (both before the report
    # month), so February must show NO travel leave — the counter must not
    # restart at the first day of the visible month.
    leave = _leave(date(2024, 1, 30), date(2024, 2, 5), detail=_tl_detail(2))
    mapping = _map(
        [leave], start=date(2024, 2, 1), end=date(2024, 2, 29)
    )["U1"]
    assert LEAVE_TYPE_TRAVEL not in mapping.values()
    assert mapping[date(2024, 2, 1)] == "AL"
    assert mapping[date(2024, 2, 3)] == "AL"


def test_cross_month_remaining_travel_day_spills_into_report_month():
    # Leave: Wed 2024-01-31 .. Mon 2024-02-05, final_travel_days=2.
    # ws0 = 01-31 (before the month), ws1 = 02-01 -> the only TL in view.
    leave = _leave(date(2024, 1, 31), date(2024, 2, 5), detail=_tl_detail(2))
    mapping = _map(
        [leave], start=date(2024, 2, 1), end=date(2024, 2, 29)
    )["U1"]
    tl_dates = [d for d, t in mapping.items() if t == LEAVE_TYPE_TRAVEL]
    assert tl_dates == [date(2024, 2, 1)]
    assert mapping[date(2024, 2, 3)] == "AL"


def test_zero_final_travel_days_keeps_all_days_al():
    mapping = _map(
        [_leave(D0, D3, detail=_tl_detail(0))], start=D0, end=D3
    )["U1"]
    assert set(mapping.values()) == {"AL"}
    assert set(mapping.keys()) == {D0, D1, D2, D3}


def test_multiple_employees_have_independent_mappings():
    leaves = [
        _leave(D0, D3, detail=_tl_detail(1), user_id="U1"),
        _leave(D0, D3, detail=_tl_detail(2), user_id="U2"),
    ]
    mapping = _map(
        leaves,
        departments={"U1": "1", "U2": "1"},
        start=D0,
        end=D3,
    )
    assert mapping["U1"][D0] == LEAVE_TYPE_TRAVEL
    assert mapping["U1"][D1] == "AL"
    assert mapping["U2"][D0] == LEAVE_TYPE_TRAVEL
    assert mapping["U2"][D1] == LEAVE_TYPE_TRAVEL
    assert mapping["U2"][D2] == "AL"


def test_day_code_recognizes_travel_leave_internal_code():
    day = date(2026, 9, 7)
    assert get_day_code(day, {day: "TL"}, {}, set(), False, False) == "TL"
    # ت stays the Reward Leave (RL) code.
    assert get_day_code(day, {day: "RL"}, {}, set(), False, False) == "ت"
    assert get_day_code(day, {day: "AL"}, {}, set(), False, False) == "ص"


def test_fetch_leave_data_extends_holiday_range_before_month(db, make_user):
    user = make_user(role="user", balance_al=30)
    today_j = jdatetime.date.today()
    ms, me = _bounds(today_j.year, today_j.month)
    cross = ms - timedelta(days=1)

    existing = db.query(Holiday).filter(Holiday.holiday_date == cross).first()
    created = existing is None
    if created:
        db.add(Holiday(
            holiday_date=cross, title="تعطیل تست ماه قبل",
            is_national=True, group_id=None,
        ))
        db.commit()

    try:
        req = LeaveRequest(
            user_id=user["user_id"],
            leave_type="AL",
            from_date=cross,
            to_date=ms + timedelta(days=2),
            days_count=4,
            status="A",
        )
        db.add(req)
        db.commit()

        leaves, holidays = fetch_monthly_stats_leave_data(db, ms, me)
        assert any(lv.id == req.id for lv in leaves)
        assert any(h.holiday_date == cross for h in holidays)
        # Display holidays stay limited to the visible month.
        shown = display_holiday_dates(holidays, ms, me)
        assert cross not in shown
    finally:
        if created:
            db.query(Holiday).filter(Holiday.holiday_date == cross).delete()
            db.commit()


def _current_month_workdays(db, n, department="1"):
    today_j = jdatetime.date.today()
    ms, me = _bounds(today_j.year, today_j.month)
    applicable = {
        h.holiday_date
        for h in db.query(Holiday).filter(
            Holiday.holiday_date >= ms, Holiday.holiday_date <= me
        ).all()
        if h.group_id is None or h.group_id == department
    }
    picks = []
    cur = ms
    while cur <= me and len(picks) < n:
        if cur.weekday() != 4 and cur not in applicable:
            picks.append(cur)
        cur += timedelta(days=1)
    assert len(picks) == n, "not enough working days in current month"
    return picks


def _create_travel_leave(db, user_id, from_g, to_g, final_travel_days):
    city = db.query(City).filter(City.is_active.is_(True)).first()
    assert city, "test DB must have at least one active city"
    req = LeaveRequest(
        user_id=user_id,
        leave_type="AL",
        from_date=from_g,
        to_date=to_g,
        days_count=(to_g - from_g).days + 1,
        status="A",
    )
    db.add(req)
    db.flush()
    db.add(TravelLeaveDetail(
        leave_request_id=req.id,
        destination_city_id=city.id,
        destination_city_name_snapshot=city.name,
        destination_latitude_snapshot=city.latitude,
        destination_longitude_snapshot=city.longitude,
        distance_km=100.0,
        calculated_travel_days=final_travel_days,
        final_travel_days=final_travel_days,
        manual_override=False,
        jalali_year=jdatetime.date.fromgregorian(date=from_g).year,
    ))
    db.commit()
    return req


def test_monthly_stats_route_marks_travel_leave_days(client, db, make_user):
    admin = make_user(role="super_admin", balance_al=None)
    user = make_user(role="user", balance_al=30, department="1")
    today_j = jdatetime.date.today()
    ms, _me = _bounds(today_j.year, today_j.month)
    _set_employment(db, user["user_id"], ms - timedelta(days=100), None)

    w1, w2, w3 = _current_month_workdays(db, 3)
    _create_travel_leave(db, user["user_id"], w1, w3, 2)

    login_as(client, admin["national_code"])
    resp = client.post(
        "/reports/monthly-stats",
        data={"year": str(today_j.year), "month": str(today_j.month),
              "department": "all"},
    )
    assert resp.status_code == 200
    # Rendered day cells: two TL days (first two working days) and the
    # remaining working day stays ordinary annual leave (ص).
    assert resp.text.count("        TL\n    </td>") == 2
    assert resp.text.count("        ص\n    </td>") == 1
