"""
خروجی اکسل گزارش تفصیلی ماهانه - نسخه ۲
با ستون‌های متعدد ورود/خروج
"""
from datetime import date
from typing import Dict, List
from pathlib import Path
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter
import jdatetime


class DetailedExcelExporterV2:
    """خروجی اکسل گزارش تفصیلی - نسخه ۲"""

    def __init__(self, output_dir: str = "exports"):
        self.output_dir = Path(output_dir)

    def _resolve_output_file(self, filename: str) -> str:
        """پوشهٔ خروجی فقط هنگام ذخیرهٔ واقعی فایل ساخته می‌شود.

        مسیر وب (stream) هیچ فایلی روی دیسک نمی‌نویسد و نباید پوشه بسازد.
        """
        self.output_dir.mkdir(parents=True, exist_ok=True)
        return str(self.output_dir / filename)

    def export_detailed_report(self, report: Dict, output=None):
        """خروجی گزارش تفصیلی یک کارمند به اکسل

        Args:
            report: گزارش تفصیلی
            output: اگر داده شود، workbook در آن stream/فایل نوشته می‌شود؛
                    در غیر این صورت در `output_dir` ذخیره می‌شود.
        Returns:
            مسیر فایل ذخیره‌شده، یا همان `output` در حالت stream.
        """
        wb = Workbook()

        ws_daily = wb.active
        ws_daily.title = "گزارش روزانه"
        self._create_daily_sheet(ws_daily, report)

        ws_summary = wb.create_sheet("خلاصه ماهانه")
        self._create_summary_sheet(ws_summary, report)

        if output is None:
            emp = report['employee']
            filename = (
                f"گزارش_تفصیلی_V2_{emp['full_name']}_"
                f"{report['month_name']}_{report['year']}.xlsx"
            )
            path = self._resolve_output_file(filename)
            wb.save(path)
            return path

        wb.save(output)
        if hasattr(output, 'seek'):
            output.seek(0)
        return output

    def export_all_employees_report(self, reports: List[Dict], year: int, month: int, month_name: str, output=None):
        """خروجی گزارش همه کارمندان در یک فایل اکسل

        Args:
            reports: لیست گزارش‌ها
            year: سال
            month: ماه
            month_name: نام ماه
            output: اگر داده شود، workbook در آن stream/فایل نوشته می‌شود؛
                    در غیر این صورت در `output_dir` ذخیره می‌شود.
        """
        wb = Workbook()

        ws_summary = wb.active
        ws_summary.title = "خلاصه کلی"
        self._create_all_summary_sheet(ws_summary, reports, year, month, month_name)

        for report in reports:
            emp = report['employee']
            sheet_name = f"{emp['full_name'][:25]} ({emp['user_id']})"
            ws = wb.create_sheet(sheet_name[:31])
            self._create_daily_sheet(ws, report)

            ws_sum = wb.create_sheet(f"خلاصه {emp['user_id']}")
            self._create_summary_sheet(ws_sum, report)

        if output is None:
            path = self._resolve_output_file(
                f"گزارش_کلی_V2_{month_name}_{year}.xlsx")
            wb.save(path)
            return path

        wb.save(output)
        if hasattr(output, 'seek'):
            output.seek(0)
        return output

    def _create_daily_sheet(self, ws, report: Dict):
        """ایجاد شیت گزارش روزانه با ستون‌های متعدد ورود/خروج"""
        emp = report['employee']
        headers = [
            'تاریخ', 'روز', 'وضعیت روز', 'وضعیت فرد',
            'ورود ۱', 'خروج ۱', 'ورود ۲', 'خروج ۲', 'ورود ۳', 'خروج ۳',
            'وضعیت تردد', 'کارکرد', 'تأخیر', 'تعجیل', 'اضافی', 'کسری'
        ]
        last_col = len(headers)

        ws.append([f"گزارش تفصیلی ماهانه V2 - {emp['full_name']} ({emp['user_id']})"])
        ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=last_col)
        ws['A1'].font = Font(bold=True, size=14)
        ws['A1'].alignment = Alignment(horizontal='center')

        ws.append([f"ماه: {report['month_name']} {report['year']}"])
        ws.merge_cells(start_row=2, start_column=1, end_row=2, end_column=last_col)
        ws['A2'].alignment = Alignment(horizontal='center')

        ws.append([])

        # ✅ هدر با ستون‌های متعدد ورود/خروج
        ws.append(headers)

        header_fill = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")
        header_font = Font(bold=True, color="FFFFFF")
        for cell in ws[4]:
            cell.fill = header_fill
            cell.font = header_font
            cell.alignment = Alignment(horizontal='center')

        for day in report['days']:
            def fmt_time(dt):
                return dt.strftime('%H:%M') if dt else '-'

            def fmt_hours(h):
                if not h:
                    return '-'
                return self._fmt_hours(h)

            # ✅ استخراج جفت‌های ورود/خروج
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

            def fmt_violation_m(minutes):
                if not minutes:
                    return '-'
                return self._fmt_hours(int(minutes) / 60.0)

            ws.append([
                day['jalali_date'],
                day['day_name'],
                day['day_status'],
                day['person_status_name'],
                enter1, exit1,
                enter2, exit2,
                enter3, exit3,
                attendance_str,
                fmt_hours(day['work_hours']),
                fmt_violation_m(day.get('late_violation_minutes')),
                fmt_violation_m(day.get('early_leave_violation_minutes')),
                fmt_hours(day['surplus']),
                fmt_hours(day['deficit'])
            ])

        self._auto_adjust_column_width(ws)

    def _create_summary_sheet(self, ws, report: Dict):
        """ایجاد شیت خلاصه ماهانه

        مقادیر مستقیماً از `report['summary']` خوانده می‌شوند — همین همان
        ساختاری است که صفحهٔ monthly-full نمایش می‌دهد (قانون: خروجی
        نباید attendance یا موظفی را دوباره حساب کند).
        """
        emp = report['employee']
        summary = report['summary']

        ws.append([f"خلاصه ماهانه - {emp['full_name']} ({emp['user_id']})"])
        ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=4)
        ws['A1'].font = Font(bold=True, size=14)
        ws['A1'].alignment = Alignment(horizontal='center')

        ws.append([f"ماه: {report['month_name']} {report['year']}"])
        ws.merge_cells(start_row=2, start_column=1, end_row=2, end_column=4)
        ws['A2'].alignment = Alignment(horizontal='center')

        ws.append([])

        def section(title):
            ws.append([title])
            row = ws.max_row
            ws.cell(row=row, column=1).font = Font(bold=True, size=12)
            ws.append([])

        def entry(label, value):
            ws.append([label, value])

        section('موظفی')
        entry('روزهای موظفی', summary['duty_days'])
        entry('ساعات موظفی', self._fmt_hours(summary['duty_hours']))

        section('وضعیت روزها')
        entry('حضور (کاری عادی)', summary['present_days'])
        entry('جمعه کاری', summary['friday_work_days'])
        entry('تعطیل کاری', summary['holiday_work_days'])
        entry('مرخصی', summary['leave_days'])
        entry('مأموریت', summary['mission_days'])
        entry('غیبت', summary['absent_days'])
        entry('استراحت', summary['rest_days'])
        entry('تعطیل', summary['holiday_days'])

        section('ساعات کاری')
        entry('کارکرد ماهانه', self._fmt_hours(summary['total_work_hours']))
        entry('ساعات صبح', self._fmt_hours(summary['total_morning']))
        entry('ساعات عصر', self._fmt_hours(summary['total_evening']))
        entry('ساعات شب', self._fmt_hours(summary['total_night']))
        entry('جمعه کاری (ساعت)', self._fmt_hours(summary['friday_work_hours']))
        entry('تعطیل کاری (ساعت)', self._fmt_hours(summary['holiday_work_hours']))

        section('اضافه کاری و کسری')
        # مبنای اضافه/کسری، موظفی هر روز از Policy/Schedule است (نه مقدار ثابت)
        entry('اضافه کاری روزانه', self._fmt_hours(summary['total_surplus']))
        entry('کسری کار', self._fmt_hours(summary['total_deficit']))
        entry('تخلف تأخیر', self._fmt_hours(summary.get('total_late_violation') or 0))
        entry('تخلف تعجیل', self._fmt_hours(summary.get('total_early_leave_violation') or 0))
        entry('اضافه کاری هفتگی', self._fmt_hours(summary['weekly_overtime']))

        section('وضعیت کلی')
        entry('تهاتر اضافی و کسری',
              self._fmt_hours(abs(summary['net_balance'])))
        entry('وضعیت نهایی', summary['overall_status'])
        entry('مقدار خالص (ساعت)', summary['net_balance_hours'])

        self._auto_adjust_column_width(ws)

    def _create_all_summary_sheet(self, ws, reports: List[Dict], year: int, month: int, month_name: str):
        """ایجاد شیت خلاصه کلی همه کارمندان"""
        ws.append([f"خلاصه گزارش ماهانه V2 - {month_name} {year}"])
        ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=12)
        ws['A1'].font = Font(bold=True, size=14)
        ws['A1'].alignment = Alignment(horizontal='center')

        ws.append([f"تعداد کارمندان: {len(reports)}"])
        ws.merge_cells(start_row=2, start_column=1, end_row=2, end_column=12)
        ws['A2'].alignment = Alignment(horizontal='center')

        ws.append([])

        headers = [
            'ردیف', 'کد', 'نام کامل', 'دپارتمان',
            'روز موظفی', 'ساعت موظفی', 'حضور', 'مرخصی', 'غیبت',
            'کارکرد', 'اضافی', 'کسری'
        ]
        ws.append(headers)

        header_fill = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")
        header_font = Font(bold=True, color="FFFFFF")
        for cell in ws[4]:
            cell.fill = header_fill
            cell.font = header_font
            cell.alignment = Alignment(horizontal='center')

        for i, report in enumerate(reports, 1):
            emp = report['employee']
            summary = report['summary']

            ws.append([
                i,
                emp['user_id'],
                emp['full_name'],
                emp['department'],
                summary['duty_days'],
                self._fmt_hours(summary['duty_hours']),
                summary['present_days'],
                summary['leave_days'],
                summary['absent_days'],
                self._fmt_hours(summary['total_work_hours']),
                self._fmt_hours(summary['total_surplus']),
                self._fmt_hours(summary['total_deficit'])
            ])

        self._auto_adjust_column_width(ws)

    def _fmt_hours(self, h: float) -> str:
        """فرمت ساعات اعشاری به HH:MM با دقت دقیقه."""
        if h is None:
            return '00:00'
        total_minutes = int(round(float(h) * 60))
        sign = '-' if total_minutes < 0 else ''
        total_minutes = abs(total_minutes)
        hours = total_minutes // 60
        minutes = total_minutes % 60
        return f"{sign}{hours:02d}:{minutes:02d}"

    def _auto_adjust_column_width(self, ws, max_width: int = 25):
        """تنظیم خودکار عرض ستون‌ها"""
        for col_idx in range(1, ws.max_column + 1):
            column_letter = get_column_letter(col_idx)
            max_length = 0

            for row in range(1, ws.max_row + 1):
                cell = ws.cell(row=row, column=col_idx)
                if cell.value is not None:
                    try:
                        cell_len = len(str(cell.value))
                        if cell_len > max_length:
                            max_length = cell_len
                    except:
                        pass

            adjusted_width = min(max_length + 2, max_width)
            ws.column_dimensions[column_letter].width = max(adjusted_width, 12)