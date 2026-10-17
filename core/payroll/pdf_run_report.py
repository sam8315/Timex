"""PDF افقی گزارش لیست حقوق."""
from __future__ import annotations

from typing import Callable, Optional, Sequence

from core.payroll.pdf_payslip import PayslipPDF
from core.payroll.payslip_present import fa_digits, money_text

FIXED_FIELDS = (
    {"code": "user_id", "name": "کد"},
    {"code": "name", "name": "نام"},
    {"code": "membership", "name": "عضویت"},
    {"code": "department", "name": "دپارتمان"},
    {"code": "position", "name": "سمت"},
)
NUMERIC_FIELDS = {"row", "user_id"}
A4_LANDSCAPE_USABLE_MM = 277.0
_PT_STEPS = [9.0 - 0.5 * i for i in range(11)]  # 9 … 4
_PAD_MM = 2.8


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


def cell_text(row: dict, code: str) -> str:
    if code == "row":
        value = row.get("row")
        return "" if value is None else str(value)
    return str(row.get(code) or "")


def plan_layout(
    specs: Sequence[dict],
    usable: float,
    measure: Callable[[str, float], float],
    *,
    steps: Sequence[float] = _PT_STEPS,
) -> dict:
    """بزرگ‌ترین فونت و عرض ستون‌هایی که جمعشان دقیقاً برابر عرض قابل چاپ است.

    هر spec: header, values, wrap. ستون عددی هرگز شکسته نمی‌شود؛ ستون متنی فقط روی فاصله می‌شکند.
    """

    def needs(pt: float) -> list[float]:
        result = []
        for spec in specs:
            header_words = str(spec["header"]).split() or [""]
            longest_header = max(measure(word, pt) for word in header_words)
            values = {str(value) for value in spec["values"] if str(value)}
            if spec["wrap"]:
                words = {word for value in values for word in value.split()}
                longest = max((measure(word, pt) for word in words), default=0.0)
                full = max((measure(value, pt) for value in values), default=0.0)
                body = max(longest, longest_header, min(full, pt * 3.0))
            else:
                full = max((measure(value, pt) for value in values), default=0.0)
                body = max(full, longest_header)
            result.append(body + _PAD_MM)
        return result

    chosen_pt = steps[-1]
    chosen = needs(chosen_pt)
    for pt in steps:
        candidate = needs(pt)
        chosen_pt, chosen = pt, candidate
        if sum(candidate) <= usable:
            break
    total = sum(chosen)
    if not chosen:
        return {"font_pt": chosen_pt, "widths": []}
    if total >= usable:
        widths = [item * usable / total for item in chosen]
    else:
        weights = [item * (2.0 if spec["wrap"] else 1.0) for item, spec in zip(chosen, specs)]
        extra = usable - total
        widths = [item + extra * weight / sum(weights) for item, weight in zip(chosen, weights)]
    widths[-1] += usable - sum(widths)
    return {"font_pt": chosen_pt, "widths": widths}


def report_specs(report: dict, fields: Sequence[dict], columns: Sequence[dict]) -> list[dict]:
    specs = []
    for field in fields:
        specs.append({"header": field["name"], "values": [], "wrap": field["code"] not in NUMERIC_FIELDS, "code": field["code"]})
    for column in columns:
        specs.append({"header": column["name"], "values": [], "wrap": False, "code": column["code"]})
    count = len(fields)

    def add_total(total):
        for index, field in enumerate(fields):
            if field["code"] == "name":
                specs[index]["values"].append(total["label"])
        for index, column in enumerate(columns):
            specs[count + index]["values"].append(money_text(total["amounts"].get(column["code"], 0)))

    for section in report.get("sections") or []:
        for row in section.get("rows") or []:
            for index, field in enumerate(fields):
                specs[index]["values"].append(cell_text(row, field["code"]))
            for index, column in enumerate(columns):
                specs[count + index]["values"].append(money_text(row["amounts"].get(column["code"], 0)))
        if section.get("subtotal"):
            add_total(section["subtotal"])
    if report.get("grand_total"):
        add_total(report["grand_total"])
    return specs


def estimate_measure(text: str, pt: float) -> float:
    """برآورد عرض متن برای HTML (میلی‌متر)؛ کمی محافظه‌کارانه."""
    return len(str(text)) * pt * 0.3528 * 0.6


def report_fields(report: dict) -> list[dict]:
    return list(report.get("fields") or FIXED_FIELDS)


