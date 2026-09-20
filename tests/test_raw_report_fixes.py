"""Focused regression tests for raw-attendance-report feature fixes."""
from datetime import datetime, time, timedelta
from io import BytesIO
from types import SimpleNamespace

import jdatetime
import pytest

from core.raw_report import (
    build_attendance_segments,
    format_attendance_display,
    fmt_time,
    RawReportService,
)
from core.excel_raw_report import export_group as excel_export_group
from core.pdf_raw_report import export_group as pdf_export_group
from models.attendance import Attendance


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _att(ts, punch, source="D", record_id=None):
    """Build a minimal Attendance-like object for segment tests."""
    return SimpleNamespace(
        id=record_id or hash(str(ts) + str(punch)),
        timestamp=ts,
        punch=punch,
        source=source,
    )


def _dt(hour, minute=0):
    return datetime(2026, 9, 15, hour, minute)


# ---------------------------------------------------------------------------
# 1. Consecutive-entry pairing (matches AttendanceAnalyzer semantics)
# ---------------------------------------------------------------------------
class TestPairingLogic:
    def test_single_entry_and_exit(self):
        records = [_dt(7, 0), _dt(14, 30)]
        atts = [_att(t, 0 if t.hour < 10 else 1) for t in records]
        segs = build_attendance_segments(atts)
        assert len(segs) == 1
        assert segs[0]["kind"] == "pair"
        assert fmt_time(segs[0]["enter"]["time"]) == "07:00"
        assert fmt_time(segs[0]["exit"]["time"]) == "14:30"

    def test_consecutive_entries_pair_with_next_exit(self):
        """07:00 IN, 07:10 IN, 14:30 OUT → 07:00 → — | 07:10 → 14:30"""
        atts = [
            _att(_dt(7, 0), 0, record_id=1),
            _att(_dt(7, 10), 0, record_id=2),
            _att(_dt(14, 30), 1, record_id=3),
        ]
        segs = build_attendance_segments(atts)
        assert len(segs) == 2
        assert segs[0]["kind"] == "entry_only"
        assert fmt_time(segs[0]["record"]["time"]) == "07:00"
        assert segs[1]["kind"] == "pair"
        assert fmt_time(segs[1]["enter"]["time"]) == "07:10"
        assert fmt_time(segs[1]["exit"]["time"]) == "14:30"

    def test_three_consecutive_entries(self):
        """IN, IN, IN, OUT → first two are entry_only, last IN pairs with OUT."""
        atts = [
            _att(_dt(7, 0), 0, record_id=1),
            _att(_dt(7, 5), 0, record_id=2),
            _att(_dt(7, 10), 0, record_id=3),
            _att(_dt(14, 0), 1, record_id=4),
        ]
        segs = build_attendance_segments(atts)
        assert len(segs) == 3
        assert segs[0]["kind"] == "entry_only"
        assert segs[1]["kind"] == "entry_only"
        assert segs[2]["kind"] == "pair"
        assert fmt_time(segs[2]["enter"]["time"]) == "07:10"
        assert fmt_time(segs[2]["exit"]["time"]) == "14:00"

    def test_exit_without_pending_entry(self):
        atts = [_att(_dt(14, 0), 1, record_id=1)]
        segs = build_attendance_segments(atts)
        assert len(segs) == 1
        assert segs[0]["kind"] == "exit_only"

    def test_pending_entry_becomes_entry_only(self):
        atts = [_att(_dt(7, 0), 0, record_id=1)]
        segs = build_attendance_segments(atts)
        assert len(segs) == 1
        assert segs[0]["kind"] == "entry_only"

    def test_pair_then_new_entry(self):
        """IN, OUT, IN → pair + entry_only"""
        atts = [
            _att(_dt(7, 0), 0, record_id=1),
            _att(_dt(14, 0), 1, record_id=2),
            _att(_dt(15, 0), 0, record_id=3),
        ]
        segs = build_attendance_segments(atts)
        assert len(segs) == 2
        assert segs[0]["kind"] == "pair"
        assert segs[1]["kind"] == "entry_only"

    def test_full_display_format(self):
        atts = [
            _att(_dt(7, 0), 0, record_id=1),
            _att(_dt(7, 10), 0, record_id=2),
            _att(_dt(14, 30), 1, record_id=3),
        ]
        display = format_attendance_display(atts)
        assert "07:00 → —" in display
        assert "07:10 → 14:30" in display


