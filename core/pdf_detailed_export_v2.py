"""
خروجی PDF گزارش تفصیلی ماهانه - نسخه ۲
با ستون‌های متعدد ورود/خروج
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


class DetailedPDFExporterV2:
    """خروجی PDF گزارش تفصیلی - نسخه ۲"""

    def __init__(self, output_dir: str = "exports"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(exist_ok=True)
        self.font_path = self._find_persian_font()

    def _find_persian_font(self) -> str:
        """پیدا کردن فونت فارسی"""
        font_paths = [
            "C:/Windows/Fonts/tahoma.ttf",
            "C:/Windows/Fonts/arial.ttf",
            "C:/Windows/Fonts/segoeui.ttf",
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

    def _fmt_hours(self, h: float) -> str:
        """فرمت ساعات"""
        if h == 0:
            return '00:00'
        hours = int(h)
        minutes = int((h - hours) * 60)
        return f"{hours:02d}:{minutes:02d}"

    def _setup_font(self, pdf: FPDF) -> str:
        """تنظیم فونت فارسی"""
        if os.path.exists(self.font_path):
            pdf.add_font('Persian', '', self.font_path, uni=True)
            pdf.add_font('Persian', 'B', self.font_path, uni=True)
            return 'Persian'
        return 'Helvetica'

    def export_detailed_report(self, report: Dict) -> str:
        """خروجی گزارش تفصیلی یک کارمند به PDF"""
        pdf = FPDF()
        pdf.add_page()

        font_name = self._setup_font(pdf)
        emp = report['employee']
        summary = report['summary']

        pdf.set_font(font_name, 'B', 16)
        pdf.cell(0, 10, self._fix_rtl(f"گزارش تفصیلی V2 - {emp['full_name']}"), ln=True, align='C')
        pdf.set_font(font_name, '', 12)
        pdf.cell(0, 8, self._fix_rtl(f"کد: {emp['user_id']} | دپارتمان: {emp['department']}"), ln=True, align='C')
        pdf.cell(0, 8, self._fix_rtl(f"ماه: {report['month_name']} {report['year']}"), ln=True, align='C')
        pdf.ln(5)

        # جدول روزانه با ستون‌های متعدد
        pdf.set_font(font_name, 'B', 9)
        pdf.cell(0, 7, self._fix_rtl('گزارش روزانه'), ln=True, align='R')
        pdf.ln(2)

        pdf.set_font(font_name, 'B', 6)
        headers = ['تاریخ', 'روز', 'وضعیت روز', 'وضعیت فرد', 'و۱', 'خ۱', 'و۲', 'خ۲', 'و۳', 'خ۳', 'وضعیت تردد', 'کارکرد',
                   'اضافی', 'کسری']
        col_widths = [18, 15, 13, 18, 11, 11, 11, 11, 11, 11, 16, 11, 11, 11]

        page_width = pdf.w - 2 * pdf.l_margin
        table_width = sum(col_widths)
        start_x = pdf.l_margin + (page_width - table_width)

        current_x = start_x + table_width
        for i, header in enumerate(headers):
            current_x -= col_widths[i]
            pdf.set_xy(current_x, pdf.get_y())
            pdf.cell(col_widths[i], 5, self._fix_rtl(header), border=1, align='C')
        pdf.ln()

        pdf.set_font(font_name, '', 5)
        for day in report['days']:
            def fmt_time(dt):
                return dt.strftime('%H:%M') if dt else '-'

            def fmt_hours(h):
                if h == 0:
                    return '-'
                hours = int(h)
                minutes = int((h - hours) * 60)
                return f"{hours:02d}:{minutes:02d}"

            pairs = day.get('attendance_pairs', [])
            enter1 = fmt_time(pairs[0]['enter']) if len(pairs) > 0 else '-'
            exit1 = fmt_time(pairs[0]['exit']) if len(pairs) > 0 else '-'
            enter2 = fmt_time(pairs[1]['enter']) if len(pairs) > 1 else '-'
            exit2 = fmt_time(pairs[1]['exit']) if len(pairs) > 1 else '-'
            enter3 = fmt_time(pairs[2]['enter']) if len(pairs) > 2 else '-'
            exit3 = fmt_time(pairs[2]['exit']) if len(pairs) > 2 else '-'

            attendance_str = day['attendance_status']
            if attendance_str == 'بدون تردد':
                attendance_str = '-'

            values = [
                day['jalali_date'],
                day['day_name'][:6],
                day['day_status'][:6],
                day['person_status_name'][:10],
                enter1, exit1,
                enter2, exit2,
                enter3, exit3,
                attendance_str[:10],
                fmt_hours(day['work_hours']),
                fmt_hours(day['surplus']),
                fmt_hours(day['deficit'])
            ]

            if pdf.get_y() > pdf.h - 20:
                pdf.add_page()
                pdf.set_font(font_name, 'B', 6)
                current_x = start_x + table_width
                for i, header in enumerate(headers):
                    current_x -= col_widths[i]
                    pdf.set_xy(current_x, pdf.get_y())
                    pdf.cell(col_widths[i], 5, self._fix_rtl(header), border=1, align='C')
                pdf.ln()
                pdf.set_font(font_name, '', 5)

            current_x = start_x + table_width
            for i, value in enumerate(values):
                current_x -= col_widths[i]
                pdf.set_xy(current_x, pdf.get_y())
                if i in [0, 4, 5, 6, 7, 8, 9, 11, 12, 13]:
                    pdf.cell(col_widths[i], 4, value, border=1, align='C')
                else:
                    pdf.cell(col_widths[i], 4, self._fix_rtl(value), border=1, align='C')
            pdf.ln()

        pdf.ln(4)

        # خلاصه
        pdf.set_font(font_name, 'B', 11)
        pdf.cell(0, 7, self._fix_rtl('خلاصه ماهانه'), ln=True, align='R')
        pdf.ln(2)

        pdf.set_font(font_name, '', 9)
        pdf.cell(0, 5,
                 self._fix_rtl(f"موظفی: {summary['duty_days']} روز / {self._fmt_hours(summary['duty_hours'])} ساعت"),
                 ln=True, align='R')
        pdf.cell(0, 5, self._fix_rtl(
            f"حضور: {summary['present_days']} | مرخصی: {summary['leave_days']} | غیبت: {summary['absent_days']} | استراحت: {summary['rest_days']} | تعطیل: {summary['holiday_days']}"),
                 ln=True, align='R')
        pdf.cell(0, 5, self._fix_rtl(
            f"کارکرد: {self._fmt_hours(summary['total_work_hours'])} | صبح: {self._fmt_hours(summary['total_morning'])} | عصر: {self._fmt_hours(summary['total_evening'])} | شب: {self._fmt_hours(summary['total_night'])}"),
                 ln=True, align='R')
        pdf.cell(0, 5, self._fix_rtl(
            f"اضافی (7:20): {self._fmt_hours(summary['total_surplus'])} | کسری (7:20): {self._fmt_hours(summary['total_deficit'])} | هفتگی: {self._fmt_hours(summary['weekly_overtime'])} | جمعه کاری: {self._fmt_hours(summary['friday_work_hours'])}"),
                 ln=True, align='R')

        filename = self.output_dir / f"گزارش_تفصیلی_V2_{emp['full_name']}_{report['month_name']}_{report['year']}.pdf"
        pdf.output(str(filename))
        return str(filename)

    def export_all_employees_report(self, reports: List[Dict], year: int, month: int, month_name: str) -> str:
        """خروجی گزارش همه کارمندان در یک فایل PDF"""
        pdf = FPDF()
        pdf.set_auto_page_break(auto=True, margin=15)

        font_name = self._setup_font(pdf)

        # صفحه اول: خلاصه کلی
        pdf.add_page()
        pdf.set_font(font_name, 'B', 16)
        pdf.cell(0, 10, self._fix_rtl(f"خلاصه گزارش V2 - {month_name} {year}"), ln=True, align='C')
        pdf.set_font(font_name, '', 12)
        pdf.cell(0, 8, self._fix_rtl(f"تعداد کارمندان: {len(reports)}"), ln=True, align='C')
        pdf.ln(5)

        pdf.set_font(font_name, 'B', 7)
        headers = ['ردیف', 'کد', 'نام', 'موظفی', 'حضور', 'مرخصی', 'غیبت', 'کارکرد', 'اضافی', 'کسری']
        col_widths = [12, 18, 35, 18, 15, 15, 15, 18, 18, 18]

        page_width = pdf.w - 2 * pdf.l_margin
        table_width = sum(col_widths)
        start_x = pdf.l_margin + (page_width - table_width)

        current_x = start_x + table_width
        for i, header in enumerate(headers):
            current_x -= col_widths[i]
            pdf.set_xy(current_x, pdf.get_y())
            pdf.cell(col_widths[i], 6, self._fix_rtl(header), border=1, align='C')
        pdf.ln()

        pdf.set_font(font_name, '', 7)
        for idx, report in enumerate(reports, 1):
            emp = report['employee']
            summary = report['summary']

            values = [
                str(idx),
                emp['user_id'],
                emp['full_name'][:15],
                self._fmt_hours(summary['duty_hours']),
                str(summary['present_days']),
                str(summary['leave_days']),
                str(summary['absent_days']),
                self._fmt_hours(summary['total_work_hours']),
                self._fmt_hours(summary['total_surplus']),
                self._fmt_hours(summary['total_deficit'])
            ]

            current_x = start_x + table_width
            for i, value in enumerate(values):
                current_x -= col_widths[i]
                pdf.set_xy(current_x, pdf.get_y())
                if i in [0, 1, 4, 5, 6]:
                    pdf.cell(col_widths[i], 5, value, border=1, align='C')
                else:
                    pdf.cell(col_widths[i], 5, self._fix_rtl(value), border=1, align='C')
            pdf.ln()

        # صفحات بعدی: گزارش تفصیلی هر کارمند
        for report in reports:
            pdf.add_page()
            self._add_employee_detail_to_pdf(pdf, report, font_name)

        filename = self.output_dir / f"گزارش_کلی_V2_{month_name}_{year}.pdf"
        pdf.output(str(filename))
        return str(filename)

    def _add_employee_detail_to_pdf(self, pdf: FPDF, report: Dict, font_name: str):
        """اضافه کردن گزارش تفصیلی یک کارمند"""
        emp = report['employee']
        summary = report['summary']

        pdf.set_font(font_name, 'B', 14)
        pdf.cell(0, 10, self._fix_rtl(f"{emp['full_name']} ({emp['user_id']})"), ln=True, align='C')
        pdf.set_font(font_name, '', 10)
        pdf.cell(0, 6, self._fix_rtl(f"دپارتمان: {emp['department']} | {report['month_name']} {report['year']}"),
                 ln=True, align='C')
        pdf.ln(3)

        pdf.set_font(font_name, 'B', 8)
        pdf.cell(0, 6, self._fix_rtl('گزارش روزانه'), ln=True, align='R')
        pdf.ln(1)

        pdf.set_font(font_name, 'B', 6)
        headers = ['تاریخ', 'روز', 'وضعیت روز', 'وضعیت فرد', 'و۱', 'خ۱', 'و۲', 'خ۲', 'و۳', 'خ۳', 'وضعیت تردد', 'کارکرد',
                   'اضافی', 'کسری']
        col_widths = [18, 15, 13, 18, 11, 11, 11, 11, 11, 11, 16, 11, 11, 11]

        page_width = pdf.w - 2 * pdf.l_margin
        table_width = sum(col_widths)
        start_x = pdf.l_margin + (page_width - table_width)

        current_x = start_x + table_width
        for i, header in enumerate(headers):
            current_x -= col_widths[i]
            pdf.set_xy(current_x, pdf.get_y())
            pdf.cell(col_widths[i], 5, self._fix_rtl(header), border=1, align='C')
        pdf.ln()

        pdf.set_font(font_name, '', 5)
        for day in report['days']:
            def fmt_time(dt):
                return dt.strftime('%H:%M') if dt else '-'

            def fmt_hours(h):
                if h == 0:
                    return '-'
                hours = int(h)
                minutes = int((h - hours) * 60)
                return f"{hours:02d}:{minutes:02d}"

            pairs = day.get('attendance_pairs', [])
            enter1 = fmt_time(pairs[0]['enter']) if len(pairs) > 0 else '-'
            exit1 = fmt_time(pairs[0]['exit']) if len(pairs) > 0 else '-'
            enter2 = fmt_time(pairs[1]['enter']) if len(pairs) > 1 else '-'
            exit2 = fmt_time(pairs[1]['exit']) if len(pairs) > 1 else '-'
            enter3 = fmt_time(pairs[2]['enter']) if len(pairs) > 2 else '-'
            exit3 = fmt_time(pairs[2]['exit']) if len(pairs) > 2 else '-'

            attendance_str = day['attendance_status']
            if attendance_str == 'بدون تردد':
                attendance_str = '-'

            values = [
                day['jalali_date'],
                day['day_name'][:6],
                day['day_status'][:6],
                day['person_status_name'][:10],
                enter1, exit1,
                enter2, exit2,
                enter3, exit3,
                attendance_str[:10],
                fmt_hours(day['work_hours']),
                fmt_hours(day['surplus']),
                fmt_hours(day['deficit'])
            ]

            if pdf.get_y() > pdf.h - 20:
                pdf.add_page()
                pdf.set_font(font_name, 'B', 6)
                current_x = start_x + table_width
                for i, header in enumerate(headers):
                    current_x -= col_widths[i]
                    pdf.set_xy(current_x, pdf.get_y())
                    pdf.cell(col_widths[i], 5, self._fix_rtl(header), border=1, align='C')
                pdf.ln()
                pdf.set_font(font_name, '', 5)

            current_x = start_x + table_width
            for i, value in enumerate(values):
                current_x -= col_widths[i]
                pdf.set_xy(current_x, pdf.get_y())
                if i in [0, 4, 5, 6, 7, 8, 9, 11, 12, 13]:
                    pdf.cell(col_widths[i], 4, value, border=1, align='C')
                else:
                    pdf.cell(col_widths[i], 4, self._fix_rtl(value), border=1, align='C')
            pdf.ln()

        pdf.ln(4)

        # خلاصه
        pdf.set_font(font_name, 'B', 11)
        pdf.cell(0, 7, self._fix_rtl('خلاصه ماهانه'), ln=True, align='R')
        pdf.ln(2)

        pdf.set_font(font_name, '', 9)
        pdf.cell(0, 5,
                 self._fix_rtl(f"موظفی: {summary['duty_days']} روز / {self._fmt_hours(summary['duty_hours'])} ساعت"),
                 ln=True, align='R')
        pdf.cell(0, 5, self._fix_rtl(f"حضور: {summary['present_days']} | جمعه کاری: {summary['friday_work_days']} | تعطیل کاری: {summary['holiday_work_days']} | مرخصی: {summary['leave_days']} | غیبت: {summary['absent_days']} | استراحت: {summary['rest_days']} | تعطیل: {summary['holiday_days']}"), ln=True, align='R')

        pdf.cell(0, 5, self._fix_rtl(
            f"کارکرد: {self._fmt_hours(summary['total_work_hours'])} | صبح: {self._fmt_hours(summary['total_morning'])} | عصر: {self._fmt_hours(summary['total_evening'])} | شب: {self._fmt_hours(summary['total_night'])}"),
                 ln=True, align='R')
        pdf.cell(0, 5, self._fix_rtl(
            f"اضافی: {self._fmt_hours(summary['total_surplus'])} | کسری: {self._fmt_hours(summary['total_deficit'])} | هفتگی: {self._fmt_hours(summary['weekly_overtime'])} | جمعه کاری: {self._fmt_hours(summary['friday_work_hours'])}"),
                 ln=True, align='R')

        # ✅ وضعیت کلی
        pdf.set_font(font_name, 'B', 9)
        pdf.cell(0, 5, self._fix_rtl('وضعیت کلی:'), ln=True, align='R')
        pdf.set_font(font_name, '', 9)
        # ✅ خط آخر با تهاتر و مقدار عددی
        pdf.cell(0, 5, self._fix_rtl(f"تهاتر: {self._fmt_hours(abs(summary['net_balance']))} ({abs(summary['net_balance']):.2f} عددی) | وضعیت: {summary['overall_status']} | مقدار خالص: {summary['net_balance_hours']:.2f} عددی"), ln=True, align='R')