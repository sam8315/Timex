"""قانون «شیفت پیوسته نیمه‌شب»: فاصلهٔ خروج/ورود داخل پنجرهٔ نیمه‌شب کارکرد است."""
import re
from datetime import date, datetime, timedelta

import pytest

from core.attendance_calculator import (
    STATUS_COMPLETE,
    STATUS_NIGHT_SHIFT,
    MidnightBridgeRule,
    calculate_work_hours,
    compute_day_attendance,
)
from core.detailed_monthly_report_v2 import DetailedMonthlyReportGeneratorV2
from models.policy import Policy, PolicyValue
from web.services.midnight_bridge_settings import (
    MIDNIGHT_BRIDGE_CATEGORY,
    MidnightBridgeSettings,
    load_midnight_bridge_settings,
    save_midnight_bridge_settings,
)
from .conftest import login_as

D1 = date(2024, 5, 15)
D2 = D1 + timedelta(days=1)
D0 = D1 - timedelta(days=1)
RULE = MidnightBridgeRule(before_minutes=15, after_minutes=15)


class Rec:
    def __init__(self, ts, punch):
        self.timestamp = ts
        self.punch = punch


def at(d, h, m=0):
    return datetime(d.year, d.month, d.day, h, m)


def minutes(hours):
    return round(hours * 60)


def day(d, records, prev=None, next_=None, rule=RULE):
    return compute_day_attendance(
        day=d,
        day_records=records,
        prev_day_records=prev or [],
        next_day_records=next_ or [],
        midnight_bridge=rule,
    )


# ============================================
# عبور از نیمه‌شب: خروج 23:55 و ورود 00:10
# ============================================
def _cross_midnight_records():
    d1 = [Rec(at(D1, 15), 0), Rec(at(D1, 23, 55), 1)]
    d2 = [Rec(at(D2, 0, 10), 0), Rec(at(D2, 8), 1)]
    return d1, d2


def test_cross_midnight_each_day_gets_its_own_part():
    d1, d2 = _cross_midnight_records()
    r1 = day(D1, d1, next_=d2)
    r2 = day(D2, d2, prev=d1)

    assert minutes(r1.work_hours) == 9 * 60  # 15:00 → 24:00
    assert minutes(r2.work_hours) == 8 * 60  # 00:00 → 08:00
    assert r1.pairs[-1]['exit'] == datetime.combine(D2, datetime.min.time())
    assert r2.pairs[0]['enter'] == datetime.combine(D2, datetime.min.time())
    assert r1.pairs[-1]['bridged_midnight'] is True
    assert r2.pairs[0]['bridged_midnight'] is True
    # پانچ واقعی برای تأخیر/تعجیل دست نمی‌خورد
    assert r1.last_exit == at(D1, 23, 55)
    assert r2.first_enter == at(D2, 0, 10)
    assert r1.main_status == STATUS_COMPLETE
    assert r2.main_status == STATUS_COMPLETE


def test_cross_midnight_without_rule_is_unchanged():
    d1, d2 = _cross_midnight_records()
    r1 = day(D1, d1, next_=d2, rule=None)
    r2 = day(D2, d2, prev=d1, rule=None)
    assert minutes(r1.work_hours) == 8 * 60 + 55
    assert minutes(r2.work_hours) == 7 * 60 + 50
    assert all('bridged_midnight' not in p for p in r1.pairs + r2.pairs)


def test_sum_of_pairs_matches_work_hours():
    d1, d2 = _cross_midnight_records()
    for r in (day(D1, d1, next_=d2), day(D2, d2, prev=d1)):
        assert sum(p['hours'] for p in r.pairs) == pytest.approx(r.work_hours)


# ============================================
# هر دو بعد از نیمه‌شب: خروج 00:05 و ورود 00:10 (شیفت شب)
# ============================================
def test_both_after_midnight_in_night_shift_merges_into_one_pair():
    d1 = [Rec(at(D1, 16), 0)]
    d2 = [Rec(at(D2, 0, 5), 1), Rec(at(D2, 0, 10), 0), Rec(at(D2, 8), 1)]

    r2 = day(D2, d2, prev=d1)
    assert r2.main_status == STATUS_NIGHT_SHIFT
    assert len(r2.pairs) == 1
    assert r2.pairs[0]['enter'] == datetime.combine(D2, datetime.min.time())
    assert r2.pairs[0]['exit'] == at(D2, 8)
    assert r2.pairs[0]['bridged_midnight'] is True
    assert minutes(r2.work_hours) == 8 * 60

    no_rule = day(D2, d2, prev=d1, rule=None)
    assert minutes(no_rule.work_hours) == 8 * 60 - 5


