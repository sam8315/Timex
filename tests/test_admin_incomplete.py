"""
تست‌های /admin/incomplete پس از مهاجرت به Central Attendance Engine.

پوشش Caseهای A–L از مشخصات اصلاح معماری تشخیص تردد ناقص.
"""
from datetime import date, datetime, timedelta

import jdatetime
import pytest

from core.attendance_calculator import (
    STATUS_COMPLETE,
    STATUS_MISSING_ENTER,
    STATUS_MISSING_EXIT,
    STATUS_NIGHT_SHIFT,
    STATUS_SEQUENCE_ERROR,
    compute_day_attendance,
)
from models.attendance import Attendance
from models.user_permission import UserPermission
from tests.conftest import login_as
from web.services.incomplete_attendance_service import (
    IncompleteDateError,
    find_incomplete_attendances,
    resolve_date_range,
)


DAY = date(2024, 6, 10)
DAY2 = date(2024, 6, 11)


def _dt(d: date, hour: int, minute: int = 0) -> datetime:
    return datetime(d.year, d.month, d.day, hour, minute, 0)


def _add_punch(db, user_id, d, hour, punch, minute=0, is_deleted=False):
    rec = Attendance(
        user_id=user_id,
        timestamp=_dt(d, hour, minute),
        punch=punch,
        status=15,
        source='M',
        is_deleted=is_deleted,
    )
    db.add(rec)
    return rec


def _jalali(d: date) -> str:
    return jdatetime.date.fromgregorian(date=d).strftime('%Y/%m/%d')


def _capture_incomplete(client, monkeypatch, query: str):
    import web.routes.admin as route_mod

    captured = {}
    original = route_mod.templates.TemplateResponse

    def spy(*args, **kwargs):
        ctx = None
        if len(args) >= 3 and isinstance(args[2], dict):
            ctx = args[2]
        elif isinstance(kwargs.get('context'), dict):
            ctx = kwargs['context']
        if ctx is not None:
            captured.clear()
            captured.update(ctx)
        return original(*args, **kwargs)

    monkeypatch.setattr(route_mod.templates, 'TemplateResponse', spy)
    resp = client.get(f'/admin/incomplete?{query}', follow_redirects=False)
    return resp, dict(captured)


def _login_admin(client, make_user, department='4'):
    admin = make_user(role='admin', department=department)
    login_as(client, admin['national_code'])
    return admin


# ---------------------------------------------------------------------------
# Central Engine — Case A–G (منبع حقیقت)
# ---------------------------------------------------------------------------
class TestCentralEngineCases:
    def test_case_a_complete(self):
        recs = [
            type('R', (), {'timestamp': _dt(DAY, 8), 'punch': 0})(),
            type('R', (), {'timestamp': _dt(DAY, 17), 'punch': 1})(),
        ]
        res = compute_day_attendance(day=DAY, day_records=recs)
        assert res.main_status == STATUS_COMPLETE

    def test_case_b_missing_exit(self):
        recs = [type('R', (), {'timestamp': _dt(DAY, 8), 'punch': 0})()]
        res = compute_day_attendance(day=DAY, day_records=recs)
        assert res.main_status == STATUS_MISSING_EXIT

    def test_case_c_missing_enter(self):
        recs = [type('R', (), {'timestamp': _dt(DAY, 17), 'punch': 1})()]
        res = compute_day_attendance(day=DAY, day_records=recs)
        assert res.main_status == STATUS_MISSING_ENTER

    def test_case_d_missing_exit_after_pair(self):
        recs = [
            type('R', (), {'timestamp': _dt(DAY, 8), 'punch': 0})(),
            type('R', (), {'timestamp': _dt(DAY, 12), 'punch': 1})(),
            type('R', (), {'timestamp': _dt(DAY, 13), 'punch': 0})(),
        ]
        res = compute_day_attendance(day=DAY, day_records=recs)
        assert res.main_status == STATUS_MISSING_EXIT

    def test_case_e_sequence_error_balanced_counts(self):
        """enter_count == exit_count ولی دو خروج پشت‌سرهم → sequence_error."""
        recs = [
            type('R', (), {'timestamp': _dt(DAY, 8), 'punch': 0})(),
            type('R', (), {'timestamp': _dt(DAY, 12), 'punch': 1})(),
            type('R', (), {'timestamp': _dt(DAY, 13), 'punch': 1})(),
            type('R', (), {'timestamp': _dt(DAY, 14, 30), 'punch': 0})(),
        ]
        res = compute_day_attendance(day=DAY, day_records=recs)
        assert res.enter_count == res.exit_count == 2
        assert res.main_status == STATUS_SEQUENCE_ERROR
        assert res.has_sequence_error is True

    def test_case_f_night_shift(self):
        day1 = [
            type('R', (), {'timestamp': _dt(DAY, 22), 'punch': 0})(),
        ]
        day2 = [
            type('R', (), {'timestamp': _dt(DAY2, 6), 'punch': 1})(),
        ]
        r1 = compute_day_attendance(
            day=DAY, day_records=day1, next_day_records=day2,
        )
        r2 = compute_day_attendance(
            day=DAY2, day_records=day2, prev_day_records=day1,
        )
        assert r1.main_status == STATUS_NIGHT_SHIFT
        assert r2.main_status == STATUS_NIGHT_SHIFT


