"""
Phase 9 — Regression برای خروجی‌های monthly-full (Print / PDF / Excel).

مسیرهای تست‌شده:
    Screen : POST /reports/monthly-full
    PDF    : GET  /reports/monthly-full/export-pdf
    Excel  : GET  /reports/monthly-full/export-excel
    Print  : همان صفحه Screen + CSS چاپ

قاعده: هر سه خروجی از یک report data source (Central Attendance Engine از
طریق DetailedMonthlyReportGeneratorV2) می‌آیند و هیچ‌کدام attendance را دوباره
محاسبه نمی‌کنند.
"""
import io
from datetime import timedelta

import pytest

from tests.conftest import TestingSessionLocal, login_as
from tests.test_monthly_full_central_engine import (
    _cleanup_holiday,
    _seed_report_month,
)
from tests.test_attendance_route_regression import (
    G_END,
    G_START,
    J_MONTH,
    J_YEAR,
)

EXCEL_MEDIA_TYPE = (
    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
)
XLSX_MAGIC = b'PK\x03\x04'


@pytest.fixture()
def monthly_full(db, make_user, monkeypatch):
    """Admin + کارمند با یک ماهِ داده‌دار، به‌همراه پاکسازی تعطیلات."""
    monkeypatch.setattr(
        "core.detailed_monthly_report_v2.SessionLocal", TestingSessionLocal)
    admin = make_user(role='super_admin', balance_al=None)
    target = make_user(role='user', balance_al=30, department='4')
    _seed_report_month(db, target['user_id'])
    try:
        yield {'admin': admin, 'target': target}
    finally:
        _cleanup_holiday(db)


def _params(user_id):
    return {
        'target_user_id': user_id,
        'year': J_YEAR,
        'month': J_MONTH,
    }


def _generate_report(user_id):
    """همان داده‌ای که هر سه خروجی باید از آن تغذیه شوند."""
    from core.detailed_monthly_report_v2 import (
        DetailedMonthlyReportGeneratorV2,
    )

    generator = DetailedMonthlyReportGeneratorV2()
    try:
        report = generator.generate_detailed_report(
            user_id, J_YEAR, J_MONTH)
    finally:
        generator.close()
    assert report.get('success'), report.get('message')
    return report


def _summary_cells(workbook):
    """برچسب → مقدار از شیت «خلاصه ماهانه»."""
    cells = {}
    for row in workbook['خلاصه ماهانه'].iter_rows(values_only=True):
        if row and isinstance(row[0], str):
            cells[row[0]] = row[1]
    return cells


def _fmt_hours(value):
    """همان فرمت HH:MM که exporter در شیت خلاصه استفاده می‌کند."""
    if value is None:
        return '00:00'
    total_minutes = int(round(float(value) * 60))
    sign = '-' if total_minutes < 0 else ''
    total_minutes = abs(total_minutes)
    hours = total_minutes // 60
    minutes = total_minutes % 60
    return f"{sign}{hours:02d}:{minutes:02d}"


def _fmt_cell_hours(value):
    """فرمت شیت روزانه: صفر به‌جای «-» نمایش داده می‌شود."""
    if value == 0:
        return '-'
    return _fmt_hours(value)


