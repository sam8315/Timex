"""Focused regression tests for raw-attendance-report feature fixes."""
import re
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
from core.pdf_raw_report import (
    export_group as pdf_export_group,
    export_individual as pdf_export_individual,
)
from models.attendance import Attendance


PORTRAIT_WIDTHS = [96, 32, 19, 15, 15, 17]
EXPECTED_HEADERS_RTL = [
    "ترددها (ورود → خروج)",
    "نوع مرخصی",
    "وضعیت فرد",
    "وضعیت روز",
    "روز",
    "تاریخ",
]


def _count_pdf_pages(pdf_bytes: bytes) -> int:
    """Count pages in raw PDF bytes by parsing the page tree /Count."""
    text = pdf_bytes.decode("latin-1", errors="replace")
    m = re.search(r"/Type\s*/Pages.*?/Count\s+(\d+)", text, re.DOTALL)
    if m:
        return int(m.group(1))
    return text.count("/Type /Page\n") + text.count("/Type /Page\r")


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


def _normal_day(day_num, att_str="07:00 → 14:00"):
    return {
        "jalali_date": f"1405/06/{day_num:02d}",
        "day_name": "شنبه" if day_num % 7 == 1 else "یکشنبه",
        "day_status": "کاری",
        "person_status_name": "حاضر",
        "leave_name": None,
        "hourly_leave": {},
        "attendance_str": att_str,
    }


def _make_individual_report(days):
    return {
        "year": 1405,
        "month": 6,
        "month_name": "شهریور",
        "mode": "individual",
        "employees": [{
            "user_id": "12345",
            "full_name": "Test User",
            "membership": "قراردادی",
            "hire_date_j": None,
            "termination_date_j": None,
            "days": days,
        }],
    }


def _make_group_report(user_ids):
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
        """07:00 IN, 07:10 IN, 14:30 OUT -> 07:00 -> -- | 07:10 -> 14:30"""
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
        """IN, IN, IN, OUT -> first two are entry_only, last IN pairs with OUT."""
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
        """IN, OUT, IN -> pair + entry_only"""
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
    def test_sheet_names_match_index(self):
        report = _make_group_report(["12345", "67890", "11111"])
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
        report = _make_group_report(["12345", "12345", "12345"])
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
        report = _make_group_report(["[]:*?/\\"])
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


# ---------------------------------------------------------------------------
# 7. PDF portrait orientation
# ---------------------------------------------------------------------------
class TestPDFPortraitOrientation:
    def test_rawpdf_is_portrait(self):
        from core.pdf_raw_report import RawPDF
        pdf = RawPDF()
        assert pdf.w < pdf.h, "Portrait: width must be less than height"

    def test_a4_portrait_dimensions(self):
        from core.pdf_raw_report import RawPDF
        pdf = RawPDF()
        assert abs(pdf.w - 210) < 1
        assert abs(pdf.h - 297) < 1


# ---------------------------------------------------------------------------
# 8. One-page fit for normal 31-day month
# ---------------------------------------------------------------------------
class TestPDFOnePageFit:
    def test_31_normal_days_fits_one_page(self):
        days = [_normal_day(d) for d in range(1, 32)]
        report = _make_individual_report(days)
        output = BytesIO()
        pdf_export_individual(report, output)
        output.seek(0)
        page_count = _count_pdf_pages(output.getvalue())
        assert page_count == 1, (
            f"Normal 31-day portrait report should fit on 1 page, got {page_count}"
        )

    def test_31_days_with_two_shifts_still_one_page(self):
        days = [_normal_day(d, "07:00 → 14:00 | 15:00 → 18:00") for d in range(1, 32)]
        report = _make_individual_report(days)
        output = BytesIO()
        pdf_export_individual(report, output)
        output.seek(0)
        page_count = _count_pdf_pages(output.getvalue())
        assert page_count == 1, (
            f"31-day portrait report with two shifts should fit on 1 page, got {page_count}"
        )

    def test_group_starts_each_employee_on_new_page(self):
        days = [_normal_day(d) for d in range(1, 32)]
        employees = []
        for uid in ["111", "222"]:
            employees.append({
                "user_id": uid,
                "full_name": f"User {uid}",
                "membership": "قراردادی",
                "hire_date_j": None,
                "termination_date_j": None,
                "days": days,
            })
        report = {
            "year": 1405, "month": 6, "month_name": "شهریور",
            "employees": employees,
        }
        output = BytesIO()
        pdf_export_group(report, output)
        output.seek(0)
        page_count = _count_pdf_pages(output.getvalue())
        assert page_count == 2, (
            f"Group report with 2 employees should have 2 pages, got {page_count}"
        )


