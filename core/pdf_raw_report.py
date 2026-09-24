"""خروجی PDF گزارش خام تردد."""
from io import BytesIO
from pathlib import Path
from typing import List

from fpdf import FPDF

from core.raw_report import fmt_time

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

# Attendance cells contain only numbers, arrows, parentheses and the (M)
# marker. Use a font with reliable Unicode symbol coverage for that column.
ATTENDANCE_FONT_PATHS = [
    "C:/Windows/Fonts/segoeui.ttf",
    "C:/Windows/Fonts/tahoma.ttf",
    "C:/Windows/Fonts/arial.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
]


def _find_font() -> str:
    for path in FONT_PATHS:
        candidate = Path(path)
        if candidate.exists():
            return str(candidate)
    return ""


def _find_attendance_font() -> str:
    for path in ATTENDANCE_FONT_PATHS:
        candidate = Path(path)
        if candidate.exists():
            return str(candidate)
    return ""


def _shape(text, base_dir: str = "R") -> str:
    value = "" if text is None else str(text)
    if arabic_reshaper is None or get_display is None:
        return value
    if any("\u0600" <= char <= "\u06FF" for char in value):
        reshaped = arabic_reshaper.reshape(value)
        try:
            return get_display(reshaped, base_dir=base_dir)
        except TypeError:
            return get_display(reshaped)
    return value