# ---------------------------------------------------------------------------
# Service layer — bulk + filters
# ---------------------------------------------------------------------------
class TestIncompleteService:
    def test_case_e_found_by_service(self, db, make_user):
        user = make_user(role='user', department='4')
        uid = user['user_id']
        _add_punch(db, uid, DAY, 8, 0)
        _add_punch(db, uid, DAY, 12, 1)
        _add_punch(db, uid, DAY, 13, 1)
        _add_punch(db, uid, DAY, 14, 0, minute=30)
        db.commit()

        items = find_incomplete_attendances(db, DAY, DAY)
        assert len(items) == 1
        assert items[0]['issue'] == STATUS_SEQUENCE_ERROR
        assert items[0]['enter_count'] == 2
        assert items[0]['exit_count'] == 2

    def test_case_a_complete_excluded(self, db, make_user):
        user = make_user(role='user', department='4')
        uid = user['user_id']
        _add_punch(db, uid, DAY, 8, 0)
        _add_punch(db, uid, DAY, 17, 1)
        db.commit()

        items = find_incomplete_attendances(db, DAY, DAY)
        assert items == []

    def test_case_g_night_shift_not_incomplete_by_default(self, db, make_user):
        user = make_user(role='user', department='4')
        uid = user['user_id']
        _add_punch(db, uid, DAY, 22, 0)
        _add_punch(db, uid, DAY2, 6, 1)
        db.commit()

        items = find_incomplete_attendances(db, DAY, DAY2, include_night_shift=False)
        assert items == []

        with_night = find_incomplete_attendances(
            db, DAY, DAY2, include_night_shift=True,
        )
        assert len(with_night) == 2
        assert all(i['issue'] == STATUS_NIGHT_SHIFT for i in with_night)
        assert all(i['is_night_shift'] for i in with_night)

    def test_case_h_soft_deleted_ignored(self, db, make_user):
        user = make_user(role='user', department='4')
        uid = user['user_id']
        _add_punch(db, uid, DAY, 8, 0)
        _add_punch(db, uid, DAY, 17, 1, is_deleted=True)
        db.commit()

        items = find_incomplete_attendances(db, DAY, DAY)
        assert len(items) == 1
        assert items[0]['issue'] == STATUS_MISSING_EXIT

    def test_case_i_department_filter(self, db, make_user):
        u1 = make_user(role='user', department='1')
        u2 = make_user(role='user', department='4')
        _add_punch(db, u1['user_id'], DAY, 8, 0)
        _add_punch(db, u2['user_id'], DAY, 8, 0)
        db.commit()

        items = find_incomplete_attendances(db, DAY, DAY, department='1')
        assert len(items) == 1
        assert items[0]['user_id'] == u1['user_id']
        assert items[0]['department'] == '1'

    def test_case_j_issue_type_filter(self, db, make_user):
        u1 = make_user(role='user', department='4')
        u2 = make_user(role='user', department='4')
        _add_punch(db, u1['user_id'], DAY, 8, 0)          # missing_exit
        _add_punch(db, u2['user_id'], DAY, 17, 1)         # missing_enter
        db.commit()

        items = find_incomplete_attendances(
            db, DAY, DAY, issue_type=STATUS_MISSING_ENTER,
        )
        assert len(items) == 1
        assert items[0]['user_id'] == u2['user_id']

    def test_case_l_from_after_to_raises(self):
        with pytest.raises(IncompleteDateError, match='از تاریخ'):
            resolve_date_range('1403/03/20', '1403/03/10')

    def test_invalid_date_format_raises(self):
        with pytest.raises(IncompleteDateError, match='نامعتبر'):
            resolve_date_range('bad-date', '1403/03/10')

    def test_uses_range_query_not_func_date(self):
        import inspect
        import web.services.incomplete_attendance_service as svc
        src = inspect.getsource(svc.find_incomplete_attendances)
        assert 'func.date' not in src
        assert 'timestamp >=' in src or 'Attendance.timestamp >=' in src