# ---------------------------------------------------------------------------
# Excel
# ---------------------------------------------------------------------------
class TestExcelExport:
    def test_returns_valid_xlsx(self, client, monthly_full):
        from openpyxl import load_workbook

        admin = monthly_full['admin']
        uid = monthly_full['target']['user_id']
        login_as(client, admin['national_code'])

        resp = client.get(
            '/reports/monthly-full/export-excel', params=_params(uid))

        assert resp.status_code == 200
        assert resp.headers['content-type'].startswith(EXCEL_MEDIA_TYPE)
        assert resp.headers['content-disposition'].startswith('attachment;')
        assert resp.content.startswith(XLSX_MAGIC)

        # هدر filename باید ASCII باشد (هدر HTTP فقط latin-1 است)
        disposition = resp.headers['content-disposition']
        plain = disposition.split(';')[1]
        assert plain.strip().isascii(), plain
        # نام فارسی کامل از طریق filename*=UTF-8'' می‌آید
        assert 'filename*=UTF-8\'\'' in disposition

        wb = load_workbook(io.BytesIO(resp.content))
        assert 'گزارش روزانه' in wb.sheetnames
        assert 'خلاصه ماهانه' in wb.sheetnames

    def test_daily_rows_match_report_data(self, client, monthly_full):
        from openpyxl import load_workbook

        admin = monthly_full['admin']
        uid = monthly_full['target']['user_id']
        login_as(client, admin['national_code'])

        resp = client.get(
            '/reports/monthly-full/export-excel', params=_params(uid))
        assert resp.status_code == 200

        report = _generate_report(uid)
        ws = load_workbook(io.BytesIO(resp.content))['گزارش روزانه']

        headers = [c.value for c in ws[4]][:16]
        assert headers == [
            'تاریخ', 'روز', 'وضعیت روز', 'وضعیت فرد',
            'ورود ۱', 'خروج ۱', 'ورود ۲', 'خروج ۲', 'ورود ۳', 'خروج ۳',
            'وضعیت تردد', 'کارکرد', 'تأخیر', 'تعجیل', 'اضافی', 'کسری',
        ]
        # ستون اضافه‌ای نباید وجود داشته باشد (ادغام سلول با هدرها هم‌تراز است)
        assert ws.cell(row=1, column=17).value is None

        def _fmt_violation(minutes):
            if not minutes:
                return '-'
            return _fmt_cell_hours(int(minutes) / 60.0)

        rows = list(ws.iter_rows(min_row=5, values_only=True))
        assert len(rows) == len(report['days'])
        for row, day in zip(rows, report['days']):
            assert row[0] == day['jalali_date']
            assert row[1] == day['day_name']
            assert row[3] == day['person_status_name']
            assert row[11] == _fmt_cell_hours(day['work_hours'])
            assert row[12] == _fmt_violation(day.get('late_violation_minutes'))
            assert row[13] == _fmt_violation(day.get('early_leave_violation_minutes'))
            assert row[14] == _fmt_cell_hours(day['surplus'])
            assert row[15] == _fmt_cell_hours(day['deficit'])

    def test_night_shift_pairs_preserved_in_excel(self, client, monthly_full):
        """جفت‌های مرز ماه (شیفت شب) باید در اکسل هم دیده شوند."""
        from openpyxl import load_workbook

        admin = monthly_full['admin']
        uid = monthly_full['target']['user_id']
        login_as(client, admin['national_code'])

        resp = client.get(
            '/reports/monthly-full/export-excel', params=_params(uid))
        assert resp.status_code == 200

        report = _generate_report(uid)
        ws = load_workbook(io.BytesIO(resp.content))['گزارش روزانه']
        rows = list(ws.iter_rows(min_row=5, values_only=True))

        # روز اول ماه: خروجِ صبحِ «کامل (ورود دیروز)»
        first = report['days'][0]
        assert first['attendance_status'] == 'کامل (ورود دیروز)'
        first_row = rows[0]
        assert first_row[4] == first['attendance_pairs'][0]['enter'].strftime(
            '%H:%M')
        assert first_row[5] == first['attendance_pairs'][0]['exit'].strftime(
            '%H:%M')
        assert first_row[10] == 'کامل (ورود دیروز)'

    def test_summary_totals_match_report(self, client, monthly_full):
        from openpyxl import load_workbook

        admin = monthly_full['admin']
        uid = monthly_full['target']['user_id']
        login_as(client, admin['national_code'])

        resp = client.get(
            '/reports/monthly-full/export-excel', params=_params(uid))
        assert resp.status_code == 200

        report = _generate_report(uid)
        summary = report['summary']
        cells = _summary_cells(load_workbook(io.BytesIO(resp.content)))

        assert cells['روزهای موظفی'] == summary['duty_days']
        assert cells['ساعات موظفی'] == _fmt_hours(summary['duty_hours'])
        assert cells['حضور (کاری عادی)'] == summary['present_days']
        assert cells['جمعه کاری'] == summary['friday_work_days']
        assert cells['تعطیل کاری'] == summary['holiday_work_days']
        assert cells['مرخصی'] == summary['leave_days']
        assert cells['مأموریت'] == summary['mission_days']
        assert cells['غیبت'] == summary['absent_days']
        assert cells['استراحت'] == summary['rest_days']
        assert cells['تعطیل'] == summary['holiday_days']
        assert cells['کارکرد ماهانه'] == _fmt_hours(
            summary['total_work_hours'])
        assert cells['ساعات صبح'] == _fmt_hours(summary['total_morning'])
        assert cells['ساعات عصر'] == _fmt_hours(summary['total_evening'])
        assert cells['ساعات شب'] == _fmt_hours(summary['total_night'])
        assert cells['جمعه کاری (ساعت)'] == _fmt_hours(
            summary['friday_work_hours'])
        assert cells['تعطیل کاری (ساعت)'] == _fmt_hours(
            summary['holiday_work_hours'])
        assert cells['اضافه کاری هفتگی'] == _fmt_hours(
            summary['weekly_overtime'])
        assert cells['وضعیت نهایی'] == summary['overall_status']

    def test_summary_labels_do_not_hardcode_required_work(self, client,
                                                          monthly_full):
        """اضافه/کسری از Policy می‌آید؛ برچسب نباید مبنای ثابت را نشان دهد."""
        from openpyxl import load_workbook

        admin = monthly_full['admin']
        uid = monthly_full['target']['user_id']
        login_as(client, admin['national_code'])

        resp = client.get(
            '/reports/monthly-full/export-excel', params=_params(uid))
        assert resp.status_code == 200

        ws = load_workbook(io.BytesIO(resp.content))['خلاصه ماهانه']
        labels = [
            row[0] for row in ws.iter_rows(values_only=True)
            if row and isinstance(row[0], str)
        ]
        assert not any('7:20' in label for label in labels)
        assert not any('7.20' in label for label in labels)
        assert 'اضافه کاری روزانه' in labels
        assert 'کسری کار' in labels


