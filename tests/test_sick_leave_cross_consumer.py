"""یک ورودی استعلاجی باید در گزارش تفصیلی، کامل و اضافه‌کار قانونی یکسان باشد."""
from datetime import datetime, time

import jdatetime
import pytest

from core.legal_overtime_monthly_report import LegalOvertimeMonthlyReportGenerator
from core.sick_leave_facts import apply_work_hours, effect_for_span, spans_from_leaves
from models.attendance import Attendance
from models.leave_request import LeaveRequest
from tests.conftest import TestingSessionLocal


def _report(monkeypatch, user_id, year, month):
    monkeypatch.setattr(
        "core.detailed_monthly_report_v2.SessionLocal", TestingSessionLocal
    )
    detailed = None
    from core.detailed_monthly_report_v2 import DetailedMonthlyReportGeneratorV2
    gen = DetailedMonthlyReportGeneratorV2()
    try:
        detailed = gen.generate_detailed_report(user_id, year, month)
    finally:
        gen.close()
    legal = LegalOvertimeMonthlyReportGenerator()
    try:
        legal_report = legal.generate_report(user_id, year, month)
    finally:
        legal.close()
    return detailed, legal_report


def _day(report, g_date):
    return next(day for day in report["days"] if day["date"] == g_date)


def test_mehr_sick_span_matches_across_reports(db, make_user, monkeypatch):
    creds = make_user()
    start = jdatetime.date(1404, 7, 1).togregorian()
    end = jdatetime.date(1404, 7, 14).togregorian()
    back = jdatetime.date(1404, 7, 15).togregorian()
    db.add(LeaveRequest(
        user_id=creds["user_id"],
        leave_type="SL",
        from_date=start,
        to_date=end,
        days_count=10,
        status="A",
        employer_pays_wages=True,
    ))
    db.add(Attendance(
        user_id=creds["user_id"],
        timestamp=datetime(back.year, back.month, back.day, 8, 0),
        punch=0,
        source="M",
        is_deleted=False,
    ))
    db.add(Attendance(
        user_id=creds["user_id"],
        timestamp=datetime(back.year, back.month, back.day, 16, 0),
        punch=1,
        source="M",
        is_deleted=False,
    ))
    db.commit()

    detailed, legal = _report(monkeypatch, creds["user_id"], 1404, 7)
    assert detailed["success"] and legal["success"]
    span = spans_from_leaves([
        type("L", (), {
            "id": 1, "leave_type": "SL", "from_date": start, "to_date": end,
            "status": "A", "employer_pays_wages": True,
        })()
    ])[0]

    for day in detailed["days"]:
        legal_day = _day(legal, day["date"])
        assert day["person_status"] == legal_day["person_status"]
        assert day["work_hours"] == legal_day["work_hours"]
        assert day["daily_duty"] == legal_day["daily_duty"]
        if start <= day["date"] <= end:
            assert day["sick_covered"] is True
            assert day["employer_pay_label"] == "حقوق بر عهده کارفرما هست"
            assert day["work_hours"] == 0
            assert day["person_status"] != "A"
            effect = effect_for_span(
                span,
                is_friday=day["is_friday"],
                is_holiday=day["is_holiday"],
                is_weekly_rest=day["person_status"] == "R",
                is_mission=day["person_status"] == "M",
            )
            counted = apply_work_hours(8, effect)
            assert counted["work_hours"] == day["work_hours"]
            if day["is_day_off"] or day["person_status"] in ("H", "R", "M"):
                assert day["person_status"] != "A"
            else:
                assert day["person_status"] == "SL"
                assert day["daily_duty"] == 0
        if day["date"] == back:
            assert day["sick_covered"] is False
            assert day["work_hours"] > 0

    assert detailed["summary"]["absent_days"] == legal["summary"]["absent_days"]
    assert detailed["summary"]["total_work_hours"] == pytest.approx(
        legal["summary"]["total_work_hours"]
    )


def test_unknown_pay_keeps_payroll_hours_and_warns(db, make_user, monkeypatch):
    creds = make_user()
    day = jdatetime.date(1404, 7, 6).togregorian()
    db.add(LeaveRequest(
        user_id=creds["user_id"],
        leave_type="SL",
        from_date=day,
        to_date=day,
        days_count=1,
        status="A",
        employer_pays_wages=None,
    ))
    db.add(Attendance(
        user_id=creds["user_id"],
        timestamp=datetime.combine(day, time(8, 0)),
        punch=0,
        source="M",
        is_deleted=False,
    ))
    db.add(Attendance(
        user_id=creds["user_id"],
        timestamp=datetime.combine(day, time(16, 0)),
        punch=1,
        source="M",
        is_deleted=False,
    ))
    db.commit()
    detailed, _legal = _report(monkeypatch, creds["user_id"], 1404, 7)
    row = _day(detailed, day)
    assert row["work_hours"] == 0
    assert row["payroll_work_hours"] > 0
    assert row["sick_payment_unknown"] is True
    assert any("نامشخص" in text for text in detailed["sick_warnings"])


def test_pending_sick_does_not_change_attendance_status(db, make_user, monkeypatch):
    creds = make_user()
    day = jdatetime.date(1404, 7, 6).togregorian()
    db.add(LeaveRequest(
        user_id=creds["user_id"],
        leave_type="SL",
        from_date=day,
        to_date=day,
        days_count=1,
        status="P",
    ))
    db.commit()
    detailed, _legal = _report(monkeypatch, creds["user_id"], 1404, 7)
    row = _day(detailed, day)
    assert row["sick_covered"] is False
    assert row["person_status"] == "N"
    assert any("تأییدنشده" in text for text in detailed["sick_warnings"])
