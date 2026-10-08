"""خروجی PDF فیش حقوقی."""
from __future__ import annotations

from typing import Any, List
import os

from fpdf import FPDF

from core.payroll.payslip_present import fa_digits, line_detail, money_text, payslip_sort_key

try:
    import arabic_reshaper
    from bidi.algorithm import get_display

    RTL_SUPPORT = True
except ImportError:
    RTL_SUPPORT = False


class PayslipPDF(FPDF):
    def __init__(self):
        super().__init__(orientation="P", unit="mm", format="A4")
        self.font_path = self._find_persian_font()
        if self.font_path:
            self.add_font("PayFont", "", self.font_path)
            self.add_font("PayFont", "B", self.font_path)
            self.font_family_name = "PayFont"
        else:
            self.font_family_name = "Helvetica"

    def _find_persian_font(self) -> str:
        for path in (
            "C:/Windows/Fonts/tahoma.ttf",
            "C:/Windows/Fonts/arial.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        ):
            if os.path.exists(path):
                return path
        return ""

    def _rtl(self, text: str) -> str:
        text = str(text or "")
        if not RTL_SUPPORT:
            return text
        try:
            return get_display(arabic_reshaper.reshape(text))
        except Exception:
            return text

    def cell_rtl(self, w, h, text, border=0, ln=0, align="R", fill=False):
        self.cell(w, h, self._rtl(text), border=border, ln=ln, align=align, fill=fill)


def _draw_side(pdf: PayslipPDF, x: float, y: float, width: float, title: str, rows: List[Any], header_rgb, body_rgb) -> float:
    amount_w = 32
    pdf.set_xy(x, y)
    pdf.set_fill_color(*header_rgb)
    pdf.set_font(pdf.font_family_name, "B", 11)
    pdf.cell_rtl(width, 8, title, border=1, align="C", fill=True)
    y += 8
    pdf.set_fill_color(*body_rgb)
    if not rows:
        pdf.set_xy(x, y)
        pdf.set_font(pdf.font_family_name, "", 9)
        pdf.cell_rtl(width, 8, "موردی نیست", border=1, align="C", fill=True)
        return y + 8
    for item in rows:
        pdf.set_font(pdf.font_family_name, "B", 9)
        pdf.set_xy(x, y)
        pdf.cell_rtl(amount_w, 6, money_text(item.amount), border="LTR", align="C", fill=True)
        pdf.cell_rtl(width - amount_w, 6, item.component_name, border="LTR", align="R", fill=True)
        y += 6
        pdf.set_font(pdf.font_family_name, "", 8)
        pdf.set_xy(x, y)
        pdf.cell_rtl(width, 5, line_detail(item), border="LRB", align="R", fill=True)
        y += 5
    return y


def build_payslip_pdf(result: Any, items: List[Any], period_label: str, profile: dict | None = None) -> bytes:
    pdf = PayslipPDF()
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=16)
    margin = 14
    pdf.set_left_margin(margin)
    pdf.set_right_margin(margin)
    pdf.set_y(16)

    pdf.set_font(pdf.font_family_name, "B", 14)
    pdf.cell_rtl(0, 9, "فیش حقوقی", ln=1, align="C")
    pdf.set_font(pdf.font_family_name, "", 11)
    pdf.cell_rtl(0, 7, f"دوره {fa_digits(period_label)}", ln=1, align="C")
    pdf.ln(1)
    _draw_profile(pdf, result, profile, period_label)
    pdf.ln(3)

    ordered = sorted(items, key=payslip_sort_key)
    earnings = [row for row in ordered if row.kind != "deduction"]
    deductions = [row for row in ordered if row.kind == "deduction"]

    gap = 4
    usable = 210 - 2 * margin
    width = (usable - gap) / 2
    ded_x = margin
    earn_x = margin + width + gap
    top = pdf.get_y()
    earn_bottom = _draw_side(
        pdf, earn_x, top, width, "درآمدها", earnings, (214, 240, 223), (244, 251, 246)
    )
    ded_bottom = _draw_side(
        pdf, ded_x, top, width, "کسورات", deductions, (248, 222, 222), (253, 246, 246)
    )
    y = max(earn_bottom, ded_bottom) + 4
    full = usable

    pdf.set_xy(margin, y)
    pdf.set_font(pdf.font_family_name, "B", 11)
    pdf.set_fill_color(229, 246, 234)
    pdf.cell_rtl(full / 2, 9, f"جمع درآمد: {money_text(result.gross_earnings)}", border=1, align="C", fill=True)
    pdf.set_fill_color(251, 234, 234)
    pdf.cell_rtl(full / 2, 9, f"جمع کسورات: {money_text(result.total_deductions)}", border=1, align="C", fill=True)
    pdf.set_xy(margin, y + 9)
    pdf.set_fill_color(244, 247, 251)
    pdf.cell_rtl(full, 10, f"خالص پرداختی: {money_text(result.net_pay)}", border=1, align="C", fill=True)

    bottom = pdf.get_y() + 6
    pdf.set_draw_color(31, 78, 121)
    pdf.set_line_width(0.6)
    pdf.rect(8, 8, 194, max(20, bottom - 8))

    out = pdf.output()
    if isinstance(out, (bytes, bytearray)):
        return bytes(out)
    return out.encode("latin-1")


def _profile_rows(result: Any, profile: dict | None, period_label: str) -> list[tuple[str, str]]:
    if profile:
        covered = f"{profile.get('covered_days') or '—'} از {profile.get('month_days') or '—'} روز"
        return [
            ("نام", str(profile.get("name") or "—")),
            ("کد پرسنلی", str(profile.get("user_id") or "—")),
            ("کد ملی", str(profile.get("national_code") or "—")),
            ("نام پدر", str(profile.get("father_name") or "—")),
            ("سمت", str(profile.get("position") or "—")),
            ("تاریخ استخدام", str(profile.get("hire_date") or "—")),
            ("تأهل", str(profile.get("marital") or "—")),
            ("عضویت", str(profile.get("membership") or "—")),
            ("پوشش قرارداد", covered),
            ("دوره", fa_digits(period_label)),
            ("جنسیت", str(profile.get("gender") or "—")),
        ]
    return [
        ("نام", str(result.employee_name or "—")),
        ("کد پرسنلی", fa_digits(result.user_id)),
        ("عضویت", str(result.membership_type_code or "—")),
        ("پوشش قرارداد", f"{money_text(result.covered_days)} از {money_text(result.month_days)} روز"),
    ]


def _draw_profile(pdf: PayslipPDF, result: Any, profile: dict | None, period_label: str) -> None:
    rows = _profile_rows(result, profile, period_label)
    x = pdf.l_margin
    width = 210 - pdf.l_margin - pdf.r_margin
    y = pdf.get_y()
    pdf.set_fill_color(241, 245, 249)
    pdf.set_draw_color(180, 196, 214)
    pdf.set_font(pdf.font_family_name, "B", 10)
    pdf.set_xy(x, y)
    pdf.cell_rtl(width, 7, "مشخصات فردی", border=1, align="C", fill=True)
    y += 7
    col_w = width / 2
    pdf.set_font(pdf.font_family_name, "", 8)
    for index in range(0, len(rows), 2):
        pair = rows[index:index + 2]
        pdf.set_xy(x, y)
        for label, value in pair:
            pdf.cell_rtl(col_w, 6, f"{label}: {value}", border=1, align="R", fill=True)
        if len(pair) == 1:
            pdf.cell_rtl(col_w, 6, "", border=1, fill=True)
        y += 6
    pdf.set_y(y)