# ---------------------------------------------------------------------------
# PDF
# ---------------------------------------------------------------------------
class TestPdfExport:
    def test_returns_valid_pdf(self, client, monthly_full):
        admin = monthly_full['admin']
        uid = monthly_full['target']['user_id']
        login_as(client, admin['national_code'])

        resp = client.get('/reports/monthly-full/export-pdf', params=_params(uid))

        assert resp.status_code == 200
        assert resp.headers['content-type'].startswith('application/pdf')
        assert resp.headers['content-disposition'].startswith('attachment;')
        assert resp.content.startswith(b'%PDF-')
        assert b'%%EOF' in resp.content[-4096:]

        # بخش ASCII نام فایل نباید متن فارسی داشته باشد
        plain = resp.headers['content-disposition'].split(';')[1]
        assert plain.strip().isascii(), plain

    def test_pdf_is_parseable(self, client, monthly_full):
        pypdf = pytest.importorskip('pypdf')

        admin = monthly_full['admin']
        uid = monthly_full['target']['user_id']
        login_as(client, admin['national_code'])

        resp = client.get('/reports/monthly-full/export-pdf', params=_params(uid))
        assert resp.status_code == 200

        reader = pypdf.PdfReader(io.BytesIO(resp.content))
        assert len(reader.pages) >= 1

    def test_pdf_contains_employee_and_month(self, client, monthly_full):
        pypdf = pytest.importorskip('pypdf')

        admin = monthly_full['admin']
        uid = monthly_full['target']['user_id']
        login_as(client, admin['national_code'])

        resp = client.get('/reports/monthly-full/export-pdf', params=_params(uid))
        assert resp.status_code == 200

        report = _generate_report(uid)
        reader = pypdf.PdfReader(io.BytesIO(resp.content))
        text = ''.join(page.extract_text() or '' for page in reader.pages)

        # متن فارسی پس از reshape/bidi به شکل presentation forms و با ترتیب
        # دیداری استخراج می‌شود؛ بنابراین توکن‌های shaping-invariant
        # (تاریخ‌ها و اعداد) و وجود خط عربی بررسی می‌شود.
        assert str(report['year']) in text
        # هر ۳۱ روز ماه در جدول PDF چاپ شده‌اند
        for day in report['days']:
            assert day['jalali_date'] in text
        # متن فارسی واقعاً در فایل وجود دارد (نه جایگزین/خالی)
        assert any('\u0600' <= ch <= '\u06ff' for ch in text)
        # خلاصهٔ ماهانه هم چاپ شده است
        assert any('\u0600' <= ch <= '\u06ff' for ch in
                   (reader.pages[-1].extract_text() or ''))

    def test_pdf_export_does_not_recalculate_attendance(self, client,
                                                       monthly_full,
                                                       monkeypatch):
        import core.detailed_monthly_report_v2 as report_mod

        calls = []
        real = report_mod.compute_day_attendance

        def spy(**kwargs):
            calls.append(kwargs['day'])
            return real(**kwargs)

        monkeypatch.setattr(report_mod, 'compute_day_attendance', spy)

        admin = monthly_full['admin']
        uid = monthly_full['target']['user_id']
        login_as(client, admin['national_code'])

        resp = client.get('/reports/monthly-full/export-pdf', params=_params(uid))
        assert resp.status_code == 200

        # یک فراخوانی به‌ازای هر روز داخل ماه — نه بیشتر
        in_month = [d for d in calls if G_START <= d <= G_END]
        assert len(in_month) == 31
        assert set(in_month) == {
            G_START + timedelta(days=i) for i in range(31)
        }


