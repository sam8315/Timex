"""
خروجی چاپ / PDF گزارش کامل و تفصیلی ماهانه.

- فردی: یک صفحه A4
- گروهی: یک صفحه به ازای هر نفر، فیلتر نوع عضویت
- گزارش تفصیلی قبلاً خروجی نداشت؛ مسیرهای export اضافه شده‌اند
"""
import io

import pytest

from tests.conftest import TestingSessionLocal, login_as
from tests.test_monthly_full_central_engine import (
    _cleanup_holiday,
    _seed_report_month,
)
from tests.test_attendance_route_regression import (
    J_MONTH,
    J_YEAR,
)


@pytest.fixture()
def monthly_ctx(db, make_user, monkeypatch):
    monkeypatch.setattr(
        "core.detailed_monthly_report_v2.SessionLocal", TestingSessionLocal)
    admin = make_user(role='super_admin', balance_al=None)
    target = make_user(role='user', balance_al=30, department='4')
    _seed_report_month(db, target['user_id'])
    try:
        yield {
            'admin': admin,
            'target': target,
        }
    finally:
        _cleanup_holiday(db)


def _params(user_id):
    return {
        'target_user_id': user_id,
        'year': J_YEAR,
        'month': J_MONTH,
    }


def _group_params(employment_type='4'):
    return {
        'year': J_YEAR,
        'month': J_MONTH,
        'employment_type': employment_type,
    }


def _login(client, monthly_ctx):
    login_as(client, monthly_ctx['admin']['national_code'])


# ---------------------------------------------------------------------------
# PDF یک‌صفحه‌ای (فردی)
# ---------------------------------------------------------------------------
class TestOnePagePdf:
    def test_individual_pdf_is_exactly_one_page(self, monthly_ctx):
        from core.detailed_monthly_report_v2 import (
            DetailedMonthlyReportGeneratorV2,
        )
        from core.pdf_detailed_export_v2 import DetailedPDFExporterV2

        uid = monthly_ctx['target']['user_id']
        generator = DetailedMonthlyReportGeneratorV2()
        try:
            report = generator.generate_detailed_report(
                uid, J_YEAR, J_MONTH)
        finally:
            generator.close()
        assert report.get('success')

        exporter = DetailedPDFExporterV2()
        pdf, font_name = exporter._new_pdf()
        pdf.add_page()
        exporter._render_employee_page(pdf, report, font_name)
        assert pdf.page_no() == 1

    def test_full_export_pdf_route_one_page(self, client, monthly_ctx):
        pypdf = pytest.importorskip('pypdf')
        _login(client, monthly_ctx)
        uid = monthly_ctx['target']['user_id']

        resp = client.get(
            '/reports/monthly-full/export-pdf', params=_params(uid))
        assert resp.status_code == 200
        reader = pypdf.PdfReader(io.BytesIO(resp.content))
        assert len(reader.pages) == 1

    def test_detailed_export_pdf_route_one_page(self, client, monthly_ctx):
        pypdf = pytest.importorskip('pypdf')
        _login(client, monthly_ctx)
        uid = monthly_ctx['target']['user_id']

        resp = client.get(
            '/reports/monthly-detailed/export-pdf', params=_params(uid))
        assert resp.status_code == 200
        assert resp.content.startswith(b'%PDF-')
        reader = pypdf.PdfReader(io.BytesIO(resp.content))
        assert len(reader.pages) == 1


# ---------------------------------------------------------------------------
# گزارش تفصیلی — خروجی‌هایی که قبلاً نبود
# ---------------------------------------------------------------------------
class TestDetailedExports:
    def test_export_excel(self, client, monthly_ctx):
        _login(client, monthly_ctx)
        uid = monthly_ctx['target']['user_id']

        resp = client.get(
            '/reports/monthly-detailed/export-excel', params=_params(uid))
        assert resp.status_code == 200
        assert resp.content[:4] == b'PK\x03\x04'

    def test_export_pdf(self, client, monthly_ctx):
        _login(client, monthly_ctx)
        uid = monthly_ctx['target']['user_id']

        resp = client.get(
            '/reports/monthly-detailed/export-pdf', params=_params(uid))
        assert resp.status_code == 200
        assert resp.content.startswith(b'%PDF-')

    def test_screen_has_print_and_export_buttons(self, client, monthly_ctx):
        _login(client, monthly_ctx)
        uid = monthly_ctx['target']['user_id']

        resp = client.post(
            '/reports/monthly-detailed', data=_params(uid))
        assert resp.status_code == 200
        html = resp.text
        assert 'دانلود اکسل' in html
        assert 'دانلود PDF' in html
        assert 'window.print()' in html
        assert 'چاپ گروهی' in html
        assert 'PDF گروهی' in html
        assert '@media print' in html
        assert 'print-one-page' in html


