"""خروجی PDF گزارش خام تردد."""
from io import BytesIO
from pathlib import Path
from typing import List

from fpdf import FPDF

try:
    import arabic_reshaper
    from bidi.algorithm import get_display
except ImportError:
    arabic_reshaper = None
    get_display = None


FONT_PATHS = [
    "C:/Windows/Fonts/b Nazanin.ttf",
    "C:/Windows/Fonts/BNazanin.ttf",
    "C:/Windows/Fonts/tahoma.ttf",
    "C:/Windows/Fonts/arial.ttf",
    "C:/Windows/Fonts/segoeui.ttf",
    "/usr/share/fonts/truetype/tahoma/tahoma.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
]


def _find_font() -> str:
    for path in FONT_PATHS:
        candidate = Path(path)
        if candidate.exists():
            return str(candidate)
    return ""


def _shape(text) -> str:
    value = "" if text is None else str(text)
    if arabic_reshaper is None or get_display is None:
        return value
    if any("\u0600" <= char <= "\u06FF" for char in value):
        return get_display(arabic_reshaper.reshape(value))
    return value


class RawPDF(FPDF):
    def __init__(self):
        super().__init__(orientation="P", unit="mm", format="A4")
        self.set_auto_page_break(auto=True, margin=10)
        self.set_margins(8, 8, 8)
        self.font_path = _find_font()
        self.font_name = "Persian" if self.font_path else "Helvetica"
        if self.font_path:
            self.add_font(self.font_name, "", self.font_path)
            self.add_font(self.font_name, "B", self.font_path)

    def header(self):
        if self.page_no() == 1:
            return
        self.set_font(self.font_name, "", 7)
        self.set_text_color(80, 80, 80)
        self.cell(0, 5, _shape("گزارش خام تردد"), align="L")
        self.ln(5)

    def footer(self):
        self.set_y(-10)
        self.set_font(self.font_name, "", 7)
        self.set_text_color(100, 100, 100)
        self.cell(0, 5, _shape(f"صفحه {self.page_no()}"), align="C")

    def _header_block(self, title: str, subtitle: str):
        self.set_font(self.font_name, "B", 11)
        self.set_text_color(0, 0, 0)
        self.cell(0, 6, _shape(title), ln=True, align="C")
        if subtitle:
            self.set_font(self.font_name, "", 8)
            self.cell(0, 4, _shape(subtitle), ln=True, align="C")
        self.ln(1)

    def _employee_header(self, emp: dict):
        self.set_font(self.font_name, "B", 9)
        self.cell(
            0,
            5,
            _shape(
                f"نام و نام خانوادگی: {emp['full_name']}    "
                f"کد پرسنلی: {emp['user_id']}    نوع عضویت: {emp['membership']}"
            ),
            ln=True,
            align="R",
        )
        extra = []
        if emp.get("hire_date_j"):
            extra.append(f"تاریخ استخدام: {emp['hire_date_j']}")
        if emp.get("termination_date_j"):
            extra.append(f"تاریخ پایان: {emp['termination_date_j']}")
        if extra:
            self.set_font(self.font_name, "", 7.5)
            self.cell(0, 4, _shape("    ".join(extra)), ln=True, align="R")
        self.ln(1)

    @staticmethod
    def _lines(text: str, width: float, font_size: float) -> List[str]:
        return [] if not text else [text]

    def _write_cell(self, x: float, y: float, width: float, row_height: float,
                    line_height: float, text, align: str = "C"):
        self.rect(x, y, width, row_height)
        self.set_xy(x, y)
        self.multi_cell(
            width,
            line_height,
            _shape(str(text)),
            border=0,
            align=align,
            new_x="LEFT",
            new_y="NEXT",
        )

    def _table_header(self, widths: List[float], line_height: float):
        headers = [
            "ترددها (ورود → خروج)", "نوع مرخصی", "وضعیت فرد",
            "وضعیت روز", "روز", "تاریخ",
        ]
        x = self.w - self.r_margin
        y = self.get_y()
        self.set_font(self.font_name, "B", 7.5)
        for index, width in enumerate(widths):
            x -= width
            self._write_cell(x, y, width, line_height, line_height, headers[index], "C")
        self.set_xy(self.l_margin, y + line_height)

    def _daily_table(self, days: list):
        widths = [101, 27, 19, 15, 15, 17]
        line_height = 4.5
        bottom_limit = self.h - self.b_margin - 5
        self._table_header(widths, line_height)
        self.set_font(self.font_name, "", 7)
        for day in days:
            leave_display = day.get("leave_name") or "-"
            values = [
                day["attendance_str"],
                leave_display,
                day["person_status_name"],
                day["day_status"],
                day["day_name"],
                day["jalali_date"],
            ]
            max_lines = 1
            for index, (width, value) in enumerate(zip(widths, values)):
                shaped = _shape(str(value))
                text_width = self.get_string_width(shaped)
                if text_width > width:
                    est_lines = int(text_width / width) + 1
                    max_lines = max(max_lines, est_lines)
            row_height = max(line_height, max_lines * line_height + 0.8)
            if self.get_y() + row_height > bottom_limit:
                self.add_page()
                self._table_header(widths, line_height)
                self.set_font(self.font_name, "", 7)
            y = self.get_y()
            x = self.w - self.r_margin
            for index, (width, value) in enumerate(zip(widths, values)):
                x -= width
                self._write_cell(x, y, width, row_height, line_height, value, "R" if index == 0 else "C")
            self.set_xy(self.l_margin, y + row_height)
        self.ln(1)


def _save_pdf(pdf: RawPDF, output):
    if hasattr(output, "write"):
        pdf.output(output)
        output.seek(0)
    else:
        pdf.output(str(output))
    return output


def export_individual(report: dict, output):
    pdf = RawPDF()
    pdf.add_page()
    emp = report["employees"][0] if report["employees"] else None
    if emp:
        pdf._header_block(
            f"گزارش خام - {emp['full_name']}",
            f"کد: {emp['user_id']} | {report['month_name']} {report['year']}",
        )
        pdf._employee_header(emp)
        pdf._daily_table(emp["days"])
    return _save_pdf(pdf, output)


def export_group(report: dict, output):
    pdf = RawPDF()
    for emp in report["employees"]:
        pdf.add_page()
        pdf._header_block(
            f"گزارش خام - {emp['full_name']}",
            f"کد: {emp['user_id']} | {report['month_name']} {report['year']}",
        )
        pdf._employee_header(emp)
        pdf._daily_table(emp["days"])
    return _save_pdf(pdf, output)