# ---------------------------------------------------------------------------
# Print
# ---------------------------------------------------------------------------
class TestPrintOutput:
    def test_print_action_exists(self, client, monthly_full):
        admin = monthly_full['admin']
        uid = monthly_full['target']['user_id']
        login_as(client, admin['national_code'])

        resp = client.post('/reports/monthly-full', data=_params(uid))
        assert resp.status_code == 200
        assert 'window.print()' in resp.text

    def test_print_css_exists_and_hides_screen_controls(self):
        from pathlib import Path

        source = Path(
            'web/templates/admin/report_monthly_full.html'
        ).read_text(encoding='utf-8')

        assert '@media print' in source
        assert '@page' in source
        # کنترل‌های فقط-صفحه‌نمایش هنگام چاپ پنهان می‌شوند
        assert '.no-print' in source
        # رنگ پس‌زمینه جدول در چاپ حفظ می‌شود
        assert 'print-color-adjust' in source
        # هدر جدول در هر صفحه تکرار می‌شود
        assert 'table-header-group' in source

    def test_print_css_hides_real_layout_chrome(self):
        """selectorهای چاپ باید با کلاس‌های واقعی base.html بخوانند."""
        from pathlib import Path
        import re

        root = Path('web/templates')
        base = (root / 'base.html').read_text(encoding='utf-8')
        source = (root / 'admin' / 'report_monthly_full.html').read_text(
            encoding='utf-8')

        # کلاس‌های چیدمان واقعی که باید هنگام چاپ پنهان شوند
        for cls in ('app-sidebar', 'app-topbar'):
            assert cls in base, f'{cls} not found in base.html'
            assert re.search(
                r'@media print.*?\.' + cls + r'\b', source, re.S
            ), f'print CSS does not hide .{cls}'

    def test_print_css_does_not_hide_report_content(self):
        """جدول و خلاصه — یعنی محتوای گزارش — باید در چاپ دیده شوند."""
        from pathlib import Path
        import re

        source = Path(
            'web/templates/admin/report_monthly_full.html'
        ).read_text(encoding='utf-8')

        start = source.index('@media print')
        end = source.index('</style>')
        print_css = source[start:end]

        # هیچ قاعده‌ای نباید کلاس جدول یا خلاصه را پنهان کند
        for selector in ('.full-report-table', '.summary-box'):
            pattern = re.compile(
                r'([^{}]*' + re.escape(selector) + r'[^{}]*)\{([^}]*)\}')
            for match in pattern.finditer(print_css):
                assert 'display: none' not in match.group(2), (
                    f'{selector} is hidden in print: {match.group(0)}')
                assert 'display:none' not in match.group(2).replace(' ', ''), (
                    f'{selector} is hidden in print: {match.group(0)}')

    def test_print_css_is_screen_scoped_only(self):
        """print CSS نباید بیرون از @media print اثر بگذارد."""
        from pathlib import Path
        import re

        source = Path(
            'web/templates/admin/report_monthly_full.html'
        ).read_text(encoding='utf-8')

        print_block = re.search(r'@media print\s*\{', source)
        assert print_block is not None
        # از شروع بلوک چاپ تا انتهای style فقط قواعد چاپ هستند
        assert print_block.start() > source.index('.time-empty')

    def test_screen_only_blocks_marked_no_print(self, client, monthly_full):
        """بلوک‌های فقط-صفحه‌نمایش باید کلاس no-print داشته باشند."""
        admin = monthly_full['admin']
        uid = monthly_full['target']['user_id']
        login_as(client, admin['national_code'])

        resp = client.post('/reports/monthly-full', data=_params(uid))
        assert resp.status_code == 200
        html = resp.text

        # فرم انتخاب و دکمه‌های خروجی/چاپ در چاپ نباید بیایند
        assert 'card border-0 shadow-sm mb-4 no-print' in html
        assert 'card border-0 shadow-sm mt-4 no-print' in html
        # ولی جدول و خلاصه چاپ می‌شوند
        assert 'full-report-table' in html
        assert 'summary-box' in html

    def test_screen_ui_structure_preserved(self, client, monthly_full):
        admin = monthly_full['admin']
        uid = monthly_full['target']['user_id']
        login_as(client, admin['national_code'])

        resp = client.post('/reports/monthly-full', data=_params(uid))
        html = resp.text
        assert resp.status_code == 200
        # عناصر اصلی صفحه بدون تغییر باقی مانده‌اند
        assert 'action="/reports/monthly-full"' in html
        assert 'full-report-table' in html
        assert 'summary-box' in html
        assert 'دانلود اکسل' in html
        assert 'دانلود PDF' in html
        assert '۳ جفت ورود/خروج' in html