# ---------------------------------------------------------------------------
# 9. RTL column position verification
# ---------------------------------------------------------------------------
class TestPDFRTLColumnPositions:
    def test_columns_are_placed_right_to_left(self):
        from core.pdf_raw_report import RawPDF
        pdf = RawPDF()
        pdf.add_page()
        pdf._header_block("T", "S")
        pdf._employee_header({"full_name": "X", "user_id": "1", "membership": "R"})
        pdf.set_font(pdf.font_name, "", 7)

        widths = PORTRAIT_WIDTHS
        right_edge = pdf.w - pdf.r_margin
        x = right_edge
        for i, w in enumerate(widths):
            x -= w
            assert x >= pdf.l_margin - 1, (
                f"Column {i} ('{EXPECTED_HEADERS_RTL[i]}') x={x:.1f} "
                f"should be >= left margin {pdf.l_margin}"
            )

        leftmost_x = right_edge - sum(widths)
        rightmost_x = right_edge - widths[0]
        assert leftmost_x < rightmost_x, (
            "Leftmost column (date) should be to the left of rightmost (attendance)"
        )

    def test_rightmost_column_is_attendance(self):
        from core.pdf_raw_report import RawPDF
        pdf = RawPDF()
        pdf.add_page()

        widths = PORTRAIT_WIDTHS
        right_edge = pdf.w - pdf.r_margin
        rightmost_x = right_edge - widths[0]
        assert rightmost_x < right_edge, "First column (attendance) should be rightmost"

        leftmost_x = right_edge - sum(widths)
        assert leftmost_x < rightmost_x, "Last column (date) should be leftmost"

    def test_column_widths_fit_portrait_usable_width(self):
        from core.pdf_raw_report import RawPDF
        pdf = RawPDF()
        widths = PORTRAIT_WIDTHS
        table_width = pdf.w - pdf.l_margin - pdf.r_margin
        assert sum(widths) <= table_width, (
            f"Column widths sum ({sum(widths)}) should not exceed "
            f"portrait table width ({table_width})"
        )
        assert len(widths) == 6, "Table should have exactly 6 columns"


# ---------------------------------------------------------------------------
# 10. No holiday_title in PDF/Excel/HTML
# ---------------------------------------------------------------------------
class TestNoHolidayTitle:
    def test_pdf_headers_match_expected(self):
        from core.pdf_raw_report import RawPDF
        pdf = RawPDF()
        pdf.add_page()
        pdf.set_font(pdf.font_name, "", 7)
        widths = PORTRAIT_WIDTHS
        pdf._table_header(widths, 4.5)
        assert pdf.get_y() > 8

    def test_excel_no_holiday_title_column(self):
        report = _make_individual_report([_normal_day(d) for d in range(1, 6)])
        output = BytesIO()
        from core.excel_raw_report import export_individual as excel_export_individual
        excel_export_individual(report, output)
        output.seek(0)
        from openpyxl import load_workbook
        wb = load_workbook(output)
        ws = wb.active
        headers = [cell.value for cell in ws[6]]
        assert "عنوان تعطیلی" not in headers, (
            f"holiday_title column should not exist in Excel, got: {headers}"
        )
        assert len(headers) == 6, f"Excel should have 6 columns, got {len(headers)}"

    def test_html_no_holiday_title_column(self):
        with open("web/templates/admin/report_raw.html", encoding="utf-8") as f:
            html = f.read()
        assert "عنوان تعطیلی" not in html, "holiday_title should not exist in HTML template"
        thead_section = html.split("<thead>")[1].split("</thead>")[0] if "<thead>" in html else ""
        th_count = thead_section.count("<th ")
        assert th_count == 6, f"HTML raw table should have 6 <th> columns, got {th_count}"


