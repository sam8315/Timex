"""خروجی PDF فیش حقوقی — همیشه در یک صفحهٔ A4."""
from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any, List, Optional

from fpdf import FPDF

from core.payroll.payslip_present import fa_digits, line_detail, money_text, payslip_sort_key

try:
    import arabic_reshaper
    from bidi.algorithm import get_display

    RTL_SUPPORT = True
except ImportError:
    RTL_SUPPORT = False

SHAPING_SUPPORT = importlib.util.find_spec("uharfbuzz") is not None

FONT_DIR = Path(__file__).resolve().parents[2] / "web" / "static" / "fonts"
FONT_CANDIDATES = (
    (FONT_DIR / "Vazirmatn-Regular.ttf", FONT_DIR / "Vazirmatn-Bold.ttf"),
    (Path("C:/Windows/Fonts/tahoma.ttf"), Path("C:/Windows/Fonts/tahomabd.ttf")),
    (
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
    ),
)

PAGE_W = 210.0
PAGE_H = 297.0
FRAME = 8.0
MARGIN = 13.0
MIN_SCALE = 0.6

TEXT_RGB = (33, 37, 41)
MUTED_RGB = (73, 80, 87)
BORDER_RGB = (180, 196, 214)
FRAME_RGB = (31, 78, 121)
EARN_RGB = (20, 108, 67)
DED_RGB = (176, 42, 55)


def find_font_files() -> Optional[tuple[str, str]]:
    for regular, bold in FONT_CANDIDATES:
        if regular.exists():
            return str(regular), str(bold if bold.exists() else regular)
    return None


class PayslipPDF(FPDF):
    def __init__(self, orientation: str = "P"):
        super().__init__(orientation=orientation, unit="mm", format="A4")
        self.shaping = False
        fonts = find_font_files()
        if fonts:
            regular, bold = fonts
            self.font_path = regular
            self.add_font("PayFont", "", regular)
            self.add_font("PayFont", "B", bold)
            self.font_family_name = "PayFont"
            if SHAPING_SUPPORT:
                self.set_text_shaping(
                    use_shaping_engine=True, direction="rtl", script="arab", language="fas",
                )
                self.shaping = True
        else:
            self.font_path = ""
            self.font_family_name = "Helvetica"

    def _rtl(self, text: str) -> str:
        text = str(text or "")
        if self.shaping or not RTL_SUPPORT:
            return text
        try:
            return get_display(arabic_reshaper.reshape(text))
        except Exception:
            return text

    def cell_rtl(self, w, h, text, border=0, ln=0, align="R", fill=False):
        self.cell(w, h, self._rtl(text), border=border, ln=ln, align=align, fill=fill)


class _Painter:
    """اندازه‌ها با scale ضرب می‌شوند؛ با draw=False فقط ارتفاع محاسبه می‌شود."""

    def __init__(self, pdf: PayslipPDF, scale: float, draw: bool):
        self.pdf = pdf
        self.scale = scale
        self.draw = draw

    def font(self, size: float, bold: bool = False) -> None:
        self.pdf.set_font(self.pdf.font_family_name, "B" if bold else "", size * self.scale)

    def box(self, x: float, y: float, w: float, h: float, fill=None) -> None:
        if not self.draw:
            return
        self.pdf.set_line_width(0.2)
        self.pdf.set_draw_color(*BORDER_RGB)
        if fill:
            self.pdf.set_fill_color(*fill)
        self.pdf.rect(x, y, w, h, style="DF" if fill else "D")

    def text(self, x: float, y: float, w: float, h: float, text: str, align: str = "R", color=TEXT_RGB) -> None:
        if not self.draw:
            return
        self.pdf.set_text_color(*color)
        self.pdf.set_xy(x, y)
        self.pdf.cell_rtl(w, h, text, align=align)

    def wrap(self, text: str, width: float) -> List[str]:
        limit = width - 2 * self.pdf.c_margin
        lines: List[str] = []
        current = ""
        for word in str(text or "").split():
            trial = f"{current} {word}".strip()
            if current and self.pdf.get_string_width(self.pdf._rtl(trial)) > limit:
                lines.append(current)
                current = word
            else:
                current = trial
        if current:
            lines.append(current)
        return lines


def _profile_rows(result: Any, profile: dict | None, period_label: str) -> list[tuple[str, str]]:
    if profile:
        covered = f"{profile.get('covered_days') or '—'} از {profile.get('month_days') or '—'} روز"
        worked = profile.get("work_days") or profile.get("covered_days") or "—"
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
            ("کارکرد", f"{worked} از {profile.get('month_days') or '—'} روز"),
            ("دوره", fa_digits(period_label)),
            ("جنسیت", str(profile.get("gender") or "—")),
        ]
    return [
        ("نام", str(result.employee_name or "—")),
        ("کد پرسنلی", fa_digits(result.user_id)),
        ("عضویت", str(result.membership_type_code or "—")),
        ("پوشش قرارداد", f"{money_text(result.covered_days)} از {money_text(result.month_days)} روز"),
        ("کارکرد", f"{money_text(_work_days(result))} از {money_text(result.month_days)} روز"),
    ]


def _work_days(result: Any) -> int:
    work_days = getattr(result, "work_days", None)
    return int(result.covered_days or 0) if work_days is None else int(work_days)


