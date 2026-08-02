"""
خروجی PDF گزارش مرخصی‌ها
"""
from datetime import date
from typing import Dict, List
from pathlib import Path
from fpdf import FPDF
import jdatetime
import os

try:
    import arabic_reshaper
    from bidi.algorithm import get_display
    RTL_SUPPORT = True
except ImportError:
    RTL_SUPPORT = False


class PDFLeaveExporter:
    """خروجی PDF گزارش مرخصی‌ها"""

    def __init__(self, output_dir: str = "exports"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(exist_ok=True)
        self.font_path = self._find_persian_font()

    def _find_persian_font(self) -> str:
        """پیدا کردن فونت فارسی"""
        font_paths = [
            "C:/Windows/Fonts/tahoma.ttf",
            "C:/Windows/Fonts/arial.ttf",
        ]

        for path in font_paths:
            if os.path.exists(path):
                return path

        return "C:/Windows/Fonts/tahoma.ttf"

    def _fix_rtl(self, text: str) -> str:
        """اصلاح متن فارسی"""
        if RTL_SUPPORT and any('\u0600' <= c <= '\u06FF' for c in text):
            reshaped_text = arabic_reshaper.reshape(text)
            bidi_text = get_display(reshaped_text)
            return bidi_text
        return text

    def export_leave_report(self, reports: List[Dict], year: int, month: int, period: str, dept_names: Dict) -> str:
        """خروجی گزارش مرخصی‌ها به PDF"""
        pdf = FPDF(orientation='L')  # Landscape برای جدول عریض
        pdf.add_page()

        font_name = self._setup_font(pdf)

        # عنوان
        pdf.set_font(font_name, 'B', 14)
        pdf.cell(0, 8, self._fix_rtl(f"گزارش مرخصی‌ها - {period}"), ln=True, align='C')
        pdf.set_font(font_name, '', 10)
        pdf.cell(0, 6, self._fix_rtl(f"تعداد کاربران: {len(reports)}"), ln=True, align='C')
        pdf.ln(3)

        # گروه‌بندی بر اساس دپارتمان
        by_department = {}
        for r in reports:
            dept = r['department']
            if dept not in by_department:
                by_department[dept] = []
            by_department[dept].append(r)

        for dept, dept_reports in sorted(by_department.items()):
            dept_name = dept_names.get(str(dept), f'گروه {dept}')

            pdf.set_font(font_name, 'B', 11)
            pdf.cell(0, 6, self._fix_rtl(f"دپارتمان: {dept_name} ({len(dept_reports)} کاربر)"), ln=True)
            pdf.ln(1)

            # ✅ هدر دو سطری
            pdf.set_font(font_name, 'B', 6)

            # سطر اول: گروه‌ها
            headers_row1 = ['', '', '', 'AL', '', '', 'SL', '', '', 'RL', '', '', 'UL', '', '', 'CW', '', '', 'TOT', '', '']
            col_widths = [6, 10, 28, 10, 10, 10, 10, 10, 10, 10, 10, 10, 10, 10, 10, 10, 10, 10, 12, 12, 12]

            page_width = pdf.w - 2 * pdf.l_margin
            table_width = sum(col_widths)
            start_x = pdf.l_margin

            # سطر اول هدر
            current_x = start_x
            for i, header in enumerate(headers_row1):
                pdf.set_xy(current_x, pdf.get_y())
                pdf.cell(col_widths[i], 4, self._fix_rtl(header), border=1, align='C')
                current_x += col_widths[i]
            pdf.ln()

            # سطر دوم: زیرستون‌ها
            headers_row2 = ['#', 'Code', 'Name', 'T', 'U', 'B', 'T', 'U', 'B', 'T', 'U', 'B', 'T', 'U', 'B', 'T', 'U', 'B', 'T', 'U', 'B']
            current_x = start_x
            for i, header in enumerate(headers_row2):
                pdf.set_xy(current_x, pdf.get_y())
                pdf.cell(col_widths[i], 4, self._fix_rtl(header), border=1, align='C')
                current_x += col_widths[i]
            pdf.ln()

            # ✅ داده‌ها
            pdf.set_font(font_name, '', 6)
            for i, r in enumerate(dept_reports, 1):
                values = [
                    str(i),
                    r['user_id'],
                    r['full_name'][:14],
                    str(r['al_total']), str(r['al_used']), str(r['al_balance']),
                    str(r['sl_total']), str(r['sl_used']), str(r['sl_balance']),
                    str(r['rl_total']), str(r['rl_used']), str(r['rl_balance']),
                    str(r['ul_total']), str(r['ul_used']), str(r['ul_balance']),
                    str(r['cw_total']), str(r['cw_used']), str(r['cw_balance']),
                    str(r['tot_total']), str(r['tot_used']), str(r['tot_balance']),
                ]

                current_x = start_x
                for j, value in enumerate(values):
                    pdf.set_xy(current_x, pdf.get_y())
                    pdf.cell(col_widths[j], 4, self._fix_rtl(value), border=1, align='C')
                    current_x += col_widths[j]
                pdf.ln()

            pdf.ln(3)

        # ✅ راهنما در انتها
        pdf.set_font(font_name, 'B', 8)
        pdf.cell(0, 5, self._fix_rtl("راهنما:"), ln=True)
        pdf.set_font(font_name, '', 7)
        pdf.cell(0, 4, self._fix_rtl("AL=Annual Leave (استحقاقی) | SL=Sick Leave (استعلاجی) | RL=Reward Leave (تشویقی) | UL=Unpaid Leave (بدون حقوق) | CW=Carryover (ذخیره) | TOT=Total"), ln=True)
        pdf.cell(0, 4, self._fix_rtl("T=Total (کل) | U=Used (استفاده شده) | B=Balance (مانده)"), ln=True)

        # ذخیره
        filename = self.output_dir / f"leave_report_{period.replace(' ', '_')}.pdf"
        pdf.output(str(filename))
        return str(filename)

    def _setup_font(self, pdf: FPDF) -> str:
        """تنظیم فونت فارسی"""
        if os.path.exists(self.font_path):
            pdf.add_font('Persian', '', self.font_path, uni=True)
            pdf.add_font('Persian', 'B', self.font_path, uni=True)
            return 'Persian'
        return 'Helvetica'