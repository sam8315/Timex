"""
سرویس خروجی PDF گزارشات - با پشتیبانی کامل از فارسی
"""
from pathlib import Path
from typing import Dict
import os

try:
    from fpdf import FPDF
except ImportError:
    raise ImportError("لطفاً ابتدا fpdf2 را نصب کنید: pip install fpdf2")

try:
    import arabic_reshaper
    from bidi.algorithm import get_display
    HAS_RTL_SUPPORT = True
except ImportError:
    HAS_RTL_SUPPORT = False
    print("⚠️ arabic_reshaper یا python-bidi نصب نیست. متن فارسی ممکن است برعکس نمایش داده شود.")

# مسیرهای احتمالی فونت
BASE_DIR = Path(__file__).parent.parent.parent
POSSIBLE_FONT_PATHS = [
    BASE_DIR / "static" / "fonts",
    BASE_DIR / "fonts",
    BASE_DIR / "web" / "static" / "fonts",
]

OUTPUT_DIR = BASE_DIR / "static" / "exports"


class PdfReportExporter:
    """تولید PDF گزارش تفصیلی ماهانه با پشتیبانی کامل از فارسی"""

    def __init__(self):
        self.output_dir = OUTPUT_DIR
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.font_dir = self._find_font_dir()
        self.font_name = None

    def _find_font_dir(self) -> Path:
        """پیدا کردن پوشه فونت"""
        for path in POSSIBLE_FONT_PATHS:
            if path.exists():
                return path

        # اگر نبود، ایجاد کن
        font_dir = BASE_DIR / "static" / "fonts"
        font_dir.mkdir(parents=True, exist_ok=True)
        return font_dir

    def _setup_font(self, pdf: FPDF) -> str:
        """تنظیم فونت فارسی"""
        font_name = 'Vazir'

        # مسیرهای احتمالی فونت
        regular_font = self.font_dir / "Vazirmatn-Regular.ttf"
        bold_font = self.font_dir / "Vazirmatn-Bold.ttf"

        # اگر Bold نبود، از Regular استفاده کن
        if not bold_font.exists():
            bold_font = regular_font

        try:
            if regular_font.exists():
                # در fpdf2 نیازی به uni=True نیست
                pdf.add_font(font_name, '', str(regular_font))
                if bold_font.exists():
                    pdf.add_font(font_name, 'B', str(bold_font))
                else:
                    pdf.add_font(font_name, 'B', str(regular_font))
                self.font_name = font_name
                return font_name
            else:
                print(f"⚠️ فونت فارسی در {self.font_dir} یافت نشد")
                print(f"   لطفاً Vazirmatn-Regular.ttf را در {self.font_dir} قرار دهید")
                # استفاده از فونت پیش‌فرض
                return 'helvetica'
        except Exception as e:
            print(f"⚠️ خطا در لود فونت: {e}")
            return 'helvetica'

    def _fix_rtl(self, text: str) -> str:
        """اصلاح متن راست‌به‌چپ برای نمایش صحیح در PDF"""
        if text is None:
            return ''
        text = str(text)
        if not HAS_RTL_SUPPORT:
            return text
        try:
            reshaped = arabic_reshaper.reshape(text)
            return get_display(reshaped)
        except Exception:
            return text

    def _fmt_hours(self, hours: float) -> str:
        """تبدیل ساعت اعشاری به فرمت HH:MM"""
        if hours is None or hours == 0:
            return '-'
        total_minutes = int(round(float(hours) * 60))
        h = total_minutes // 60
        m = total_minutes % 60
        return f"{h:02d}:{m:02d}"

    def _fmt_time(self, dt) -> str:
        """فرمت datetime به HH:MM"""
        if dt is None:
            return '-'
        try:
            return dt.strftime('%H:%M')
        except Exception:
            return '-'

    def _get_first_last(self, day: dict):
        """استخراج اولین ورود و آخرین خروج از attendance_pairs"""
        pairs = day.get('attendance_pairs', [])
        if not pairs:
            return None, None
        first_enter = pairs[0].get('enter')
        last_exit = pairs[-1].get('exit')
        return first_enter, last_exit

    def _draw_rtl_cell(self, pdf: FPDF, width: int, height: int, text: str,
                       border: int = 1, align: str = 'C', is_number: bool = False):
        """رسم سلول با متن راست‌به‌چپ"""
        if is_number:
            # اعداد نیازی به reshaping ندارند
            pdf.cell(width, height, str(text), border=border, align=align)
        else:
            pdf.cell(width, height, self._fix_rtl(text), border=border, align=align)

    def export_detailed_report(self, report: Dict) -> str:
        """خروجی گزارش تفصیلی یک کارمند به PDF"""
        # 🆕 استفاده از جهت افقی برای ستون‌های بیشتر
        pdf = FPDF(orientation='L', unit='mm', format='A4')
        pdf.add_page()
        pdf.set_auto_page_break(auto=True, margin=15)

        font_name = self._setup_font(pdf)
        emp = report['employee']
        summary = report['summary']

        # ============================================
        # هدر
        # ============================================
        pdf.set_font(font_name, 'B', 16)
        pdf.cell(0, 10, self._fix_rtl(f"گزارش تفصیلی ماهانه - {emp['full_name']}"),
                 ln=True, align='C')

        pdf.set_font(font_name, '', 11)
        pdf.cell(0, 8, self._fix_rtl(
            f"کد پرسنلی: {emp['user_id']} | دپارتمان: {emp['department'] or '-'}"
        ), ln=True, align='C')

        pdf.cell(0, 8, self._fix_rtl(
            f"ماه: {report['month_name']} {report['year']}"
        ), ln=True, align='C')
        pdf.ln(5)

        # ============================================
        # جدول روزانه
        # ============================================
        pdf.set_font(font_name, 'B', 11)
        pdf.cell(0, 8, self._fix_rtl('گزارش روزانه'), ln=True, align='R')
        pdf.ln(2)

        # تعریف ستون‌ها (از راست به چپ)
        headers = ['تاریخ', 'روز', 'وضعیت روز', 'وضعیت فرد',
                   'ورود', 'خروج', 'وضعیت تردد',
                   'کارکرد', 'اضافه', 'کسری']
        col_widths = [28, 20, 20, 30, 16, 16, 28, 16, 16, 16]

        # عرض صفحه و محاسبه start_x
        page_width = pdf.w - 2 * pdf.l_margin
        table_width = sum(col_widths)
        start_x = pdf.l_margin + (page_width - table_width) / 2

        # رسم هدر جدول
        pdf.set_font(font_name, 'B', 8)
        pdf.set_fill_color(30, 41, 59)  # رنگ تیره
        pdf.set_text_color(255, 255, 255)

        current_x = start_x + table_width
        for i, header in enumerate(headers):
            current_x -= col_widths[i]
            pdf.set_xy(current_x, pdf.get_y())
            pdf.cell(col_widths[i], 7, self._fix_rtl(header), border=1, align='C', fill=True)
        pdf.ln()

        # رنگ‌بندی ردیف‌ها
        pdf.set_text_color(0, 0, 0)

        # ============================================
        # داده‌های روزانه
        # ============================================
        pdf.set_font(font_name, '', 7)

        for day in report['days']:
            # بررسی نیاز به صفحه جدید
            if pdf.get_y() > pdf.h - 20:
                pdf.add_page()

            # رنگ پس‌زمینه بر اساس وضعیت
            is_friday = day.get('is_friday', False)
            is_holiday = day.get('is_holiday', False)
            is_day_off = day.get('is_day_off', False)
            person_status = day.get('person_status', '')

            if person_status == 'L':
                pdf.set_fill_color(219, 234, 254)  # آبی روشن - مرخصی
                fill = True
            elif person_status == 'A':
                pdf.set_fill_color(254, 226, 226)  # قرمز روشن - غیبت
                fill = True
            elif is_friday:
                pdf.set_fill_color(241, 245, 249)  # خاکستری روشن - جمعه
                fill = True
            elif is_holiday:
                pdf.set_fill_color(254, 243, 199)  # زرد روشن - تعطیل
                fill = True
            else:
                fill = False

            # استخراج ورود/خروج
            first_enter, last_exit = self._get_first_last(day)

            # وضعیت تردد
            attendance_str = day.get('attendance_status', 'بدون تردد')
            if attendance_str == 'بدون تردد':
                attendance_str = '-'

            # اضافه و کسری
            surplus = day.get('surplus', 0)
            deficit = day.get('deficit', 0)
            surplus_str = self._fmt_hours(surplus) if surplus > 0 else '-'
            deficit_str = self._fmt_hours(deficit) if deficit > 0 else '-'

            # مقادیر ستون‌ها
            values = [
                (day['jalali_date'], True),           # تاریخ (عدد)
                (day['day_name'][:8], False),         # روز
                ('تعطیل' if is_day_off else 'کاری', False),
                (day.get('person_status_name', '-')[:14], False),
                (self._fmt_time(first_enter), True),  # ورود (عدد)
                (self._fmt_time(last_exit), True),    # خروج (عدد)
                (attendance_str[:14], False),
                (self._fmt_hours(day['work_hours']), True),
                (surplus_str, True),
                (deficit_str, True),
            ]

            # رسم ردیف
            current_x = start_x + table_width
            for i, (value, is_number) in enumerate(values):
                current_x -= col_widths[i]
                pdf.set_xy(current_x, pdf.get_y())

                # رنگ متن برای اضافه/کسری
                if i == 8 and surplus > 0:  # اضافه - سبز
                    pdf.set_text_color(5, 150, 105)
                elif i == 9 and deficit > 0:  # کسری - قرمز
                    pdf.set_text_color(220, 38, 38)
                else:
                    pdf.set_text_color(0, 0, 0)

                if is_number:
                    pdf.cell(col_widths[i], 5, str(value), border=1, align='C', fill=fill)
                else:
                    pdf.cell(col_widths[i], 5, self._fix_rtl(str(value)),
                             border=1, align='C', fill=fill)

            pdf.set_text_color(0, 0, 0)
            pdf.ln()

        # ============================================
        # خلاصه ماهانه
        # ============================================
        pdf.ln(5)
        if pdf.get_y() > pdf.h - 80:
            pdf.add_page()

        pdf.set_font(font_name, 'B', 11)
        pdf.cell(0, 8, self._fix_rtl('خلاصه ماهانه'), ln=True, align='R')
        pdf.ln(2)

        # بخش موظفی
        pdf.set_font(font_name, 'B', 9)
        pdf.cell(0, 6, self._fix_rtl('موظفی:'), ln=True, align='R')
        pdf.set_font(font_name, '', 9)
        pdf.cell(0, 5, self._fix_rtl(
            f"روزهای موظفی: {summary['duty_days']} | ساعات موظفی: {self._fmt_hours(summary['duty_hours'])}"
        ), ln=True, align='R')
        pdf.ln(1)

        # وضعیت روزها
        pdf.set_font(font_name, 'B', 9)
        pdf.cell(0, 6, self._fix_rtl('وضعیت روزها:'), ln=True, align='R')
        pdf.set_font(font_name, '', 9)
        pdf.cell(0, 5, self._fix_rtl(
            f"حضور: {summary['present_days']} | مرخصی: {summary['leave_days']} | "
            f"غیبت: {summary['absent_days']} | استراحت: {summary['rest_days']} | "
            f"تعطیل: {summary['holiday_days']} | جمعه کاری: {summary.get('friday_work_days', 0)}"
        ), ln=True, align='R')
        pdf.ln(1)

        # ساعات کاری
        pdf.set_font(font_name, 'B', 9)
        pdf.cell(0, 6, self._fix_rtl('ساعات کاری:'), ln=True, align='R')
        pdf.set_font(font_name, '', 9)
        pdf.cell(0, 5, self._fix_rtl(
            f"کارکرد: {self._fmt_hours(summary['total_work_hours'])} | "
            f"صبح: {self._fmt_hours(summary['total_morning'])} | "
            f"عصر: {self._fmt_hours(summary['total_evening'])} | "
            f"شب: {self._fmt_hours(summary['total_night'])}"
        ), ln=True, align='R')
        pdf.ln(1)

        # اضافه کاری
        pdf.set_font(font_name, 'B', 9)
        pdf.cell(0, 6, self._fix_rtl('اضافه کاری:'), ln=True, align='R')
        pdf.set_font(font_name, '', 9)
        pdf.cell(0, 5, self._fix_rtl(
            f"هفتگی: {self._fmt_hours(summary['weekly_overtime'])} | "
            f"جمعه کاری: {self._fmt_hours(summary['friday_work_hours'])} | "
            f"تعطیل کاری: {self._fmt_hours(summary['holiday_work_hours'])}"
        ), ln=True, align='R')
        pdf.ln(1)

        # کسری و اضافی
        pdf.set_font(font_name, 'B', 9)
        pdf.cell(0, 6, self._fix_rtl('کسری و اضافی:'), ln=True, align='R')
        pdf.set_font(font_name, '', 9)
        pdf.cell(0, 5, self._fix_rtl(
            f"مجموع کسری: {self._fmt_hours(summary['total_deficit'])} | "
            f"مجموع اضافی: {self._fmt_hours(summary['total_surplus'])} | "
            f"وضعیت کلی: {summary['overall_status']} ({self._fmt_hours(summary['net_balance_hours'])} ساعت)"
        ), ln=True, align='R')

        # ============================================
        # ذخیره فایل
        # ============================================
        safe_name = (emp['full_name']
                     .replace(' ', '_')
                     .replace('/', '_')
                     .replace('\\', '_'))
        filename = self.output_dir / f"گزارش_تفصیلی_{safe_name}_{report['month_name']}_{report['year']}.pdf"

        # جلوگیری از overwrite با اضافه کردن timestamp
        if filename.exists():
            from datetime import datetime
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = self.output_dir / f"گزارش_تفصیلی_{safe_name}_{report['month_name']}_{report['year']}_{timestamp}.pdf"

        pdf.output(str(filename))
        return str(filename)