class RawPDF(FPDF):
    def __init__(self):
        super().__init__(orientation="P", unit="mm", format="A4")
        self.set_auto_page_break(auto=True, margin=10)
        self.set_margins(8, 8, 8)
        self.font_path = _find_font()
        self.font_name = "Persian" if self.font_path else "Helvetica"
        self.attendance_font_path = _find_attendance_font()
        self.attendance_font_name = (
            "AttendanceUnicode" if self.attendance_font_path else self.font_name
        )
        if self.font_path:
            self.add_font(self.font_name, "", self.font_path)
            self.add_font(self.font_name, "B", self.font_path)
        if self.attendance_font_path and self.attendance_font_name != self.font_name:
            self.add_font(self.attendance_font_name, "", self.attendance_font_path)
            self.add_font(self.attendance_font_name, "B", self.attendance_font_path)

    def header(self):
        if self.page_no() == 1:
            return
        self.set_font(self.font_name, "", 7.5)
        self.set_text_color(80, 80, 80)
        self.cell(0, 5, _shape("گزارش خام تردد"), align="L")
        self.ln(5)

    def footer(self):
        self.set_y(-10)
        self.set_font(self.font_name, "", 7.5)
        self.set_text_color(100, 100, 100)
        self.cell(0, 5, _shape(f"صفحه {self.page_no()}"), align="C")

    def _header_block(self, title: str, subtitle: str):
        self.set_font(self.font_name, "B", 12)
        self.set_text_color(0, 0, 0)
        self.cell(0, 7, _shape(title), ln=True, align="C")
        if subtitle:
            self.set_font(self.font_name, "", 8.5)
            self.cell(0, 4.5, _shape(subtitle), ln=True, align="C")
        self.ln(1)

    def _employee_header(self, emp: dict):
        self.set_font(self.font_name, "B", 9.5)
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
            self.set_font(self.font_name, "", 8)
            self.cell(0, 4, _shape("    ".join(extra)), ln=True, align="R")
        self.ln(1)

    def _cell_lines(self, text: str, width: float, base_dir: str = "R") -> List[str]:
        value = "" if text is None else str(text)
        raw_lines = value.splitlines() or [""]
        result: List[str] = []
        for raw_line in raw_lines:
            if not raw_line:
                result.append("")
                continue
            if self.get_string_width(
                _shape(raw_line, base_dir=base_dir) if base_dir == "R" else raw_line
            ) <= width:
                result.append(raw_line)
                continue

            parts = raw_line.split(" | ")
            current = ""
            for part in parts:
                candidate = part if not current else f"{current} | {part}"
                shaped_candidate = (
                    _shape(candidate, base_dir=base_dir)
                    if base_dir == "R"
                    else candidate
                )
                if self.get_string_width(shaped_candidate) <= width:
                    current = candidate
                    continue
                if current:
                    result.append(current)
                    current = part
                else:
                    current = part
                if self.get_string_width(
                    _shape(current, base_dir=base_dir) if base_dir == "R" else current
                ) > width:
                    words = current.split(" ")
                    current = ""
                    for word in words:
                        candidate_word = word if not current else f"{current} {word}"
                        shaped_word = (
                            _shape(candidate_word, base_dir=base_dir)
                            if base_dir == "R"
                            else candidate_word
                        )
                        if self.get_string_width(shaped_word) <= width:
                            current = candidate_word
                        else:
                            if current:
                                result.append(current)
                            current = word
                    if current:
                        result.append(current)
                    current = ""
            if current:
                result.append(current)
        return result or [""]

    @staticmethod
    def _format_attendance_segment(segment: dict) -> str:
        kind = segment.get("kind")
        if kind == "pair":
            enter = segment["enter"]
            exit_record = segment["exit"]
            left = fmt_time(enter.get("time"))
            right = fmt_time(exit_record.get("time"))
            if enter.get("is_manual"):
                left += " (M)"
            if exit_record.get("is_manual"):
                right += " (M)"
            return f"{left} → {right}"
        record = segment.get("record", {})
        value = fmt_time(record.get("time"))
        if record.get("is_manual"):
            value += " (M)"
        if kind == "entry_only":
            return f"{value} → —"
        if kind == "exit_only":
            return f"— → {value}"
        return value

    @classmethod
    def _attendance_text_for_pdf(cls, day: dict) -> str:
        segments = day.get("attendance_segments") or []
        if segments:
            return " | ".join(
                cls._format_attendance_segment(segment) for segment in segments
            )
        # Keep tests/legacy datasets compatible while normalizing the old label.
        return str(day.get("attendance_str") or "—").replace("دستی", "(M)")

    @staticmethod
    def _leave_and_mission_text(day: dict) -> str:
        """نوع مرخصی + مأموریت ساعتی (فقط متن — بدون emoji برای سازگاری فونت PDF)."""
        parts = []
        leave_name = day.get("leave_name")
        if leave_name:
            parts.append(str(leave_name))
        hm = day.get("hourly_mission_display") or ""
        if hm:
            parts.append(hm)
        if not parts:
            return "-"
        return "\n".join(parts)

    def _write_cell(self, x: float, y: float, width: float, row_height: float,
                    line_height: float, text, align: str = "C",
                    base_dir: str = "R"):
        style = "B" if getattr(self, "font_style", "") == "B" else ""
        self.set_font(
            self.attendance_font_name if base_dir == "L" else self.font_name,
            style,
            self.font_size_pt,
        )
        lines = self._cell_lines(text, width, base_dir=base_dir)
        self.rect(x, y, width, row_height)
        content_height = len(lines) * line_height
        top_padding = max(0.0, (row_height - content_height) / 2)
        for line_index, line in enumerate(lines):
            self.set_xy(x, y + top_padding + line_index * line_height)
            rendered = _shape(line, base_dir=base_dir) if base_dir == "R" else line
            self.cell(
                width,
                line_height,
                rendered,
                border=0,
                align=align,
                new_x="LEFT",
                new_y="NEXT",
            )

    def _table_header(self, widths: List[float], line_height: float):
        # Physical RTL order: the first column is on the RIGHT,
        # and each following column moves toward the LEFT.
        headers = [
            "تاریخ",
            "روز",
            "وضعیت روز",
            "وضعیت فرد",
            "نوع مرخصی",
            "ترددها (ورود → خروج)",
        ]
        x = self.w - self.r_margin
        y = self.get_y()
        self.set_font(self.font_name, "B", 8)
        for index, width in enumerate(widths):
            x -= width
            header_height = line_height if index in (4, 5) else line_height
            align = "R" if index in (0, 1, 2, 3, 4) else "C"
            base_dir = "R"
            self._write_cell(
                x, y, width, header_height, line_height,
                headers[index], align, base_dir=base_dir
            )
        self.set_xy(self.l_margin, y + line_height)

    def _daily_table(self, days: list):
        widths = [17, 15, 15, 19, 32, 96]
        line_height = 4.8
        bottom_limit = self.h - self.b_margin - 5
        self._table_header(widths, line_height)
        self.set_font(self.font_name, "", 7.8)
        for day in days:
            leave_display = self._leave_and_mission_text(day)
            values = [
                day["jalali_date"],
                day["day_name"],
                day["day_status"],
                day["person_status_name"],
                leave_display,
                self._attendance_text_for_pdf(day),
            ]
            max_lines = 1
            for index, (width, value) in enumerate(zip(widths, values)):
                base_dir = "L" if index == 5 else "R"
                max_lines = max(
                    max_lines,
                    len(self._cell_lines(value, width, base_dir=base_dir)),
                )
            row_height = max(line_height, max_lines * line_height + 0.6)
            if self.get_y() + row_height > bottom_limit:
                self.add_page()
                self._table_header(widths, line_height)
                self.set_font(self.font_name, "", 7.8)
            y = self.get_y()
            x = self.w - self.r_margin
            for index, (width, value) in enumerate(zip(widths, values)):
                x -= width
                self._write_cell(
                    x, y, width, row_height, line_height, value,
                    "L" if index == 5 else "C",
                    base_dir="L" if index == 5 else "R",
                )
            self.set_xy(self.l_margin, y + row_height)
        self.ln(1)
        self.set_font(self.font_name, "", 7)
        self.cell(
            0,
            4.2,
            _shape(
                "راهنمای گزارش: (M) یعنی تردد دستی؛ نبودن (M) یعنی ثبت توسط دستگاه. در هر روز، زمان‌ها به ترتیب ورود و سپس خروج نمایش داده می‌شوند."
            ),
            border=0,
            align="R",
            new_x="LMARGIN",
            new_y="NEXT",
        )


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