def _draw_profile(p: _Painter, x: float, y: float, width: float, rows: list[tuple[str, str]]) -> float:
    s = p.scale
    head_h = 7 * s
    p.box(x, y, width, head_h, fill=(232, 238, 245))
    p.font(10, True)
    p.text(x, y, width, head_h, "مشخصات فردی", "C", FRAME_RGB)
    y += head_h
    col_w = width / 2
    row_h = 6 * s
    p.font(8.5)
    for index in range(0, len(rows), 2):
        pair = rows[index:index + 2]
        for col in range(2):
            cx = x + width - (col + 1) * col_w
            p.box(cx, y, col_w, row_h, fill=(247, 250, 252))
            if col < len(pair):
                label, value = pair[col]
                p.text(cx, y, col_w, row_h, f"{label}: {value}")
        y += row_h
    return y


def _draw_side(p: _Painter, x: float, y: float, width: float, title: str, rows: List[Any],
               header_rgb, title_rgb, body_rgb) -> float:
    s = p.scale
    head_h = 8 * s
    p.box(x, y, width, head_h, fill=header_rgb)
    p.font(11, True)
    p.text(x, y, width, head_h, title, "C", title_rgb)
    y += head_h
    if not rows:
        p.box(x, y, width, 8 * s, fill=body_rgb)
        p.font(9)
        p.text(x, y, width, 8 * s, "موردی نیست", "C", MUTED_RGB)
        return y + 8 * s
    amount_w = 30 * s
    name_h = 6 * s
    line_h = 4.4 * s
    for item in rows:
        p.font(8)
        lines = p.wrap(line_detail(item), width)
        row_h = name_h + len(lines) * line_h + (1 * s if lines else 0)
        p.box(x, y, width, row_h, fill=body_rgb)
        p.font(9, True)
        p.text(x + amount_w, y, width - amount_w, name_h, item.component_name, "R")
        p.text(x, y, amount_w, name_h, money_text(item.amount), "L")
        p.font(8)
        for index, line in enumerate(lines):
            p.text(x, y + name_h + index * line_h, width, line_h, line, "R", MUTED_RGB)
        y += row_h
    return y


def _layout(pdf: PayslipPDF, result: Any, items: List[Any], period_label: str,
            profile: dict | None, *, scale: float, draw: bool) -> float:
    """پایین‌ترین y محتوا را برمی‌گرداند."""
    p = _Painter(pdf, scale, draw)
    s = scale
    x = MARGIN
    width = PAGE_W - 2 * MARGIN
    y = MARGIN

    p.font(14, True)
    p.text(x, y, width, 9 * s, "فیش حقوقی", "C", FRAME_RGB)
    y += 9 * s
    p.font(11)
    p.text(x, y, width, 7 * s, f"دوره {fa_digits(period_label)}", "C", MUTED_RGB)
    y += 8 * s
    y = _draw_profile(p, x, y, width, _profile_rows(result, profile, period_label)) + 4 * s

    ordered = sorted(items, key=payslip_sort_key)
    earnings = [row for row in ordered if row.kind != "deduction"]
    deductions = [row for row in ordered if row.kind == "deduction"]
    gap = 4
    col_w = (width - gap) / 2
    earn_bottom = _draw_side(
        p, x + col_w + gap, y, col_w, "درآمدها", earnings,
        (214, 240, 223), EARN_RGB, (244, 251, 246),
    )
    ded_bottom = _draw_side(
        p, x, y, col_w, "کسورات", deductions,
        (248, 222, 222), DED_RGB, (253, 246, 246),
    )
    y = max(earn_bottom, ded_bottom) + 4 * s

    half = width / 2
    total_h = 9 * s
    p.font(11, True)
    p.box(x + half, y, half, total_h, fill=(229, 246, 234))
    p.text(x + half, y, half, total_h, f"جمع درآمد: {money_text(result.gross_earnings)}", "C", EARN_RGB)
    p.box(x, y, half, total_h, fill=(251, 234, 234))
    p.text(x, y, half, total_h, f"جمع کسورات: {money_text(result.total_deductions)}", "C", DED_RGB)
    y += total_h
    net_h = 10 * s
    p.font(12, True)
    p.box(x, y, width, net_h, fill=(244, 247, 251))
    p.text(x, y, width, net_h, f"خالص پرداختی: {money_text(result.net_pay)}", "C", FRAME_RGB)
    return y + net_h


def _fit_scale(pdf: PayslipPDF, args: tuple) -> float:
    limit = PAGE_H - MARGIN
    scale = 1.0
    while scale > MIN_SCALE:
        bottom = _layout(pdf, *args, scale=scale, draw=False)
        if bottom <= limit:
            return scale
        ratio = (limit - MARGIN) / (bottom - MARGIN)
        scale = max(MIN_SCALE, min(scale - 0.02, scale * ratio))
    return MIN_SCALE


def render_payslip_pdf(result: Any, items: List[Any], period_label: str,
                       profile: dict | None = None) -> PayslipPDF:
    pdf = PayslipPDF()
    pdf.set_auto_page_break(auto=False)
    pdf.set_margins(MARGIN, MARGIN, MARGIN)
    args = (result, items, period_label, profile)
    scale = _fit_scale(pdf, args)
    pdf.add_page()
    bottom = _layout(pdf, *args, scale=scale, draw=True)
    frame_bottom = min(PAGE_H - FRAME, bottom + (MARGIN - FRAME))
    pdf.set_draw_color(*FRAME_RGB)
    pdf.set_line_width(0.6)
    pdf.rect(FRAME, FRAME, PAGE_W - 2 * FRAME, frame_bottom - FRAME)
    pdf.scale_used = scale
    return pdf


def build_payslip_pdf(result: Any, items: List[Any], period_label: str, profile: dict | None = None) -> bytes:
    out = render_payslip_pdf(result, items, period_label, profile).output()
    if isinstance(out, (bytes, bytearray)):
        return bytes(out)
    return out.encode("latin-1")