# ---------------------------------------------------------------------------
# Data consistency: Screen / Excel / PDF از یک منبع
# ---------------------------------------------------------------------------
class TestExportDataConsistency:
    def test_excel_rows_equal_screen_report(self, client, monthly_full):
        from openpyxl import load_workbook

        admin = monthly_full['admin']
        uid = monthly_full['target']['user_id']
        login_as(client, admin['national_code'])

        screen = client.post('/reports/monthly-full', data=_params(uid))
        assert screen.status_code == 200
        excel = client.get(
            '/reports/monthly-full/export-excel', params=_params(uid))
        assert excel.status_code == 200

        report = _generate_report(uid)

        # Screen: عنوان و یک تاریخ شاخص را نشان می‌دهد
        assert report['employee']['full_name'] in screen.text
        assert report['month_name'] in screen.text
        assert report['days'][0]['jalali_date'] in screen.text

        # Excel: همان روزها، همان ترتیب
        ws = load_workbook(io.BytesIO(excel.content))['گزارش روزانه']
        rows = list(ws.iter_rows(min_row=5, values_only=True))
        assert [r[0] for r in rows] == [
            d['jalali_date'] for d in report['days']
        ]

    def test_exports_use_single_report_generation(self, client, monthly_full,
                                                  monkeypatch):
        """هر درخواست export فقط یک بار گزارش می‌سازد."""
        import core.detailed_monthly_report_v2 as report_mod

        calls = []
        real = report_mod.DetailedMonthlyReportGeneratorV2 \
            .generate_detailed_report

        def spy(self, *args, **kwargs):
            calls.append(args)
            return real(self, *args, **kwargs)

        monkeypatch.setattr(
            report_mod.DetailedMonthlyReportGeneratorV2,
            'generate_detailed_report',
            spy,
        )

        admin = monthly_full['admin']
        uid = monthly_full['target']['user_id']
        login_as(client, admin['national_code'])

        for suffix in ('export-excel', 'export-pdf'):
            resp = client.get(
                f'/reports/monthly-full/{suffix}', params=_params(uid))
            assert resp.status_code == 200
            assert len(calls) == (1 if suffix == 'export-excel' else 2)


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------
class TestExportErrorHandling:
    def test_unknown_employee_redirects_with_error(self, client, monthly_full):
        admin = monthly_full['admin']
        login_as(client, admin['national_code'])

        for suffix in ('export-excel', 'export-pdf'):
            resp = client.get(
                f'/reports/monthly-full/{suffix}',
                params=_params('NO-SUCH-USER'),
                follow_redirects=False,
            )
            assert resp.status_code == 302
            assert '/reports/monthly-full?error=' in resp.headers['location']

    def test_invalid_month_redirects_with_error(self, client, monthly_full):
        admin = monthly_full['admin']
        uid = monthly_full['target']['user_id']
        login_as(client, admin['national_code'])

        for suffix in ('export-excel', 'export-pdf'):
            resp = client.get(
                f'/reports/monthly-full/{suffix}',
                params={
                    'target_user_id': uid,
                    'year': J_YEAR,
                    'month': 13,
                },
                follow_redirects=False,
            )
            assert resp.status_code == 302
            assert 'error=' in resp.headers['location']


# ---------------------------------------------------------------------------
# Security: export route ها باید همان سطح دسترسی گزارش اصلی را داشته باشند
# ---------------------------------------------------------------------------
class TestExportAuthorization:
    def test_export_routes_require_login(self, client):
        for suffix in ('export-excel', 'export-pdf'):
            resp = client.get(
                f'/reports/monthly-full/{suffix}',
                params=_params('SOMEONE'),
                follow_redirects=False,
            )
            assert resp.status_code in (302, 307, 401, 403), suffix

    def test_export_routes_reject_non_admin(self, client, make_user):
        user = make_user(role='user', balance_al=30, department='4')
        login_as(client, user['national_code'])
        for suffix in ('export-excel', 'export-pdf'):
            resp = client.get(
                f'/reports/monthly-full/{suffix}',
                params=_params(user['user_id']),
                follow_redirects=False,
            )
            assert resp.status_code in (302, 307, 401, 403), suffix
