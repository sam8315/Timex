"""PDF افقی گزارش لیست حقوق."""
from __future__ import annotations

from core.payroll.pdf_payslip import PayslipPDF
from core.payroll.payslip_present import fa_digits, money_text


class RunReportPDF(PayslipPDF):
    def __init__(self, *, monochrome: bool, page_numbers: bool):
        super().__init__(orientation="L")
        self.monochrome = monochrome
        self.page_numbers = page_numbers
        self.alias_nb_pages()
        self.set_auto_page_break(auto=True, margin=14)

    def footer(self):
        if not self.page_numbers:
            return
        self.set_y(-10)
        self.set_text_color(0, 0, 0)
        self.set_font(self.font_family_name, "", 9)
        self.cell_rtl(0, 6, f"صفحه {fa_digits(self.page_no())} از {{nb}}", align="C")


def build_run_report_pdf(report: dict, *, title: str, period_label: str, monochrome: bool) -> bytes:
    numbered = _render(report, title=title, period_label=period_label, monochrome=monochrome, page_numbers=True)
    if numbered.page <= 1:
        numbered = _render(
            report, title=title, period_label=period_label, monochrome=monochrome, page_numbers=False
        )
    return bytes(numbered.output())


def _render(report, *, title, period_label, monochrome, page_numbers) -> RunReportPDF:
    pdf = RunReportPDF(monochrome=monochrome, page_numbers=page_numbers)
    pdf.add_page()
    pdf.set_font(pdf.font_family_name, "B", 14)
    pdf.cell_rtl(0, 8, title, ln=1, align="C")
    pdf.set_font(pdf.font_family_name, "", 10)
    pdf.cell_rtl(0, 6, f"دوره {fa_digits(period_label)}", ln=1, align="C")
    pdf.ln(2)

    columns = report.get("columns") or []
    fields = report.get("fields") or [
        {"code": "user_id", "name": "کد"},
        {"code": "name", "name": "نام"},
        {"code": "membership", "name": "عضویت"},
        {"code": "department", "name": "دپارتمان"},
        {"code": "position", "name": "سمت"},
    ]
    fixed, money = _widths(pdf, len(columns), len(fields))
    pdf.table_font = _font_size(fixed + money)
    headers = [field["name"] for field in fields] + [column["name"] for column in columns]

    def paint_header():
        _row(
            pdf,
            headers,
            fixed + money,
            bold=True,
            fill=not monochrome,
            fill_rgb=(33, 90, 70),
            text_rgb=(255, 255, 255) if not monochrome else (0, 0, 0),
        )

    paint_header()
    for section in report.get("sections") or []:
        for row in section.get("rows") or []:
            values = [_field_text(row, field["code"]) for field in fields]
            values.extend(money_text(row["amounts"].get(column["code"], 0)) for column in columns)
            _maybe_break(pdf, paint_header)
            _row(pdf, values, fixed + money, bold=False, fill=False, text_rgb=(0, 0, 0))
        subtotal = section.get("subtotal")
        if subtotal:
            _total_row(pdf, subtotal, columns, fields, fixed, money, monochrome, paint_header, grand=False)
    grand = report.get("grand_total")
    if grand:
        _total_row(pdf, grand, columns, fields, fixed, money, monochrome, paint_header, grand=True)
    return pdf


def _widths(pdf: RunReportPDF, money_count: int, text_count: int = 5) -> tuple[list[float], list[float]]:
    """عرض‌ها دقیقاً به اندازهٔ صفحهٔ A4 افقی جمع می‌شوند."""
    usable = pdf.w - pdf.l_margin - pdf.r_margin
    text_weights = [2.0 if index == 1 else 1.4 for index in range(text_count)]
    weights = text_weights + [1.3] * money_count
    scale = usable / sum(weights)
    widths = [weight * scale for weight in weights]
    widths[-1] += usable - sum(widths)
    return widths[:text_count], widths[text_count:]


def _font_size(widths: list[float]) -> int:
    narrow = min(widths) if widths else 20
    return max(5, min(8, int(narrow / 2.1)))


def _maybe_break(pdf: RunReportPDF, paint_header) -> None:
    if pdf.get_y() + 7 <= pdf.page_break_trigger:
        return
    pdf.add_page()
    paint_header()


def _field_text(row: dict, code: str) -> str:
    if code == "user_id":
        return row.get("user_id") or ""
    if code == "name":
        return row.get("name") or ""
    return row.get(code) or ""


def _total_row(pdf, total, columns, fields, fixed, money, monochrome, paint_header, *, grand: bool) -> None:
    _maybe_break(pdf, paint_header)
    values = [total["label"] if field["code"] == "name" else "" for field in fields]
    values.extend(money_text(total["amounts"].get(column["code"], 0)) for column in columns)
    fill_rgb = (214, 232, 220) if grand else (232, 244, 236)
    _row(
        pdf,
        values,
        fixed + money,
        bold=True,
        fill=not monochrome,
        fill_rgb=fill_rgb,
        text_rgb=(0, 0, 0),
    )


def _row(pdf, values, widths, *, bold: bool, fill: bool, text_rgb=(0, 0, 0), fill_rgb=(255, 255, 255)) -> None:
    size = getattr(pdf, "table_font", 8)
    pdf.set_font(pdf.font_family_name, "B" if bold else "", size)
    pdf.set_text_color(*text_rgb)
    pdf.set_draw_color(0, 0, 0)
    if fill:
        pdf.set_fill_color(*fill_rgb)
    for value, width in zip(values, widths):
        pdf.cell_rtl(width, 6, str(value or ""), border=1, fill=fill)
    pdf.ln(6)