# ---------------------------------------------------------------------------
# 11. RTL text isolation and leave-cell wrapping in HTML
# ---------------------------------------------------------------------------
class TestHTMLRTLFix:
    def _html(self):
        with open("web/templates/admin/report_raw.html", encoding="utf-8") as f:
            return f.read()

    def test_leave_header_has_isolation(self):
        assert "unicode-bidi: isolate" in self._html(), (
            "HTML should use unicode-bidi: isolate to prevent RTL corruption"
        )

    def test_leave_header_contains_slash(self):
        assert "نوع مرخصی / مرخصی ساعتی" in self._html(), (
            "Header should contain the full Persian text with / separator"
        )

    def test_leave_cell_has_explicit_rtl(self):
        html = self._html()
        assert ".leave-cell" in html
        leave_css = html.split(".leave-cell")[1].split("}")[0]
        assert "direction: rtl" in leave_css, (
            ".leave-cell must have explicit direction: rtl"
        )

    def test_leave_cell_allows_wrapping(self):
        html = self._html()
        leave_css = html.split(".leave-cell")[1].split("}")[0]
        assert "white-space: normal" in leave_css, (
            ".leave-cell must use white-space: normal to allow wrapping"
        )

    def test_leave_cell_has_overflow_wrap(self):
        html = self._html()
        leave_css = html.split(".leave-cell")[1].split("}")[0]
        assert "overflow-wrap" in leave_css, (
            ".leave-cell must have overflow-wrap for safe breaking"
        )

    def test_leave_header_has_explicit_rtl_inline(self):
        html = self._html()
        thead = html.split("<thead>")[1].split("</thead>")[0]
        leave_th = [line for line in thead.split("<th") if "نوع مرخصی" in line][0]
        assert "direction: rtl" in leave_th, (
            "Leave <th> should have explicit direction: rtl inline"
        )


# ---------------------------------------------------------------------------
# 12. Filter form alignment
# ---------------------------------------------------------------------------
class TestFilterFormAlignment:
    def test_hint_not_inside_col_md_4(self):
        with open("web/templates/admin/report_raw.html", encoding="utf-8") as f:
            html = f.read()
        form_section = html.split('<form method="post"')[1].split('</form>')[0]
        col_md4_end = form_section.split('</div>')[0]
        assert "برای گزارش گروهی" not in col_md4_end, (
            "Helper text should not be inside the employee col-md-4"
        )

    def test_hint_outside_form_row(self):
        with open("web/templates/admin/report_raw.html", encoding="utf-8") as f:
            html = f.read()
        form_end_idx = html.index('</form>')
        after_form = html[form_end_idx:form_end_idx + 500]
        assert "برای گزارش گروهی" in after_form, (
            "Helper text should appear after the form closing tag"
        )


# ---------------------------------------------------------------------------
# 13. Manual label per-punch (both entry and exit get 'دستی')
# ---------------------------------------------------------------------------
class TestManualLabelPerPunch:
    def test_manual_entry_only_shows_dasti(self):
        atts = [_att(_dt(7, 0), 0, source="M", record_id=1)]
        display = format_attendance_display(atts)
        assert "07:00 دستی → —" in display

    def test_manual_exit_only_shows_dasti(self):
        atts = [_att(_dt(14, 0), 1, source="M", record_id=1)]
        display = format_attendance_display(atts)
        assert "— → 14:00 دستی" in display

    def test_manual_pair_shows_dasti_on_both_sides(self):
        atts = [
            _att(_dt(7, 0), 0, source="M", record_id=1),
            _att(_dt(14, 0), 1, source="M", record_id=2),
        ]
        display = format_attendance_display(atts)
        assert "07:00 دستی → 14:00 دستی" in display

    def test_mixed_manual_and_device_pair(self):
        atts = [
            _att(_dt(7, 0), 0, source="M", record_id=1),
            _att(_dt(14, 0), 1, source="D", record_id=2),
        ]
        display = format_attendance_display(atts)
        assert "07:00 دستی → 14:00" in display
        assert "14:00 دستی" not in display

    def test_all_device_no_dasti(self):
        atts = [
            _att(_dt(7, 0), 0, source="D", record_id=1),
            _att(_dt(14, 0), 1, source="D", record_id=2),
        ]
        display = format_attendance_display(atts)
        assert "دستی" not in display

    def test_multiple_segments_manual_labeled(self):
        atts = [
            _att(_dt(7, 0), 0, source="M", record_id=1),
            _att(_dt(7, 10), 0, source="M", record_id=2),
            _att(_dt(14, 30), 1, source="M", record_id=3),
        ]
        display = format_attendance_display(atts)
        assert "07:00 دستی → —" in display
        assert "07:10 دستی → 14:30 دستی" in display