def build_run_report_pdf(
    report: dict,
    *,
    title: str,
    period_label: str,
    monochrome: bool,
    approvals: Optional[Sequence[dict]] = None,
) -> bytes:
    """approvals: متن آمادهٔ نمایش {name, role, time} به ترتیب مراحل گردش؛ زمان فقط برای مرحلهٔ تأییدشده."""
    approvals = list(approvals or [])
    numbered = _render(
        report, title=title, period_label=period_label, monochrome=monochrome,
        page_numbers=True, approvals=approvals,
    )
    if numbered.page <= 1:
        numbered = _render(
            report, title=title, period_label=period_label, monochrome=monochrome,
            page_numbers=False, approvals=approvals,
        )
    return bytes(numbered.output())


def _make_measure(pdf: RunReportPDF) -> Callable[[str, float], float]:
    cache: dict[str, float] = {}
    ref = 10.0
    pdf.set_font(pdf.font_family_name, "", ref)

    def measure(text: str, pt: float) -> float:
        key = str(text)
        if key not in cache:
            cache[key] = pdf.get_string_width(pdf._rtl(key))
        return cache[key] * pt / ref

    return measure


def _render(report, *, title, period_label, monochrome, page_numbers, approvals=()) -> RunReportPDF:
    pdf = RunReportPDF(monochrome=monochrome, page_numbers=page_numbers)
    pdf.add_page()
    pdf.set_line_width(0.35 if monochrome else 0.2)
    pdf.set_font(pdf.font_family_name, "B", 14)
    pdf.cell_rtl(0, 8, title, ln=1, align="C")
    pdf.ln(2)

    columns = report.get("columns") or []
    fields = report_fields(report)
    usable = pdf.w - pdf.l_margin - pdf.r_margin
    specs = report_specs(report, fields, columns)
    layout = plan_layout(specs, usable, _make_measure(pdf))
    widths = layout["widths"]
    pdf.table_font = layout["font_pt"]
    headers = [field["name"] for field in fields] + [column["name"] for column in columns]

    def paint_header():
        _row(
            pdf,
            headers,
            widths,
            bold=True,
            fill=not monochrome,
            fill_rgb=(33, 90, 70),
            text_rgb=(255, 255, 255) if not monochrome else (0, 0, 0),
        )

    paint_header()
    for section in report.get("sections") or []:
        for row in section.get("rows") or []:
            values = [cell_text(row, field["code"]) for field in fields]
            values.extend(money_text(row["amounts"].get(column["code"], 0)) for column in columns)
            _row(pdf, values, widths, bold=False, fill=False, text_rgb=(0, 0, 0), paint_header=paint_header)
        subtotal = section.get("subtotal")
        if subtotal:
            _total_row(pdf, subtotal, columns, fields, widths, monochrome, paint_header, grand=False)
    grand = report.get("grand_total")
    if grand:
        _total_row(pdf, grand, columns, fields, widths, monochrome, paint_header, grand=True)
    if approvals:
        _approval_boxes(pdf, approvals)
    return pdf


APPROVAL_PER_ROW = 4
_APPROVAL_GAP = 2.0
_NAME_LINE_H = 5.0
_ROLE_LINE_H = 4.5
_TIME_LINE_H = 5.0


def _approval_entry_height(pdf, item: dict, width: float) -> float:
    pdf.set_font(pdf.font_family_name, "B", 10)
    height = _NAME_LINE_H * max(len(_wrap(pdf, item.get("name", ""), width)[:2]), 1)
    role = item.get("role") or ""
    if role:
        pdf.set_font(pdf.font_family_name, "", 8.5)
        height += _ROLE_LINE_H * len(_wrap(pdf, role, width)[:2])
    if item.get("time"):
        height += _TIME_LINE_H
    return height