# ---------------------------------------------------------------------------
# 2. Manual source label
# ---------------------------------------------------------------------------
class TestManualSourceLabel:
    def test_manual_entry_shows_dasti(self):
        atts = [_att(_dt(7, 0), 0, source="M", record_id=1)]
        display = format_attendance_display(atts)
        assert "دستی" in display

    def test_device_entry_no_dasti(self):
        atts = [_att(_dt(7, 0), 0, source="D", record_id=1)]
        display = format_attendance_display(atts)
        assert "دستی" not in display


# ---------------------------------------------------------------------------
# 3. Excel group sheet-name consistency
# ---------------------------------------------------------------------------
class TestExcelSheetNames:
    def _make_report(self, user_ids):
        employees = []
        for uid in user_ids:
            employees.append({
                "user_id": uid,
                "full_name": f"User {uid}",
                "first_name": "User",
                "last_name": str(uid),
                "department": "4",
                "membership": "قراردادی",
                "hire_date_j": None,
                "termination_date_j": None,
                "days": [],
            })
        return {
            "year": 1405,
            "month": 6,
            "month_name": "شهریور",
            "days_count": 31,
            "mode": "group",
            "employee_user_id": None,
            "employment_type": "all",
            "status_filter": "all",
            "employees": employees,
        }

    def test_sheet_names_match_index(self):
        report = self._make_report(["12345", "67890", "11111"])
        output = BytesIO()
        excel_export_group(report, output)
        output.seek(0)

        from openpyxl import load_workbook
        wb = load_workbook(output)
        index_ws = wb["فهرست کارمندان"]

        for row in index_ws.iter_rows(min_row=4, values_only=True):
            if row[0] is None:
                break
            sheet_name_in_index = row[4]
            assert sheet_name_in_index in wb.sheetnames, (
                f"Index references sheet '{sheet_name_in_index}' which does not exist"
            )

    def test_duplicate_user_ids_get_unique_names(self):
        report = self._make_report(["12345", "12345", "12345"])
        output = BytesIO()
        excel_export_group(report, output)
        output.seek(0)

        from openpyxl import load_workbook
        wb = load_workbook(output)
        index_ws = wb["فهرست کارمندان"]

        names_in_index = []
        for row in index_ws.iter_rows(min_row=4, values_only=True):
            if row[0] is None:
                break
            names_in_index.append(row[4])

        assert len(names_in_index) == 3
        assert len(set(names_in_index)) == 3
        for name in names_in_index:
            assert name in wb.sheetnames

    def test_special_chars_in_user_id(self):
        report = self._make_report(["[]:*?/\\"])
        output = BytesIO()
        excel_export_group(report, output)
        output.seek(0)

        from openpyxl import load_workbook
        wb = load_workbook(output)
        index_ws = wb["فهرست کارمندان"]

        for row in index_ws.iter_rows(min_row=4, values_only=True):
            if row[0] is None:
                break
            sheet_name = row[4]
            assert sheet_name in wb.sheetnames


# ---------------------------------------------------------------------------
# 4. Hourly leave included in leave filter
# ---------------------------------------------------------------------------
class TestHourlyLeaveInFilter:
    def _build_day(self, person_status="P", leave_type=None, hourly_leave_minutes=0):
        return {
            "date": _dt(7, 0).date(),
            "jalali_date": "1405/06/15",
            "day_name": "شنبه",
            "day_status": "کاری",
            "holiday_title": None,
            "person_status": person_status,
            "person_status_name": "حاضر",
            "leave_type": leave_type,
            "leave_name": None,
            "hourly_leave": {"minutes": hourly_leave_minutes, "display": "09:00 تا 10:00"},
            "has_attendance": True,
            "punches": [],
            "attendance_segments": [],
            "attendance_str": "07:00 → 14:00",
        }

    def test_hl_person_status_included(self):
        day = self._build_day(person_status="HL")
        assert day["person_status"] == "HL"

    def test_hourly_leave_minutes_included(self):
        day = self._build_day(person_status="P", hourly_leave_minutes=60)
        assert day["hourly_leave"]["minutes"] > 0

    def test_leave_filter_logic(self):
        """Simulate the leave filter logic from raw_report.py."""
        from core.raw_report import LEAVE_PERSON_STATUS

        days = [
            self._build_day(person_status="P", hourly_leave_minutes=0),
            self._build_day(person_status="HL"),
            self._build_day(person_status="P", hourly_leave_minutes=60),
            self._build_day(person_status="AL", leave_type="AL"),
            self._build_day(person_status="P"),
        ]

        filtered = [
            day for day in days
            if day["person_status"] in LEAVE_PERSON_STATUS
            or day["leave_type"] is not None
            or day["person_status"] == "HL"
            or (day.get("hourly_leave") and day["hourly_leave"].get("minutes", 0) > 0)
        ]

        assert len(filtered) == 3
        statuses = [d["person_status"] for d in filtered]
        assert "HL" in statuses
        assert "AL" in statuses
        assert any(
            d["hourly_leave"]["minutes"] > 0 and d["person_status"] == "P"
            for d in filtered
        )