# ---------------------------------------------------------------------------
# خروجی گروهی بر اساس نوع عضویت
# ---------------------------------------------------------------------------
class TestGroupByEmployment:
    def test_full_group_pdf(self, client, monthly_ctx):
        _login(client, monthly_ctx)

        resp = client.get(
            '/reports/monthly-full/export-pdf-group',
            params=_group_params('4'),
        )
        assert resp.status_code == 200
        assert resp.content.startswith(b'%PDF-')

    def test_detailed_group_pdf(self, client, monthly_ctx):
        _login(client, monthly_ctx)

        resp = client.get(
            '/reports/monthly-detailed/export-pdf-group',
            params=_group_params('4'),
        )
        assert resp.status_code == 200
        assert resp.content.startswith(b'%PDF-')

    def test_group_pdf_pages_match_employee_count(self, monthly_ctx):
        from core.pdf_detailed_export_v2 import DetailedPDFExporterV2
        from core.detailed_monthly_report_v2 import (
            DetailedMonthlyReportGeneratorV2,
        )

        uid = monthly_ctx['target']['user_id']
        generator = DetailedMonthlyReportGeneratorV2()
        try:
            report = generator.generate_detailed_report(
                uid, J_YEAR, J_MONTH)
        finally:
            generator.close()

        exporter = DetailedPDFExporterV2()
        pdf, font_name = exporter._new_pdf()
        for _ in range(2):
            pdf.add_page()
            exporter._render_employee_page(pdf, report, font_name)
        assert pdf.page_no() == 2

    def test_full_print_group_page(self, client, monthly_ctx):
        _login(client, monthly_ctx)

        resp = client.get(
            '/reports/monthly-full/print-group',
            params=_group_params('4'),
        )
        assert resp.status_code == 200, getattr(resp, 'headers', {})
        html = resp.text
        assert 'print-employee-page' in html
        assert 'page-break-after: always' in html
        assert monthly_ctx['target']['user_id'] in html
        assert 'چاپ گروهی' in html

    def test_detailed_print_group_page(self, client, monthly_ctx):
        _login(client, monthly_ctx)

        resp = client.get(
            '/reports/monthly-detailed/print-group',
            params=_group_params('4'),
        )
        assert resp.status_code == 200, getattr(resp, 'headers', {})
        assert 'print-employee-page' in resp.text

    def test_group_filters_by_employment_type(
            self, client, monthly_ctx, make_user):
        other = make_user(role='user', balance_al=30, department='1')
        _login(client, monthly_ctx)

        resp = client.get(
            '/reports/monthly-full/print-group',
            params=_group_params('4'),
        )
        assert resp.status_code == 200, getattr(resp, 'headers', {})
        assert monthly_ctx['target']['user_id'] in resp.text
        assert other['user_id'] not in resp.text

    def test_invalid_employment_type_redirects(self, client, monthly_ctx):
        _login(client, monthly_ctx)

        resp = client.get(
            '/reports/monthly-full/export-pdf-group',
            params=_group_params('99'),
            follow_redirects=False,
        )
        assert resp.status_code == 302
        location = resp.headers.get('location', '')
        assert '/reports/monthly-full' in location
        assert 'error=' in location


# ---------------------------------------------------------------------------
# CSS چاپ یک‌صفحه‌ای
# ---------------------------------------------------------------------------
class TestPrintCssOnePage:
    def test_full_has_one_page_print_rules(self):
        from pathlib import Path
        source = Path(
            'web/templates/admin/report_monthly_full.html'
        ).read_text(encoding='utf-8')
        assert 'print-one-page' in source
        assert 'page-break-inside: avoid' in source
        assert 'margin: 6mm' in source

    def test_detailed_has_print_and_group_ui(self):
        from pathlib import Path
        source = Path(
            'web/templates/admin/report_monthly_detailed.html'
        ).read_text(encoding='utf-8')
        assert '@media print' in source
        assert 'print-one-page' in source
        assert 'PDF گروهی' in source
        assert 'چاپ گروهی' in source
        assert 'دانلود PDF' in source