def _approval_boxes(pdf, approvals: Sequence[dict]) -> None:
    """متن تأییدکنندگان، چهار تا در هر ردیف و از راست به چپ به ترتیب مراحل.

    بدون عنوان و بدون کادر. هر ردیف کامل در یک صفحه می‌ماند و فقط اگر جا نباشد به صفحهٔ بعد می‌رود.
    """
    usable = pdf.w - pdf.l_margin - pdf.r_margin
    width = (usable - _APPROVAL_GAP * (APPROVAL_PER_ROW - 1)) / APPROVAL_PER_ROW
    pdf.ln(3)
    for start in range(0, len(approvals), APPROVAL_PER_ROW):
        chunk = list(approvals[start:start + APPROVAL_PER_ROW])
        height = max(_approval_entry_height(pdf, item, width) for item in chunk)
        if pdf.get_y() + height > pdf.page_break_trigger:
            pdf.add_page()
        y = pdf.get_y()
        for index, item in enumerate(chunk):
            x = pdf.w - pdf.r_margin - (index + 1) * width - index * _APPROVAL_GAP
            _approval_text(pdf, x, y, width, item)
        pdf.set_xy(pdf.l_margin, y + height + _APPROVAL_GAP)


def _approval_text(pdf, x: float, y: float, width: float, item: dict) -> None:
    cursor = y
    pdf.set_text_color(0, 0, 0)
    pdf.set_font(pdf.font_family_name, "B", 10)
    for line in _wrap(pdf, item.get("name", ""), width)[:2]:
        pdf.set_xy(x, cursor)
        pdf.cell_rtl(width, _NAME_LINE_H, line, align="C")
        cursor += _NAME_LINE_H
    role = item.get("role") or ""
    if role:
        pdf.set_font(pdf.font_family_name, "", 8.5)
        for line in _wrap(pdf, role, width)[:2]:
            pdf.set_xy(x, cursor)
            pdf.cell_rtl(width, _ROLE_LINE_H, line, align="C")
            cursor += _ROLE_LINE_H
    stamp = item.get("time") or ""
    if stamp:
        pdf.set_font(pdf.font_family_name, "", 9)
        pdf.set_xy(x, cursor)
        pdf.cell_rtl(width, _TIME_LINE_H, stamp, align="C")


def _total_row(pdf, total, columns, fields, widths, monochrome, paint_header, *, grand: bool) -> None:
    values = [total["label"] if field["code"] == "name" else "" for field in fields]
    values.extend(money_text(total["amounts"].get(column["code"], 0)) for column in columns)
    fill_rgb = (214, 232, 220) if grand else (232, 244, 236)
    _row(
        pdf,
        values,
        widths,
        bold=True,
        fill=not monochrome,
        fill_rgb=fill_rgb,
        text_rgb=(0, 0, 0),
        paint_header=paint_header,
    )


def _wrap(pdf, text: str, width: float) -> list[str]:
    """شکستن فقط روی فاصله؛ عددِ بدون فاصله هیچ‌وقت شکسته نمی‌شود."""
    text = str(text or "")
    limit = width - 2 * pdf.c_margin
    if not text or pdf.get_string_width(pdf._rtl(text)) <= limit:
        return [text]
    lines: list[str] = []
    current = ""
    for word in text.split():
        trial = f"{current} {word}".strip()
        if current and pdf.get_string_width(pdf._rtl(trial)) > limit:
            lines.append(current)
            current = word
        else:
            current = trial
    if current:
        lines.append(current)
    return lines or [text]


def _row(
    pdf,
    values,
    widths,
    *,
    bold: bool,
    fill: bool,
    text_rgb=(0, 0, 0),
    fill_rgb=(255, 255, 255),
    paint_header: Optional[Callable[[], None]] = None,
) -> None:
    size = getattr(pdf, "table_font", 8)
    pdf.set_font(pdf.font_family_name, "B" if bold else "", size)
    line_h = max(4.0, size * 0.3528 * 1.45)
    wrapped = [_wrap(pdf, value, width) for value, width in zip(values, widths)]
    height = max((len(lines) for lines in wrapped), default=1) * line_h + 1.2
    if paint_header is not None and pdf.get_y() + height > pdf.page_break_trigger:
        pdf.add_page()
        paint_header()
        pdf.set_font(pdf.font_family_name, "B" if bold else "", size)
    pdf.set_text_color(*text_rgb)
    pdf.set_draw_color(0, 0, 0)
    if fill:
        pdf.set_fill_color(*fill_rgb)
    x = pdf.l_margin
    y = pdf.get_y()
    for lines, width in zip(wrapped, widths):
        pdf.rect(x, y, width, height, style="DF" if fill else "D")
        offset = (height - len(lines) * line_h) / 2
        for index, line in enumerate(lines):
            pdf.set_xy(x, y + offset + index * line_h)
            pdf.cell_rtl(width, line_h, line, align="R")
        x += width
    pdf.set_xy(pdf.l_margin, y + height)