# ---------------------------------------------------------------------------
# HTTP route
# ---------------------------------------------------------------------------
class TestIncompleteRoute:
    def test_permission_required(self, client, make_user, db):
        admin = make_user(role='admin', department='9')
        db.add(UserPermission(
            user_id=admin['user_id'],
            permission='view_incomplete',
            granted=False,
        ))
        db.commit()
        login_as(client, admin['national_code'])
        resp = client.get('/admin/incomplete?show_all=1', follow_redirects=False)
        assert resp.status_code == 403

    def test_case_k_show_all_includes_night_shift(
        self, client, make_user, db, monkeypatch,
    ):
        admin = _login_admin(client, make_user)
        uid = make_user(role='user', department='4')['user_id']

        today_j = jdatetime.date.today()
        d1 = jdatetime.date(today_j.year, today_j.month, 1).togregorian()
        if d1.month == 12:
            d2 = date(d1.year + 1, 1, 1)
        else:
            # day 2 of same month range — ensure inside current jalali month
            d2 = d1 + timedelta(days=1)

        _add_punch(db, uid, d1, 22, 0)
        _add_punch(db, uid, d2, 6, 1)
        # also a real incomplete
        missing_day = d1 + timedelta(days=3)
        # keep inside month if possible
        month_end = (
            jdatetime.date(today_j.year, today_j.month + 1, 1) - timedelta(days=1)
            if today_j.month < 12
            else jdatetime.date(today_j.year + 1, 1, 1) - timedelta(days=1)
        ).togregorian()
        if missing_day > month_end:
            missing_day = d1
            # overwrite: use a separate user day that is clearly incomplete
        else:
            _add_punch(db, uid, missing_day, 8, 0)
        db.commit()

        resp, ctx = _capture_incomplete(
            client, monkeypatch, 'show_all=1&include_night_shift=1',
        )
        assert resp.status_code == 200
        assert ctx['has_filter'] is True
        assert ctx['include_night_shift'] == '1'
        issues = {i['issue'] for i in ctx['incomplete_list']}
        assert STATUS_NIGHT_SHIFT in issues

    def test_default_excludes_night_shift(
        self, client, make_user, db, monkeypatch,
    ):
        _login_admin(client, make_user)
        uid = make_user(role='user', department='4')['user_id']
        _add_punch(db, uid, DAY, 22, 0)
        _add_punch(db, uid, DAY2, 6, 1)
        db.commit()

        q = (
            f'from_date_str={_jalali(DAY)}&to_date_str={_jalali(DAY2)}'
            f'&include_night_shift=0'
        )
        resp, ctx = _capture_incomplete(client, monkeypatch, q)
        assert resp.status_code == 200
        assert ctx['stats']['total'] == 0
        assert ctx['incomplete_list'] == []

    def test_sequence_error_via_http(self, client, make_user, db, monkeypatch):
        _login_admin(client, make_user)
        uid = make_user(role='user', department='4')['user_id']
        _add_punch(db, uid, DAY, 8, 0)
        _add_punch(db, uid, DAY, 12, 1)
        _add_punch(db, uid, DAY, 13, 1)
        _add_punch(db, uid, DAY, 14, 0, minute=30)
        db.commit()

        q = (
            f'from_date_str={_jalali(DAY)}&to_date_str={_jalali(DAY)}'
            f'&include_night_shift=0'
        )
        resp, ctx = _capture_incomplete(client, monkeypatch, q)
        assert resp.status_code == 200
        assert ctx['stats']['sequence_error'] == 1
        assert ctx['incomplete_list'][0]['issue'] == STATUS_SEQUENCE_ERROR

    def test_case_l_date_error_via_http(self, client, make_user, monkeypatch):
        _login_admin(client, make_user)
        q = 'from_date_str=1403/03/20&to_date_str=1403/03/10&include_night_shift=0'
        resp, ctx = _capture_incomplete(client, monkeypatch, q)
        assert resp.status_code == 200
        assert ctx['date_error']
        assert 'از تاریخ' in ctx['date_error']
        assert ctx['stats']['total'] == 0

    def test_has_filter_includes_night_shift_param(
        self, client, make_user, monkeypatch,
    ):
        _login_admin(client, make_user)
        resp, ctx = _capture_incomplete(
            client, monkeypatch, 'include_night_shift=1',
        )
        assert resp.status_code == 200
        assert ctx['has_filter'] is True

    def test_filter_state_preserved(self, client, make_user, monkeypatch):
        _login_admin(client, make_user)
        q = (
            f'from_date_str={_jalali(DAY)}&to_date_str={_jalali(DAY)}'
            f'&membership_type=4&issue_type=missing_exit&include_night_shift=1'
        )
        resp, ctx = _capture_incomplete(client, monkeypatch, q)
        assert resp.status_code == 200
        assert ctx['from_date_str'] == _jalali(DAY)
        assert ctx['to_date_str'] == _jalali(DAY)
        assert ctx['membership_type'] == '4'
        assert ctx['issue_type'] == 'missing_exit'
        assert ctx['include_night_shift'] == '1'

    def test_no_parallel_analyzer_in_route(self):
        import inspect
        import web.routes.admin as route_mod
        src = inspect.getsource(route_mod.admin_incomplete_attendance)
        assert 'AttendanceAnalyzer' not in src
        assert 'get_incomplete_attendances' not in src
        assert 'find_incomplete_attendances' in src

    def test_route_uses_central_engine(self):
        import web.routes.admin as route_mod
        import web.services.incomplete_attendance_service as svc
        assert svc.compute_day_attendance is not None
        assert route_mod.compute_day_attendance is not None