# ============================================
# هر دو قبل از نیمه‌شب: خروج 23:50 و ورود 23:58
# ============================================
def test_both_before_midnight_merges_same_day():
    d1 = [Rec(at(D1, 15), 0), Rec(at(D1, 23, 50), 1), Rec(at(D1, 23, 58), 0)]
    d2 = [Rec(at(D2, 8), 1)]

    r1 = day(D1, d1, next_=d2)
    assert r1.main_status == STATUS_NIGHT_SHIFT
    assert len(r1.pairs) == 1
    assert r1.pairs[0]['enter'] == at(D1, 15)
    assert r1.pairs[0]['bridged_midnight'] is True
    no_rule = day(D1, d1, next_=d2, rule=None)
    assert minutes(r1.work_hours) - minutes(no_rule.work_hours) == 8


def test_both_before_midnight_complete_day():
    d1 = [
        Rec(at(D1, 15), 0), Rec(at(D1, 23, 50), 1),
        Rec(at(D1, 23, 52), 0), Rec(at(D1, 23, 56), 1),
    ]
    r1 = day(D1, d1)
    assert minutes(r1.work_hours) == 8 * 60 + 56
    assert len(r1.pairs) == 1


# ============================================
# منفی
# ============================================
@pytest.mark.parametrize('exit_t,enter_t', [
    ((23, 40), (0, 10)),   # خروج قبل از پنجره
    ((23, 55), (0, 20)),   # ورود بعد از پنجره
    ((23, 50), (0, 20)),
])
def test_outside_window_is_not_bridged(exit_t, enter_t):
    d1 = [Rec(at(D1, 15), 0), Rec(at(D1, *exit_t), 1)]
    d2 = [Rec(at(D2, *enter_t), 0), Rec(at(D2, 8), 1)]
    for r, base in (
        (day(D1, d1, next_=d2), day(D1, d1, next_=d2, rule=None)),
        (day(D2, d2, prev=d1), day(D2, d2, prev=d1, rule=None)),
    ):
        assert r.work_hours == pytest.approx(base.work_hours)
        assert all('bridged_midnight' not in p for p in r.pairs)


def test_record_between_exit_and_enter_blocks_bridge():
    d1 = [
        Rec(at(D1, 15), 0), Rec(at(D1, 23, 50), 1),
        Rec(at(D1, 23, 52), 1), Rec(at(D1, 23, 58), 0), Rec(at(D1, 23, 59), 1),
    ]
    r = day(D1, d1)
    base = day(D1, d1, rule=None)
    assert r.work_hours == pytest.approx(base.work_hours)


def test_next_day_starts_with_exit_is_not_bridged():
    d1 = [Rec(at(D1, 15), 0), Rec(at(D1, 23, 55), 1)]
    d2 = [Rec(at(D2, 0, 5), 1)]
    r = day(D1, d1, next_=d2)
    assert minutes(r.work_hours) == 8 * 60 + 55


def test_zero_window_disables_side():
    d1, d2 = _cross_midnight_records()
    rule = MidnightBridgeRule(before_minutes=0, after_minutes=15)
    assert minutes(day(D1, d1, next_=d2, rule=rule).work_hours) == 8 * 60 + 55
    assert minutes(day(D2, d2, prev=d1, rule=rule).work_hours) == 7 * 60 + 50


def test_calculate_work_hours_accepts_rule():
    d1, d2 = _cross_midnight_records()
    hours, first_enter, last_exit = calculate_work_hours(
        d1, False, next_day_records=d2, midnight_bridge=RULE,
    )
    assert minutes(hours) == 9 * 60
    assert last_exit == at(D1, 23, 55)


