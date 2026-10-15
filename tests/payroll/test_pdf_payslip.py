from pathlib import Path
from types import SimpleNamespace as NS

import pytest

from core.payroll import pdf_payslip
from core.payroll.pdf_payslip import FONT_DIR, build_payslip_pdf, render_payslip_pdf

TEMPLATES = Path(__file__).resolve().parents[2] / "web" / "templates"


def _item(code, name, kind, amount, unit=None, qty=None, note=None, order=100):
    return NS(component_code=code, component_name=name, kind=kind, amount=amount,
              unit_amount=unit, quantity=qty, calc_note=note, sort_order=order)


def _result():
    return NS(employee_name="علی رضایی", user_id=1024, membership_type_code="P",
              covered_days=29, month_days=30, gross_earnings=383_845_678,
              total_deductions=32_500_000, net_pay=351_345_678)


def _profile():
    return {"name": "علی رضایی", "user_id": "۱۰۲۴", "national_code": "۰۰۱۲۳۴۵۶۷۸",
            "father_name": "محمد", "position": "کارشناس فنی", "hire_date": "۱۳۹۸/۰۲/۰۱",
            "marital": "متأهل", "membership": "رسمی", "covered_days": "۲۹",
            "month_days": "۳۰", "gender": "مرد"}


def _items(repeat=1):
    base = [
        _item("DAILY_WAGE", "حقوق پایه", "earning", 299_000_000, 10_386_145, 29),
        _item("SENIORITY", "پایه سنوات", "earning", 8_500_000, 300_000, 29),
        _item("HOUSING", "حق مسکن", "earning", 9_000_000, 9_000_000, 29),
        _item("CHILD_ALLOWANCE", "حق اولاد", "earning", 30_000_000, 10_386_145, 3),
        _item("OVERTIME", "اضافه کار", "earning", 12_345_678, 1_234_567, 10),
        _item("WORK_DEFICIT", "کسر کار", "deduction", 2_500_000, 590_000, 4.5, order=10),
        _item("INSURANCE_EMPLOYEE", "بیمه سهم کارمند", "deduction", 25_000_000, 7, 357_000_000, order=20),
        _item("TAX", "مالیات", "deduction", 5_000_000, 10, 50_000_000, order=30),
    ]
    return base * repeat


def test_regular_payslip_is_one_page_at_full_scale():
    pdf = render_payslip_pdf(_result(), _items(), "1405/07", _profile())
    assert pdf.pages_count == 1
    assert pdf.scale_used == 1.0


def test_long_payslip_is_scaled_down_to_one_page():
    pdf = render_payslip_pdf(_result(), _items(repeat=4), "1405/07", _profile())
    assert pdf.pages_count == 1
    assert pdf_payslip.MIN_SCALE <= pdf.scale_used < 1.0


def test_build_returns_single_page_pdf_bytes():
    data = build_payslip_pdf(_result(), _items(repeat=3), "1405/07", _profile())
    assert data.startswith(b"%PDF")
    assert b"/Count 1" in data


@pytest.mark.skipif(not (FONT_DIR / "Vazirmatn-Regular.ttf").exists(), reason="project font missing")
def test_uses_project_vazirmatn_font_with_real_bold():
    pdf = render_payslip_pdf(_result(), _items(), "1405/07", _profile())
    assert pdf.font_path.endswith("Vazirmatn-Regular.ttf")
    assert str(pdf.fonts["payfontB"].ttffile).endswith("Vazirmatn-Bold.ttf")


def test_falls_back_to_reshaper_without_shaping_engine(monkeypatch):
    monkeypatch.setattr(pdf_payslip, "SHAPING_SUPPORT", False)
    pdf = render_payslip_pdf(_result(), _items(repeat=2), "1405/07", _profile())
    assert pdf.shaping is False
    assert pdf.pages_count == 1


def test_profile_less_payslip_renders():
    pdf = render_payslip_pdf(_result(), [], "1405/07", None)
    assert pdf.pages_count == 1


def test_payslip_templates_fit_print_to_one_page():
    body = (TEMPLATES / "payroll" / "_payslip_body.html").read_text(encoding="utf-8")
    assert "@page { size: A4 portrait" in body
    assert "@media screen and (max-width: 768px)" in body
    assert "body.payslip-print-mode .payslip-box" in body
    for page in ("payroll/payslip_detail.html", "admin/payroll_run_detail.html"):
        assert "/static/js/payslip_print.js" in (TEMPLATES / page).read_text(encoding="utf-8")
