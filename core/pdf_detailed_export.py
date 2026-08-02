"""
خروجی PDF گزارش تفصیلی ماهانه
"""
from datetime import date
from typing import Dict
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
    print("⚠️  کتابخانه‌های arabic_reshaper و python-bidi نصب نشده‌اند")


class DetailedPDFExporter:
    """خروجی PDF گزارش تفصیلی"""

    def __init__(self, output_dir: str = "exports"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(exist_ok=True)
        self.font_path = self._find_persian_font()

    def _find_persian_font(self) -> str:
        """پیدا کردن فونت فارسی در سیستم"""
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
        """✅ اصلاح متن فارسی برای نمایش صحیح RTL"""
        if RTL_SUPPORT and any('\u0600' <= c <= '\u06FF' for c in text):
            reshaped_text = arabic_reshaper.reshape(text)
            bidi_text = get_display(reshaped_text)
            return bidi_text
        return text

    def export_detailed_report(self, report: Dict) -> str:
        """خروجی گزارش تفصیلی به PDF"""
        pdf = FPDF()
        pdf.add_page()

        # اضافه کردن فونت فارسی
        if os.path.exists(self.font_path):
            pdf.add_font('Persian', '', self.font_path, uni=True)
            pdf.add_font('Persian', 'B', self.font_path, uni=True)
            font_name = 'Persian'
        else:
            font_name = 'Helvetica'

        emp = report['employee']
        summary = report['summary']

        # هدر
        pdf.set_font(font_name, 'B', 16)
        pdf.cell(0, 10, self._fix_rtl(f"گزارش تفصیلی ماهانه - {emp['full_name']}"), ln=True, align='C')
        pdf.set_font(font_name, '', 12)
        pdf.cell(0, 8, self._fix_rtl(f"کد پرسنلی: {emp['user_id']} | دپارتمان: {emp['department']}"), ln=True, align='C')
        pdf.cell(0, 8, self._fix_rtl(f"ماه: {report['month_name']} {report['year']}"), ln=True, align='C')
        pdf.ln(5)

        # ✅ جدول روزانه از راست به چپ
        pdf.set_font(font_name, 'B', 10)
        pdf.cell(0, 8, self._fix_rtl('گزارش روزانه'), ln=True, align='R')
        pdf.ln(2)

        # ✅ هدر جدول - ترتیب عادی (تاریخ اول)
        pdf.set_font(font_name, 'B', 7)
        headers = ['تاریخ', 'روز', 'وضعیت روز', 'وضعیت فرد', 'ورود', 'خروج', 'کارکرد', 'اضافه']
        col_widths = [25, 20, 20, 25, 15, 15, 15, 15]

        # ✅ محاسبه موقعیت شروع برای RTL
        page_width = pdf.w - 2 * pdf.l_margin
        table_width = sum(col_widths)
        start_x = pdf.l_margin + (page_width - table_width)

        # رسم هدر جدول از راست به چپ
        current_x = start_x + table_width
        for i, header in enumerate(headers):
            current_x -= col_widths[i]
            pdf.set_xy(current_x, pdf.get_y())
            pdf.cell(col_widths[i], 6, self._fix_rtl(header), border=1, align='C')
        pdf.ln()

        # ✅ داده‌ها از راست به چپ
        pdf.set_font(font_name, '', 6)
        for day in report['days']:
            def fmt_time(dt):
                return dt.strftime('%H:%M') if dt else '-'

            def fmt_hours(h):
                if h == 0:
                    return '-'
                hours = int(h)
                minutes = int((h - hours) * 60)
                return f"{hours:02d}:{minutes:02d}"

            # ✅ مقادیر به ترتیب عادی (تاریخ اول)
            values = [
                day['jalali_date'],
                day['day_name'][:8],
                'تعطیل' if day['is_day_off'] else 'کاری',
                day['person_status_name'][:12],
                fmt_time(day['first_enter']),
                fmt_time(day['last_exit']),
                fmt_hours(day['work_hours']),
                fmt_hours(day['overtime'])
            ]

            # رسم سلول‌ها از راست به چپ
            current_x = start_x + table_width
            for i, value in enumerate(values):
                current_x -= col_widths[i]
                pdf.set_xy(current_x, pdf.get_y())
                # ✅ اعداد و تاریخ‌ها را اصلاح RTL نکن
                if i in [0, 4, 5, 6, 7]:  # تاریخ، ورود، خروج، کارکرد، اضافه
                    pdf.cell(col_widths[i], 5, value, border=1, align='C')
                else:  # متن فارسی
                    pdf.cell(col_widths[i], 5, self._fix_rtl(value), border=1, align='C')
            pdf.ln()

        pdf.ln(3)

        # ✅ خلاصه ماهانه - بررسی فضا
        remaining_space = pdf.h - pdf.get_y() - 20
        required_space = 50  # فضای مورد نیاز برای خلاصه فشرده

        if remaining_space < required_space:
            pdf.add_page()

        pdf.set_font(font_name, 'B', 10)
        pdf.cell(0, 8, self._fix_rtl('خلاصه ماهانه'), ln=True, align='R')
        pdf.ln(2)

        # ✅ فشرده‌تر کردن خلاصه
        pdf.set_font(font_name, '', 8)

        # موظفی
        pdf.set_font(font_name, 'B', 8)
        pdf.cell(0, 5, self._fix_rtl('موظفی:'), ln=True, align='R')
        pdf.set_font(font_name, '', 8)
        pdf.cell(0, 4, self._fix_rtl(f"روزهای موظفی: {summary['duty_days']} | ساعات موظفی: {self._fmt_hours(summary['duty_hours'])}"), ln=True, align='R')

        pdf.ln(1)

        # وضعیت روزها
        pdf.set_font(font_name, 'B', 8)
        pdf.cell(0, 5, self._fix_rtl('وضعیت روزها:'), ln=True, align='R')
        pdf.set_font(font_name, '', 8)
        pdf.cell(0, 4, self._fix_rtl(f"حضور: {summary['present_days']} | مرخصی: {summary['leave_days']} | غیبت: {summary['absent_days']} | استراحت: {summary['rest_days']} | جمعه کاری: {summary['friday_work_days']}"), ln=True, align='R')

        pdf.ln(1)

        # ساعات کاری
        pdf.set_font(font_name, 'B', 8)
        pdf.cell(0, 5, self._fix_rtl('ساعات کاری:'), ln=True, align='R')
        pdf.set_font(font_name, '', 8)
        pdf.cell(0, 4, self._fix_rtl(f"کارکرد ماهانه: {self._fmt_hours(summary['total_work_hours'])} | صبح: {self._fmt_hours(summary['total_morning'])} | عصر: {self._fmt_hours(summary['total_evening'])} | شب: {self._fmt_hours(summary['total_night'])}"), ln=True, align='R')

        pdf.ln(1)

        # اضافه کاری
        pdf.set_font(font_name, 'B', 8)
        pdf.cell(0, 5, self._fix_rtl('اضافه کاری:'), ln=True, align='R')
        pdf.set_font(font_name, '', 8)
        pdf.cell(0, 4, self._fix_rtl(f"روزانه: {self._fmt_hours(summary['daily_overtime'])} | هفتگی: {self._fmt_hours(summary['weekly_overtime'])} | جمعه کاری: {self._fmt_hours(summary['friday_work_hours'])}"), ln=True, align='R')

        pdf.ln(1)

        # کسری و اضافی
        pdf.set_font(font_name, 'B', 8)
        pdf.cell(0, 5, self._fix_rtl('کسری و اضافی:'), ln=True, align='R')
        pdf.set_font(font_name, '', 8)
        pdf.cell(0, 4, self._fix_rtl(f"مجموع کسری: {self._fmt_hours(summary['deficit'])} | مجموع اضافی: {self._fmt_hours(summary['surplus'])}"), ln=True, align='R')

        # ذخیره
        filename = self.output_dir / f"گزارش_تفصیلی_{emp['full_name']}_{report['month_name']}_{report['year']}.pdf"
        pdf.output(str(filename))
        return str(filename)

    def _fmt_hours(self, h: float) -> str:
        """فرمت ساعات"""
        if h == 0:
            return '00:00'
        hours = int(h)
        minutes = int((h - hours) * 60)
        return f"{hours:02d}:{minutes:02d}"

    def export_all_employees_report(self, reports: List[Dict], year: int, month: int, month_name: str) -> str:
        """خروجی گزارش همه کارمندان در یک فایل PDF"""
        pdf = FPDF()
        pdf.set_auto_page_break(auto=True, margin=15)

        # اضافه کردن فونت فارسی
        if os.path.exists(self.font_path):
            pdf.add_font('Persian', '', self.font_path, uni=True)
            pdf.add_font('Persian', 'B', self.font_path, uni=True)
            font_name = 'Persian'
        else:
            font_name = 'Helvetica'

        # ✅ صفحه اول: خلاصه کلی
        pdf.add_page()
        pdf.set_font(font_name, 'B', 16)
        pdf.cell(0, 10, self._fix_rtl(f"خلاصه گزارش ماهانه - {month_name} {year}"), ln=True, align='C')
        pdf.set_font(font_name, '', 12)
        pdf.cell(0, 8, self._fix_rtl(f"تعداد کارمندان: {len(reports)}"), ln=True, align='C')
        pdf.ln(5)

        # جدول خلاصه
        pdf.set_font(font_name, 'B', 8)
        headers = ['ردیف', 'کد', 'نام', 'موظفی', 'حضور', 'مرخصی', 'غیبت', 'کارکرد', 'اضافه', 'کسری']
        col_widths = [12, 18, 35, 18, 15, 15, 15, 18, 18, 18]

        page_width = pdf.w - 2 * pdf.l_margin
        table_width = sum(col_widths)
        start_x = pdf.l_margin + (page_width - table_width)

        # رسم هدر
        current_x = start_x + table_width
        for i, header in enumerate(headers):
            current_x -= col_widths[i]
            pdf.set_xy(current_x, pdf.get_y())
            pdf.cell(col_widths[i], 6, self._fix_rtl(header), border=1, align='C')
        pdf.ln()

        # داده‌ها
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
                self._fmt_hours(summary['surplus']),
                self._fmt_hours(summary['deficit'])
            ]

            current_x = start_x + table_width
            for i, value in enumerate(values):
                current_x -= col_widths[i]
                pdf.set_xy(current_x, pdf.get_y())
                if i in [0, 1, 4, 5, 6]:  # اعداد
                    pdf.cell(col_widths[i], 5, value, border=1, align='C')
                else:
                    pdf.cell(col_widths[i], 5, self._fix_rtl(value), border=1, align='C')
            pdf.ln()

        # ✅ صفحات بعدی: گزارش تفصیلی هر کارمند
        for report in reports:
            pdf.add_page()
            self._add_employee_detail_to_pdf(pdf, report, font_name)

        # ذخیره
        filename = self.output_dir / f"گزارش_کلی_کارمندان_{month_name}_{year}.pdf"
        pdf.output(str(filename))
        return str(filename)