# ============================================
# تنظیم سراسری → Rule
# ============================================
def test_settings_rule_for_membership():
    off = MidnightBridgeSettings(enabled=False, membership_codes=frozenset({'1'}))
    assert off.rule_for('1') is None

    on = MidnightBridgeSettings(
        enabled=True, before_minutes=10, after_minutes=20,
        membership_codes=frozenset({'1', '4'}),
    )
    assert on.rule_for('2') is None
    assert on.rule_for(None) is None
    assert on.rule_for('4') == MidnightBridgeRule(before_minutes=10, after_minutes=20)


@pytest.fixture
def clean_bridge_settings(db):
    def _clean():
        ids = [p.id for p in db.query(Policy).filter(
            Policy.category == MIDNIGHT_BRIDGE_CATEGORY).all()]
        if ids:
            db.query(PolicyValue).filter(PolicyValue.policy_id.in_(ids)).delete(
                synchronize_session=False)
            db.query(Policy).filter(Policy.id.in_(ids)).delete(synchronize_session=False)
        db.commit()
    _clean()
    yield
    _clean()


def test_settings_default_and_roundtrip(db, clean_bridge_settings):
    assert load_midnight_bridge_settings(db) == MidnightBridgeSettings()

    save_midnight_bridge_settings(db, True, 10, 999, ['4', '1'], changed_by='tester')
    loaded = load_midnight_bridge_settings(db)
    assert loaded.enabled is True
    assert loaded.before_minutes == 10
    assert loaded.after_minutes == 60
    assert loaded.membership_codes == frozenset({'1', '4'})

    save_midnight_bridge_settings(db, False, 15, 15, [], changed_by='tester')
    loaded = load_midnight_bridge_settings(db)
    assert loaded.enabled is False
    assert loaded.membership_codes == frozenset()


def test_admin_save_route(client, db, make_user, clean_bridge_settings):
    creds = make_user(role="super_admin", balance_al=None)
    assert login_as(client, creds["national_code"]).status_code == 302

    page = client.get("/admin/policies/attendance")
    assert page.status_code == 200
    switch = re.search(r'<input[^>]*name="enabled"[^>]*>', page.text)
    assert switch is not None and "checked" not in switch.group(0)

    resp = client.post(
        "/admin/policies/attendance/midnight-bridge/save",
        data={
            "enabled": "on",
            "before_minutes": "-5",
            "after_minutes": "20",
            "membership_codes": ["1", "NOT_A_CODE"],
        },
        follow_redirects=False,
    )
    assert resp.status_code == 302
    loaded = load_midnight_bridge_settings(db)
    assert loaded.enabled is True
    assert loaded.before_minutes == 0
    assert loaded.after_minutes == 20
    assert loaded.membership_codes == frozenset({'1'})

    page = client.get("/admin/policies/attendance")
    switch = re.search(r'<input[^>]*name="enabled"[^>]*>', page.text)
    assert "checked" in switch.group(0)
    code_box = re.search(r'<input[^>]*id="midnight_bridge_code_1"[^>]*>', page.text)
    assert code_box is not None and "checked" in code_box.group(0)


# ============================================
# گزارش ماهانه v2: کارکرد و ساعات شب دو روز متوالی
# ============================================
def test_monthly_v2_day_actual_counts_bridge_as_night_hours():
    gen = DetailedMonthlyReportGeneratorV2.__new__(DetailedMonthlyReportGeneratorV2)
    d1, d2 = _cross_midnight_records()

    day1 = gen._compute_day_actual(D1, d1, [], d2, is_friday=False,
                                   holiday_title=None, midnight_bridge=RULE)
    day2 = gen._compute_day_actual(D2, d2, d1, [], is_friday=False,
                                   holiday_title=None, midnight_bridge=RULE)
    base1 = gen._compute_day_actual(D1, d1, [], d2, is_friday=False, holiday_title=None)
    base2 = gen._compute_day_actual(D2, d2, d1, [], is_friday=False, holiday_title=None)

    assert minutes(day1['work_hours']) == minutes(base1['work_hours']) + 5
    assert minutes(day2['work_hours']) == minutes(base2['work_hours']) + 10
    assert day1['shift_hours']['night'] == pytest.approx(base1['shift_hours']['night'] + 5 / 60, abs=0.01)
    assert day2['shift_hours']['night'] == pytest.approx(base2['shift_hours']['night'] + 10 / 60, abs=0.01)
    assert day1['last_exit'] == at(D1, 23, 55)
    assert day2['first_enter'] == at(D2, 0, 10)