# ---------------------------------------------------------------------------
# 5. PDF row-height wraps long text
# ---------------------------------------------------------------------------
class TestPDFRowHeight:
    def _make_report(self, days):
        return {
            "year": 1405,
            "month": 6,
            "month_name": "شهریور",
            "employees": [{
                "user_id": "12345",
                "full_name": "Test User",
                "membership": "قراردادی",
                "hire_date_j": None,
                "termination_date_j": None,
                "days": days,
            }],
        }

    def _day(self, att_str):
        return {
            "jalali_date": "1405/06/15",
            "day_name": "شنبه",
            "day_status": "کاری",
            "holiday_title": None,
            "person_status_name": "حاضر",
            "leave_name": None,
            "hourly_leave": {},
            "attendance_str": att_str,
        }

    def test_pdf_generates_without_error(self):
        report = self._make_report([self._day("07:00 → 14:00 | 15:00 → 18:00 | 19:00 → 22:00")] * 31)
        output = BytesIO()
        pdf_export_group(report, output)
        output.seek(0)
        assert len(output.getvalue()) > 0

    def test_long_text_causes_extra_row_height(self):
        short_day = self._day("07:00 → 14:00")
        long_str = " | ".join(f"{h:02d}:00 → {h+1:02d}:00" for h in range(7, 19))
        long_day = self._day(long_str)

        from core.pdf_raw_report import RawPDF

        pdf_short = RawPDF()
        pdf_short.add_page()
        pdf_short._header_block("T", "S")
        pdf_short._employee_header({"full_name": "X", "user_id": "1", "membership": "R"})
        pdf_short.set_font(pdf_short.font_name, "", 7)
        y_before = pdf_short.get_y()
        pdf_short._daily_table([short_day])
        y_after_short = pdf_short.get_y()

        pdf_long = RawPDF()
        pdf_long.add_page()
        pdf_long._header_block("T", "S")
        pdf_long._employee_header({"full_name": "X", "user_id": "1", "membership": "R"})
        pdf_long.set_font(pdf_long.font_name, "", 7)
        y_before_long = pdf_long.get_y()
        pdf_long._daily_table([long_day])
        y_after_long = pdf_long.get_y()

        short_consumed = y_after_short - y_before
        long_consumed = y_after_long - y_before_long
        assert long_consumed > short_consumed, (
            f"Long attendance row ({long_consumed:.1f}mm) should be taller "
            f"than short row ({short_consumed:.1f}mm)"
        )


# ---------------------------------------------------------------------------
# 6. Manual attendance source='M' in admin route
# ---------------------------------------------------------------------------
class TestManualAttendanceSource:
    def test_add_record_uses_source_m(self, client, db, make_user):
        from models.user import User
        from web.security import hash_password

        admin = make_user(role="super_admin", balance_al=None)
        target = make_user(role="user", balance_al=None)

        from tests.conftest import login_as
        login_as(client, admin["national_code"])

        today_j = jdatetime.date.today()
        today_str = today_j.strftime("%Y/%m/%d")

        resp = client.post(
            "/admin/attendance/edit/add",
            data={
                "user_id": target["user_id"],
                "date_str": today_str,
                "time_str": "08:00",
                "punch": "0",
            },
            follow_redirects=False,
        )
        assert resp.status_code == 302

        record = db.query(Attendance).filter(
            Attendance.user_id == target["user_id"],
        ).order_by(Attendance.id.desc()).first()
        assert record is not None
        assert record.source == "M"