"""
خروجی PDF گزارش تفصیلی ماهانه
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
    print("⚠️  کتابخانه‌های arabic_reshaper و python-bidi نصب نشده‌اند")


class DetailedPDFExporter:
    """خروجی PDF گزارش تفصیلی"""

    def __init__(self, output_dir: str = "exports"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(exist_ok=True)
        self.font_path = self._find_persian_font()

    def _find_persian_font(self) -> str:
        """پیدا کردن فونت فارسی در سیستم"""
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
        """✅ اصلاح متن فارسی برای نمایش صحیح RTL"""
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

        # هدر
        pdf.set_font(font_name, 'B', 16)
        pdf.cell(0, 10, self._fix_rtl(f"گزارش تفصیلی ماهانه - {emp['full_name']}"), ln=True, align='C')
        pdf.set_font(font_name, '', 12)
        pdf.cell(0, 8, self._fix_rtl(f"کد پرسنلی: {emp['user_id']} | دپارتمان: {emp['department']}"), ln=True,
                 align='C')
        pdf.cell(0, 8, self._fix_rtl(f"ماه: {report['month_name']} {report['year']}"), ln=True, align='C')
        pdf.ln(5)

        # ✅ جدول روزانه از راست به چپ
        pdf.set_font(font_name, 'B', 10)
        pdf.cell(0, 8, self._fix_rtl('گزارش روزانه'), ln=True, align='R')
        pdf.ln(2)

        # هدر جدول با ستون وضعیت تردد
        pdf.set_font(font_name, 'B', 7)
        headers = ['تاریخ', 'روز', 'وضعیت روز', 'وضعیت فرد', 'ورود', 'خروج', 'وضعیت تردد', 'کارکرد', 'اضافه']
        col_widths = [22, 18, 16, 22, 13, 13, 20, 13, 13]

        page_width = pdf.w - 2 * pdf.l_margin
        table_width = sum(col_widths)
        start_x = pdf.l_margin + (page_width - table_width)

        # رسم هدر
        current_x = start_x + table_width
        for i, header in enumerate(headers):
            current_x -= col_widths[i]
            pdf.set_xy(current_x, pdf.get_y())
            pdf.cell(col_widths[i], 6, self._fix_rtl(header), border=1, align='C')
        pdf.ln()

        # داده‌ها
        pdf.set_font(font_name, '', 6)
        for day in report['days']:
            def fmt_time(dt):
                return dt.strftime('%H:%M') if dt else '-'

            def fmt_hours(h):
                if h == 0:
                    return '-'
                hours = int(h)
                minutes = int((h - hours) * 60)
                return f"{hours:02d}:{minutes:02d}"

            attendance_str = day['attendance_status']
            if attendance_str == 'بدون تردد':
                attendance_str = '-'

            values = [
                day['jalali_date'],
                day['day_name'][:8],
                'تعطیل' if day['is_day_off'] else 'کاری',
                day['person_status_name'][:12],
                fmt_time(day['first_enter']),
                fmt_time(day['last_exit']),
                attendance_str[:12],
                fmt_hours(day['work_hours']),
                fmt_hours(day['overtime'])
            ]

            current_x = start_x + table_width
            for i, value in enumerate(values):
                current_x -= col_widths[i]
                pdf.set_xy(current_x, pdf.get_y())
                if i in [0, 4, 5, 7, 8]:
                    pdf.cell(col_widths[i], 5, value, border=1, align='C')
                else:
                    pdf.cell(col_widths[i], 5, self._fix_rtl(value), border=1, align='C')
            pdf.ln()

        pdf.ln(5)

        # خلاصه ماهانه
        remaining_space = pdf.h - pdf.get_y() - 20
        required_space = 80

        if remaining_space < required_space:
            pdf.add_page()

        pdf.set_font(font_name, 'B', 10)
        pdf.cell(0, 8, self._fix_rtl('خلاصه ماهانه'), ln=True, align='R')
        pdf.ln(2)

        pdf.set_font(font_name, '', 8)

        pdf.set_font(font_name, 'B', 8)
        pdf.cell(0, 5, self._fix_rtl('موظفی:'), ln=True, align='R')
        pdf.set_font(font_name, '', 8)
        pdf.cell(0, 4, self._fix_rtl(
            f"روزهای موظفی: {summary['duty_days']} | ساعات موظفی: {self._fmt_hours(summary['duty_hours'])}"), ln=True,
                 align='R')

        pdf.ln(1)

        pdf.set_font(font_name, 'B', 8)
        pdf.cell(0, 5, self._fix_rtl('وضعیت روزها:'), ln=True, align='R')
        pdf.set_font(font_name, '', 8)
        pdf.cell(0, 4, self._fix_rtl(
            f"حضور: {summary['present_days']} | مرخصی: {summary['leave_days']} | غیبت: {summary['absent_days']} | استراحت: {summary['rest_days']} | جمعه کاری: {summary['friday_work_days']}"),
                 ln=True, align='R')

        pdf.ln(1)

        pdf.set_font(font_name, 'B', 8)
        pdf.cell(0, 5, self._fix_rtl('ساعات کاری:'), ln=True, align='R')
        pdf.set_font(font_name, '', 8)
        pdf.cell(0, 4, self._fix_rtl(
            f"کارکرد ماهانه: {self._fmt_hours(summary['total_work_hours'])} | صبح: {self._fmt_hours(summary['total_morning'])} | عصر: {self._fmt_hours(summary['total_evening'])} | شب: {self._fmt_hours(summary['total_night'])}"),
                 ln=True, align='R')

        pdf.ln(1)

        pdf.set_font(font_name, 'B', 8)
        pdf.cell(0, 5, self._fix_rtl('اضافه کاری:'), ln=True, align='R')
        pdf.set_font(font_name, '', 8)
        pdf.cell(0, 4, self._fix_rtl(
            f"روزانه: {self._fmt_hours(summary['daily_overtime'])} | هفتگی: {self._fmt_hours(summary['weekly_overtime'])} | جمعه کاری: {self._fmt_hours(summary['friday_work_hours'])}"),
                 ln=True, align='R')

        pdf.ln(1)

        pdf.set_font(font_name, 'B', 8)
        pdf.cell(0, 5, self._fix_rtl('کسری و اضافی:'), ln=True, align='R')
        pdf.set_font(font_name, '', 8)
        pdf.cell(0, 4, self._fix_rtl(
            f"مجموع کسری: {self._fmt_hours(summary['deficit'])} | مجموع اضافی: {self._fmt_hours(summary['surplus'])}"),
                 ln=True, align='R')

        # ذخیره
        filename = self.output_dir / f"گزارش_تفصیلی_{emp['full_name']}_{report['month_name']}_{report['year']}.pdf"
        pdf.output(str(filename))
        return str(filename)

    def export_all_employees_report(self, reports: List[Dict], year: int, month: int, month_name: str) -> str:
        """خروجی گزارش همه کارمندان در یک فایل PDF"""
        pdf = FPDF()
        pdf.set_auto_page_break(auto=True, margin=15)

        font_name = self._setup_font(pdf)

        # ✅ صفحه اول: خلاصه کلی
        pdf.add_page()
        pdf.set_font(font_name, 'B', 16)
        pdf.cell(0, 10, self._fix_rtl(f"خلاصه گزارش ماهانه - {month_name} {year}"), ln=True, align='C')
        pdf.set_font(font_name, '', 12)
        pdf.cell(0, 8, self._fix_rtl(f"تعداد کارمندان: {len(reports)}"), ln=True, align='C')
        pdf.ln(5)

        # جدول خلاصه
        pdf.set_font(font_name, 'B', 8)
        headers = ['ردیف', 'کد', 'نام', 'موظفی', 'حضور', 'مرخصی', 'غیبت', 'کارکرد', 'اضافه', 'کسری']
        col_widths = [12, 18, 35, 18, 15, 15, 15, 18, 18, 18]

        page_width = pdf.w - 2 * pdf.l_margin
        table_width = sum(col_widths)
        start_x = pdf.l_margin + (page_width - table_width)

        # رسم هدر
        current_x = start_x + table_width
        for i, header in enumerate(headers):
            current_x -= col_widths[i]
            pdf.set_xy(current_x, pdf.get_y())
            pdf.cell(col_widths[i], 6, self._fix_rtl(header), border=1, align='C')
        pdf.ln()

        # داده‌ها
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
                self._fmt_hours(summary['surplus']),
                self._fmt_hours(summary['deficit'])
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

        # ✅ صفحات بعدی: گزارش تفصیلی هر کارمند
        for report in reports:
            pdf.add_page()
            self._add_employee_detail_to_pdf(pdf, report, font_name)

        # ذخیره
        filename = self.output_dir / f"گزارش_کلی_کارمندان_{month_name}_{year}.pdf"
        pdf.output(str(filename))
        return str(filename)

    def _add_employee_detail_to_pdf(self, pdf: FPDF, report: Dict, font_name: str):
        """اضافه کردن گزارش تفصیلی یک کارمند به PDF"""
        emp = report['employee']
        summary = report['summary']

        # ✅ هدر کارمند - فونت بزرگ‌تر
        pdf.set_font(font_name, 'B', 16)
        pdf.cell(0, 12, self._fix_rtl(f"گزارش تفصیلی - {emp['full_name']} ({emp['user_id']})"), ln=True, align='C')
        pdf.set_font(font_name, '', 11)
        pdf.cell(0, 7, self._fix_rtl(f"دپارتمان: {emp['department']} | ماه: {report['month_name']} {report['year']}"),
                 ln=True, align='C')
        pdf.ln(4)

        # ✅ جدول روزانه با ستون وضعیت تردد - فونت بزرگ‌تر
        pdf.set_font(font_name, 'B', 9)
        pdf.cell(0, 7, self._fix_rtl('گزارش روزانه'), ln=True, align='R')
        pdf.ln(2)

        pdf.set_font(font_name, 'B', 7)
        headers = ['تاریخ', 'روز', 'وضعیت روز', 'وضعیت فرد', 'ورود', 'خروج', 'وضعیت تردد', 'کارکرد', 'اضافه']
        col_widths = [22, 18, 16, 22, 13, 13, 20, 13, 13]

        page_width = pdf.w - 2 * pdf.l_margin
        table_width = sum(col_widths)
        start_x = pdf.l_margin + (page_width - table_width)

        # رسم هدر
        current_x = start_x + table_width
        for i, header in enumerate(headers):
            current_x -= col_widths[i]
            pdf.set_xy(current_x, pdf.get_y())
            pdf.cell(col_widths[i], 6, self._fix_rtl(header), border=1, align='C')
        pdf.ln()

        # ✅ داده‌ها با ستون وضعیت تردد - فونت بزرگ‌تر
        pdf.set_font(font_name, '', 7)
        for day in report['days']:
            def fmt_time(dt):
                return dt.strftime('%H:%M') if dt else '-'

            def fmt_hours(h):
                if h == 0:
                    return '-'
                hours = int(h)
                minutes = int((h - hours) * 60)
                return f"{hours:02d}:{minutes:02d}"

            attendance_str = day['attendance_status']
            if attendance_str == 'بدون تردد':
                attendance_str = '-'

            values = [
                day['jalali_date'],
                day['day_name'][:8],
                'تعطیل' if day['is_day_off'] else 'کاری',
                day['person_status_name'][:12],
                fmt_time(day['first_enter']),
                fmt_time(day['last_exit']),
                attendance_str[:12],
                fmt_hours(day['work_hours']),
                fmt_hours(day['overtime'])
            ]

            # بررسی فضا
            if pdf.get_y() > pdf.h - 20:
                pdf.add_page()
                # رسم مجدد هدر
                pdf.set_font(font_name, 'B', 7)
                current_x = start_x + table_width
                for i, header in enumerate(headers):
                    current_x -= col_widths[i]
                    pdf.set_xy(current_x, pdf.get_y())
                    pdf.cell(col_widths[i], 6, self._fix_rtl(header), border=1, align='C')
                pdf.ln()
                pdf.set_font(font_name, '', 7)

            current_x = start_x + table_width
            for i, value in enumerate(values):
                current_x -= col_widths[i]
                pdf.set_xy(current_x, pdf.get_y())
                # ✅ اعداد و تاریخ‌ها را اصلاح RTL نکن
                if i in [0, 4, 5, 7, 8]:  # تاریخ، ورود، خروج، کارکرد، اضافه
                    pdf.cell(col_widths[i], 5, value, border=1, align='C')
                else:  # متن فارسی
                    pdf.cell(col_widths[i], 5, self._fix_rtl(value), border=1, align='C')
            pdf.ln()

        pdf.ln(4)

        # ✅ خلاصه - فونت بزرگ‌تر
        pdf.set_font(font_name, 'B', 11)
        pdf.cell(0, 7, self._fix_rtl('خلاصه ماهانه'), ln=True, align='R')
        pdf.ln(2)

        pdf.set_font(font_name, '', 9)
        pdf.cell(0, 5,
                 self._fix_rtl(f"موظفی: {summary['duty_days']} روز / {self._fmt_hours(summary['duty_hours'])} ساعت"),
                 ln=True, align='R')
        pdf.cell(0, 5, self._fix_rtl(
            f"حضور: {summary['present_days']} | مرخصی: {summary['leave_days']} | غیبت: {summary['absent_days']} | استراحت: {summary['rest_days']} | جمعه کاری: {summary['friday_work_days']}"),
                 ln=True, align='R')
        pdf.cell(0, 5, self._fix_rtl(
            f"کارکرد: {self._fmt_hours(summary['total_work_hours'])} | صبح: {self._fmt_hours(summary['total_morning'])} | عصر: {self._fmt_hours(summary['total_evening'])} | شب: {self._fmt_hours(summary['total_night'])}"),
                 ln=True, align='R')
        pdf.cell(0, 5, self._fix_rtl(
            f"اضافه روزانه: {self._fmt_hours(summary['daily_overtime'])} | هفتگی: {self._fmt_hours(summary['weekly_overtime'])} | جمعه کاری: {self._fmt_hours(summary['friday_work_hours'])}"),
                 ln=True, align='R')
        pdf.cell(0, 5, self._fix_rtl(
            f"کسری: {self._fmt_hours(summary['deficit'])} | اضافی: {self._fmt_hours(summary['surplus'])}"), ln=True,
                 align='R')