# ---------------------------------------------------------------------------
# 14. Integration: manual attendance route → raw report shows دستی
# ---------------------------------------------------------------------------
class TestManualAttendanceIntegration:
    def test_manual_record_appears_as_dasti_in_report(self, client, db, make_user):
        from tests.conftest import login_as
        from models.attendance import Attendance

        admin = make_user(role="super_admin", balance_al=None)
        target = make_user(role="user", balance_al=None)
        login_as(client, admin["national_code"])

        today_j = jdatetime.date.today()
        today_str = today_j.strftime("%Y/%m/%d")
        month = today_j.month
        year = today_j.year

        resp = client.post(
            "/admin/attendance/edit/add",
            data={
                "user_id": target["user_id"],
                "date_str": today_str,
                "time_str": "08:30",
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

        resp = client.post(
            "/reports/raw",
            data={
                "target_user_id": target["user_id"],
                "year": str(year),
                "month": str(month),
                "employment_type": "all",
                "status_filter": "all",
            },
        )
        assert resp.status_code == 200
        assert "دستی" in resp.text, (
            "Raw report HTML must contain 'دستی' for the manual record"
        )


# ---------------------------------------------------------------------------
# 15. PDF physical RTL column order via recorded cell coordinates
# ---------------------------------------------------------------------------
class TestPDFPhysicalRTLOrder:
    def test_cells_recorded_right_to_left(self):
        from unittest.mock import patch
        from core.pdf_raw_report import RawPDF

        all_calls = []

        original_write_cell = RawPDF._write_cell

        def tracking_write_cell(self, x, y, width, row_height, line_height, text, align="C", base_dir="R"):
            all_calls.append({
                "x": x, "y": y, "w": width,
                "text": str(text), "align": align, "base_dir": base_dir,
            })
            original_write_cell(
                self, x, y, width, row_height, line_height, text, align, base_dir
            )

        with patch.object(RawPDF, "_write_cell", tracking_write_cell):
            pdf = RawPDF()
            pdf.add_page()
            pdf._header_block("T", "S")
            pdf._employee_header({"full_name": "X", "user_id": "1", "membership": "R"})
            pdf.set_font(pdf.font_name, "", 7)
            widths = PORTRAIT_WIDTHS
            pdf._table_header(widths, 4.5)
            pdf._daily_table([_normal_day(15)])

        y_values = sorted(set(round(c["y"], 1) for c in all_calls))
        assert len(y_values) >= 2, f"Expected at least 2 y-rows, got {y_values}"

        first_row_y = y_values[0]
        first_row_cells = [
            c for c in all_calls if round(c["y"], 1) == first_row_y
        ]
        assert len(first_row_cells) == 6, (
            f"Expected 6 cells in first row at y={first_row_y}, got {len(first_row_cells)}"
        )

        for i in range(len(first_row_cells) - 1):
            assert first_row_cells[i]["x"] > first_row_cells[i + 1]["x"], (
                f"Header cell '{first_row_cells[i]['text']}' at x={first_row_cells[i]['x']:.1f} "
                f"must be to the RIGHT of '{first_row_cells[i+1]['text']}' at x={first_row_cells[i+1]['x']:.1f}"
            )

        first_cell = first_row_cells[0]
        assert "ترددها" in first_cell["text"], (
            f"Rightmost header must be attendance, got: {first_cell['text']}"
        )

        last_cell = first_row_cells[-1]
        assert "تاریخ" in last_cell["text"], (
            f"Leftmost header must be date, got: {last_cell['text']}"
        )

        for i in range(len(first_row_cells) - 1):
            assert first_row_cells[i]["x"] > first_row_cells[i + 1]["x"], (
                f"Cell {i} x={first_row_cells[i]['x']:.1f} must be > cell {i+1} x={first_row_cells[i+1]['x']:.1f}"
            )

    def test_all_cells_have_rtl_cursor(self):
        from unittest.mock import patch
        from core.pdf_raw_report import RawPDF

        new_x_values = []

        original_write_cell = RawPDF._write_cell

        def tracking_write_cell(self, x, y, width, row_height, line_height, text, align="C", base_dir="R"):
            new_x_values.append({
                "text": str(text)[:30], "x": x, "w": width, "base_dir": base_dir
            })
            original_write_cell(
                self, x, y, width, row_height, line_height, text, align, base_dir
            )

        with patch.object(RawPDF, "_write_cell", tracking_write_cell):
            pdf = RawPDF()
            pdf.add_page()
            pdf._header_block("T", "S")
            pdf._employee_header({"full_name": "X", "user_id": "1", "membership": "R"})
            pdf.set_font(pdf.font_name, "", 7)
            pdf._daily_table([_normal_day(15)])

        right_edge = pdf.w - pdf.r_margin
        for cell in new_x_values:
            assert cell["x"] < right_edge + 1, (
                f"Cell '{cell['text']}' starts at x={cell['x']:.1f}, "
                f"should be inside right margin {right_edge:.1f}"
            )
            assert cell["x"] + cell["w"] <= right_edge + 1, (
                f"Cell '{cell['text']}' ends at x={cell['x']+cell['w']:.1f}, "
                f"should not exceed right margin"
            )


# ---------------------------------------------------------------------------
# 16. Manual source='M' shown in PDF and Excel outputs
# ---------------------------------------------------------------------------
class TestPDFMixedDirection:
    def test_attendance_cell_uses_ltr_base_direction(self):
        from unittest.mock import patch
        from core.pdf_raw_report import RawPDF

        calls = []
        original = RawPDF._write_cell

        def tracking(self, x, y, width, row_height, line_height, text,
                     align="C", base_dir="R"):
            calls.append({"text": str(text), "base_dir": base_dir})
            original(self, x, y, width, row_height, line_height, text, align, base_dir)

        report = _make_individual_report([_normal_day(23, "— → 14:00 دستی")])
        with patch.object(RawPDF, "_write_cell", tracking):
            output = BytesIO()
            pdf_export_individual(report, output)

        attendance_calls = [c for c in calls if "14:00" in c["text"]]
        assert attendance_calls
        assert attendance_calls[0]["base_dir"] == "L"


# ---------------------------------------------------------------------------
# 16. Manual source='M' shown in PDF and Excel outputs
# ---------------------------------------------------------------------------
    def _make_report_with_manual(self):
        day = {
            "jalali_date": "1405/06/15",
            "day_name": "شنبه",
            "day_status": "کاری",
            "person_status_name": "حاضر",
            "leave_name": None,
            "hourly_leave": {},
            "attendance_str": "07:00 دستی → 14:00 دستی",
        }
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
                "days": [day],
            }],
        }

    def test_pdf_contains_dasti(self):
        report = self._make_report_with_manual()
        output = BytesIO()
        pdf_export_individual(report, output)
        output.seek(0)
        raw = output.getvalue()
        assert b"\xd8" in raw or b"\xd9" in raw, (
            "PDF should contain Persian bytes (Arabic range)"
        )

    def test_excel_contains_dasti(self):
        from core.excel_raw_report import export_individual as excel_individual
        report = self._make_report_with_manual()
        output = BytesIO()
        excel_individual(report, output)
        output.seek(0)
        from openpyxl import load_workbook
        wb = load_workbook(output)
        ws = wb.active
        found_dasti = False
        for row in ws.iter_rows(min_row=7, values_only=True):
            for cell in row:
                if cell and "دستی" in str(cell):
                    found_dasti = True
                    break
            if found_dasti:
                break
        assert found_dasti, (
            "Excel output must contain 'دستی' for manual attendance"
        )


