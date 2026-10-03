"""
خروجی PDF گزارش تفصیلی ماهانه - نسخه ۲

هر کارمند دقیقاً در *یک* صفحه A4 جا می‌شود (چاپ مرورگر و PDF).
خروجی گروهی: یک صفحه به ازای هر کارمند.
"""
from typing import Dict, List, Optional
from pathlib import Path
from fpdf import FPDF, XPos, YPos
import os

try:
    import arabic_reshaper
    from bidi.algorithm import get_display

    RTL_SUPPORT = True
except ImportError:
    RTL_SUPPORT = False


class DetailedPDFExporterV2:
    """خروجی PDF گزارش تفصیلی - نسخه ۲ (یک صفحه به ازای هر نفر)"""

    def __init__(self, output_dir: str = "exports"):
        self.output_dir = Path(output_dir)
        self.font_path = self._find_persian_font()

    def _resolve_output_file(self, filename: str) -> str:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        return str(self.output_dir / filename)

    def _find_persian_font(self) -> str:
        for path in (
            "C:/Windows/Fonts/tahoma.ttf",
            "C:/Windows/Fonts/arial.ttf",
            "C:/Windows/Fonts/segoeui.ttf",
        ):
            if os.path.exists(path):
                return path
        return "C:/Windows/Fonts/tahoma.ttf"

    def _fix_rtl(self, text: str) -> str:
        if RTL_SUPPORT and any('\u0600' <= c <= '\u06FF' for c in str(text)):
            return get_display(arabic_reshaper.reshape(str(text)))
        return str(text)

    def _fmt_hours(self, h: float) -> str:
        """فرمت ساعات اعشاری به HH:MM با دقت دقیقه."""
        if h is None:
            return '00:00'
        total_minutes = int(round(float(h) * 60))
        if total_minutes == 0:
            return '-'
        sign = '-' if total_minutes < 0 else ''
        total_minutes = abs(total_minutes)
        hours = total_minutes // 60
        minutes = total_minutes % 60
        return f"{sign}{hours:02d}:{minutes:02d}"

    def _setup_font(self, pdf: FPDF) -> str:
        if os.path.exists(self.font_path):
            pdf.add_font('Persian', '', self.font_path)
            pdf.add_font('Persian', 'B', self.font_path)
            return 'Persian'
        return 'Helvetica'

    @staticmethod
    def _fmt_time(dt) -> str:
        return dt.strftime('%H:%M') if dt else '-'

    def _ln(self, pdf: FPDF, w, h, text, align='C'):
        pdf.cell(
            w, h, text,
            new_x=XPos.LMARGIN, new_y=YPos.NEXT, align=align,
        )
    def _new_pdf(self) -> tuple:
        pdf = FPDF(orientation='P', unit='mm', format='A4')
        # حاشیه کم برای جا شدن جدول + خلاصه در یک صفحه
        pdf.set_margins(8, 8, 8)
        pdf.set_auto_page_break(auto=False)
        font_name = self._setup_font(pdf)
        return pdf, font_name

    def _write_output(self, pdf: FPDF, output, default_filename: str):
        if output is None:
            path = self._resolve_output_file(default_filename)
            pdf.output(path)
            return path
        pdf.output(output)
        if hasattr(output, 'seek'):
            output.seek(0)
        return output

    def export_detailed_report(self, report: Dict, output=None):
        """خروجی یک کارمند — دقیقاً یک صفحه A4."""
        pdf, font_name = self._new_pdf()
        pdf.add_page()
        self._render_employee_page(pdf, report, font_name)

        emp = report['employee']
        filename = (
            f"گزارش_تفصیلی_V2_{emp['full_name']}_"
            f"{report['month_name']}_{report['year']}.pdf"
        )
        return self._write_output(pdf, output, filename)

    def export_group_reports(
        self,
        reports: List[Dict],
        year: int,
        month: int,
        month_name: str,
        group_label: str = 'گروه',
        output=None,
    ):
        """خروجی گروهی — هر کارمند یک صفحه کامل."""
        pdf, font_name = self._new_pdf()
        if not reports:
            pdf.add_page()
            pdf.set_font(font_name, 'B', 14)
            pdf.cell(
                0, 10,
                self._fix_rtl(f"گزارشی برای «{group_label}» یافت نشد"),
                new_x='LMARGIN', new_y='NEXT', align='C',
            )
        else:
            for report in reports:
                pdf.add_page()
                self._render_employee_page(pdf, report, font_name)

        filename = f"گزارش_گروهی_V2_{group_label}_{month_name}_{year}.pdf"
        return self._write_output(pdf, output, filename)

    # سازگاری با نام قبلی
    def export_all_employees_report(
        self,
        reports: List[Dict],
        year: int,
        month: int,
        month_name: str,
        output=None,
    ):
        return self.export_group_reports(
            reports, year, month, month_name,
            group_label='همه', output=output,
        )

    def _render_employee_page(self, pdf: FPDF, report: Dict, font_name: str):
        """رسم کل گزارش یک نفر در صفحهٔ جاری (بدون page-break)."""
        emp = report['employee']
        summary = report['summary']
        days = report.get('days') or []

        # ---- هدر فشرده ----
        pdf.set_font(font_name, 'B', 11)
        pdf.cell(
            0, 6,
            self._fix_rtl(f"گزارش تفصیلی — {emp['full_name']}"),
            new_x='LMARGIN', new_y='NEXT', align='C',
        )
        pdf.set_font(font_name, '', 8)
        pdf.cell(
            0, 4,
            self._fix_rtl(
                f"کد: {emp['user_id']} | عضویت: "
                f"{emp.get('department_name') or emp.get('department') or '-'} | "
                f"{report['month_name']} {report['year']}"
            ),
            new_x='LMARGIN', new_y='NEXT', align='C',
        )
        pdf.ln(1)

        # ---- جدول روزانه ----
        headers = [
            'تاریخ', 'روز', 'وضعیت روز', 'وضعیت فرد',
            'و۱', 'خ۱', 'و۲', 'خ۲', 'و۳', 'خ۳',
            'وضعیت تردد', 'کارکرد', 'تأخیر', 'تعجیل', 'اضافی', 'کسری',
        ]
        col_widths = [14, 10, 10, 14, 9, 9, 9, 9, 9, 9, 14, 10, 10, 10, 10, 10]
        page_width = pdf.w - pdf.l_margin - pdf.r_margin
        table_width = sum(col_widths)
        # اگر جدول پهن‌تر از صفحه بود، مقیاس افقی
        scale = min(1.0, page_width / table_width)
        col_widths = [w * scale for w in col_widths]
        table_width = sum(col_widths)
        start_x = pdf.l_margin + (page_width - table_width)

        row_h = 3.6 if len(days) <= 31 else 3.2
        header_h = 4.2

        pdf.set_font(font_name, 'B', 5.5)
        self._draw_row(pdf, start_x, table_width, col_widths, headers, header_h, bold_rtl=True)

        pdf.set_font(font_name, '', 5)
        for day in days:
            pairs = day.get('attendance_pairs') or []
            enter1 = self._fmt_time(pairs[0]['enter']) if len(pairs) > 0 else '-'
            exit1 = self._fmt_time(pairs[0]['exit']) if len(pairs) > 0 else '-'
            enter2 = self._fmt_time(pairs[1]['enter']) if len(pairs) > 1 else '-'
            exit2 = self._fmt_time(pairs[1]['exit']) if len(pairs) > 1 else '-'
            enter3 = self._fmt_time(pairs[2]['enter']) if len(pairs) > 2 else '-'
            exit3 = self._fmt_time(pairs[2]['exit']) if len(pairs) > 2 else '-'

            attendance_str = day.get('attendance_status') or '-'
            if attendance_str == 'بدون تردد':
                attendance_str = '-'

            late_v = day.get('late_violation_minutes') or 0
            early_v = day.get('early_leave_violation_minutes') or 0
            values = [
                day.get('jalali_date', ''),
                (day.get('day_name') or '')[:6],
                (day.get('day_status') or '')[:6],
                (day.get('person_status_name') or '')[:10],
                enter1, exit1, enter2, exit2, enter3, exit3,
                attendance_str[:12],
                self._fmt_hours(day.get('work_hours') or 0),
                self._fmt_hours(late_v / 60.0) if late_v else '-',
                self._fmt_hours(early_v / 60.0) if early_v else '-',
                self._fmt_hours(day.get('surplus') or 0),
                self._fmt_hours(day.get('deficit') or 0),
            ]
            # ستون‌های عددی/زمان بدون reshape
            ltr_cols = {0, 4, 5, 6, 7, 8, 9, 11, 12, 13, 14, 15}
            self._draw_row(
                pdf, start_x, table_width, col_widths, values, row_h,
                ltr_cols=ltr_cols,
            )

        pdf.ln(2)

        # ---- خلاصه فشرده ----
        pdf.set_font(font_name, 'B', 8)
        pdf.cell(
            0, 4, self._fix_rtl('خلاصه ماهانه'),
            new_x='LMARGIN', new_y='NEXT', align='R',
        )
        pdf.set_font(font_name, '', 7)
        lines = [
            f"موظفی: {summary['duty_days']} روز / {self._fmt_hours(summary['duty_hours'])} | "
            f"حضور: {summary['present_days']} | مرخصی: {summary['leave_days']} | "
            f"مأموریت: {summary['mission_days']} | غیبت: {summary['absent_days']} | "
            f"استراحت: {summary['rest_days']} | تعطیل: {summary['holiday_days']}",
            f"کارکرد: {self._fmt_hours(summary['total_work_hours'])} | "
            f"صبح: {self._fmt_hours(summary['total_morning'])} | "
            f"عصر: {self._fmt_hours(summary['total_evening'])} | "
            f"شب: {self._fmt_hours(summary['total_night'])}",
            f"اضافی: {self._fmt_hours(summary['total_surplus'])} | "
            f"کسری: {self._fmt_hours(summary['total_deficit'])} | "
            f"تأخیر: {self._fmt_hours(summary.get('total_late_violation') or 0)} | "
            f"تعجیل: {self._fmt_hours(summary.get('total_early_leave_violation') or 0)} | "
            f"هفتگی: {self._fmt_hours(summary['weekly_overtime'])} | "
            f"جمعه‌کاری: {self._fmt_hours(summary['friday_work_hours'])} | "
            f"تعطیل‌کاری: {self._fmt_hours(summary['holiday_work_hours'])}",
            f"وضعیت کلی: {summary['overall_status']} | "
            f"خالص: {self._fmt_hours(summary['net_balance'])}",
        ]
        for line in lines:
            pdf.cell(
                0, 3.8, self._fix_rtl(line),
                new_x='LMARGIN', new_y='NEXT', align='R',
            )

    def _draw_row(
        self,
        pdf: FPDF,
        start_x: float,
        table_width: float,
        col_widths: List[float],
        values: List[str],
        height: float,
        bold_rtl: bool = False,
        ltr_cols: Optional[set] = None,
    ):
        ltr_cols = ltr_cols or set()
        y = pdf.get_y()
        current_x = start_x + table_width
        for i, value in enumerate(values):
            current_x -= col_widths[i]
            pdf.set_xy(current_x, y)
            text = str(value)
            if i not in ltr_cols:
                text = self._fix_rtl(text)
            elif bold_rtl:
                text = self._fix_rtl(text)
            pdf.cell(col_widths[i], height, text, border=1, align='C')
        pdf.set_y(y + height)
