"""Test admin HL registration with time fields."""
import pytest
from datetime import date, time
from models.employee import Employee
from models.attendance import HourlyLeavePolicy, AttendancePolicy, AttendancePolicyDay
from models.leave_request import LeaveRequest
from .conftest import login_as

def _seed_policy(db, emp, conversion=480, monthly_exempt=480, daily_limit=180, granularity=15, min_req=1, max_req=240):
    try:
        for p in db.query(HourlyLeavePolicy).filter(HourlyLeavePolicy.employment_type_code == emp.department, HourlyLeavePolicy.user_id.is_(None)).all():
            db.delete(p)
        db.commit()
    except Exception:
        db.rollback()
    policy = HourlyLeavePolicy(
        employment_type_code=emp.department, user_id=None,
        effective_from_date=date(2027,2,1), effective_to_date=date(2027,5,31),
        is_active=True, hourly_leave_entitled=True,
        max_daily_minutes=daily_limit, monthly_exempt_minutes=monthly_exempt,
        conversion_minutes_per_day=conversion, granularity_minutes=granularity,
        min_request_minutes=min_req, max_request_minutes=max_req)
    db.add(policy)
    db.commit()
    return policy

class TestAdminHLRegister:
    def test_admin_register_hl(self, db, client, make_user):
        admin = make_user(role="admin", balance_al=None)
        user = make_user(role="user", balance_al=30)
        emp = db.query(Employee).filter(Employee.user_id == user["user_id"]).first()
        _seed_policy(db, emp, min_req=1, granularity=1)
        # seed attendance policy
        from tests.test_hourly_leave_integration import _seed_attendance_policy
        _seed_attendance_policy(db, emp)
        login_as(client, admin["national_code"])
        j_date = "1406/01/02"
        resp = client.post("/admin/leave-requests/register", data={
            "target_user_id": user["user_id"],
            "leave_type": "HL",
            "from_date_str": j_date,
            "to_date_str": "",
            "start_time_str": "09:00",
            "end_time_str": "10:30",
            "reason": "test",
        }, follow_redirects=False)
        assert resp.status_code == 302
        assert "success=" in resp.headers.get("location", "")
        lr = db.query(LeaveRequest).filter(LeaveRequest.user_id == user["user_id"], LeaveRequest.leave_type == "HL").first()
        assert lr is not None
        assert lr.from_date == date(2027,3,22)
        assert lr.to_date == date(2027,3,22)
        assert lr.start_time == time(9,0)
        assert lr.end_time == time(10,30)
        assert lr.days_count == 0