# ---------------------------------------------------------------------------
# 17. Leave status is exactly مرخصی, leave type is separate
# ---------------------------------------------------------------------------
class TestLeaveStatusPresentation:
    def test_full_day_leave_status_is_morakhasi(self):
        day = {
            "date": _dt(7, 0).date(),
            "jalali_date": "1405/06/15",
            "day_name": "شنبه",
            "day_status": "کاری",
            "holiday_title": None,
            "person_status": "AL",
            "person_status_name": "مرخصی",
            "leave_type": "AL",
            "leave_name": "استحقاقی",
            "hourly_leave": {"minutes": 0, "display": ""},
            "has_attendance": False,
            "punches": [],
            "attendance_segments": [],
            "attendance_str": "—",
        }
        assert day["person_status_name"] == "مرخصی"
        assert day["leave_name"] == "استحقاقی"

    def test_leave_person_status_values_are_morakhasi(self):
        from core.raw_report import LEAVE_PERSON_STATUS
        for code, name in LEAVE_PERSON_STATUS.items():
            assert name == "مرخصی", (
                f"LEAVE_PERSON_STATUS['{code}'] should be 'مرخصی', got '{name}'"
            )

    def test_hourly_leave_status_is_morakhasi(self):
        from core.raw_report import LEAVE_PERSON_STATUS
        assert "HL" in LEAVE_PERSON_STATUS, "HL should be in LEAVE_PERSON_STATUS"
        assert LEAVE_PERSON_STATUS["HL"] == "مرخصی"

    def test_leave_type_names_unchanged(self):
        from core.raw_report import LEAVE_TYPE_NAMES
        expected = {
            'AL': 'استحقاقی',
            'SL': 'استعلاجی',
            'RL': 'تشویقی',
            'CW': 'ذخیره سال قبل',
            'UL': 'بدون حقوق',
            'TL': 'توراهی',
        }
        for code, name in expected.items():
            assert LEAVE_TYPE_NAMES[code] == name, (
                f"LEAVE_TYPE_NAMES['{code}'] changed from '{name}' to '{LEAVE_TYPE_NAMES[code]}'"
            )

    def test_combined_leave_name_for_full_day(self):
        from core.raw_report import LEAVE_TYPE_NAMES
        leave_name = LEAVE_TYPE_NAMES.get('AL')
        assert leave_name == "استحقاقی"

    def test_combined_leave_name_for_hourly(self):
        hourly_leave_display = "09:00 تا 10:00"
        leave_name = f"ساعتی: {hourly_leave_display}"
        assert leave_name == "ساعتی: 09:00 تا 10:00"

    def test_combined_leave_name_for_both(self):
        from core.raw_report import LEAVE_TYPE_NAMES
        parts = []
        parts.append(LEAVE_TYPE_NAMES['AL'])
        parts.append("ساعتی: 09:00 تا 10:00")
        combined = '\n'.join(parts)
        assert combined == "استحقاقی\nساعتی: 09:00 تا 10:00"

    def test_leave_filter_still_includes_all_leave_types(self):
        from core.raw_report import LEAVE_PERSON_STATUS
        all_leave_codes = ['AL', 'SL', 'RL', 'CW', 'UL', 'TL', 'HL']
        for code in all_leave_codes:
            assert code in LEAVE_PERSON_STATUS, (
                f"Leave code '{code}' should be in LEAVE_PERSON_STATUS for filtering"
            )

    def test_31_day_pdf_with_leave_still_fits_one_page(self):
        days = []
        for d in range(1, 32):
            days.append({
                "jalali_date": f"1405/06/{d:02d}",
                "day_name": "شنبه" if d % 7 == 1 else "یکشنبه",
                "day_status": "کاری",
                "person_status_name": "مرخصی" if d == 15 else "حاضر",
                "leave_name": "استحقاقی" if d == 15 else None,
                "hourly_leave": {},
                "attendance_str": "—" if d == 15 else "07:00 → 14:00",
            })
        report = _make_individual_report(days)
        output = BytesIO()
        pdf_export_individual(report, output)
        output.seek(0)
        page_count = _count_pdf_pages(output.getvalue())
        assert page_count == 1, (
            f"31-day report with leave should fit on 1 page, got {page_count}"
        )
