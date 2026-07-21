"""
خروجی PDF گزارش تفصیلی ماهانه
"""
from datetime import date
from typing import Dict
from pathlib import Path
from fpdf import FPDF
import jdatetime


class DetailedPDFExporter:
    """خروجی PDF گزارش تفصیلی"""

    def __init__(self, output_dir: str = "exports"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(exist_ok=True)

    def export_detailed_report(self, report: Dict) -> str:
        """خروجی گزارش تفصیلی به PDF"""
        pdf = FPDF()
        pdf.add_page()

        # تنظیم فونت فارسی (باید فونت فارسی اضافه شود)
        # برای سادگی از فونت پیش‌فرض استفاده می‌کنیم

        emp = report['employee']
        summary = report['summary']

        # هدر
        pdf.set_font('Helvetica', 'B', 16)
        pdf.cell(0, 10, f"Detailed Monthly Report - {emp['full_name']}", ln=True, align='C')
        pdf.set_font('Helvetica', '', 12)
        pdf.cell(0, 8, f"User ID: {emp['user_id']} | Department: {emp['department']}", ln=True, align='C')
        pdf.cell(0, 8, f"Month: {report['month_name']} {report['year']}", ln=True, align='C')
        pdf.ln(5)

        # جدول روزانه
        pdf.set_font('Helvetica', 'B', 10)
        pdf.cell(0, 8, 'Daily Report', ln=True)
        pdf.ln(2)

        # هدر جدول
        pdf.set_font('Helvetica', 'B', 8)
        headers = ['Date', 'Day', 'Day Status', 'Person Status', 'Enter', 'Exit', 'Work', 'OT']
        col_widths = [25, 20, 20, 25, 15, 15, 15, 15]

        for i, header in enumerate(headers):
            pdf.cell(col_widths[i], 6, header, border=1, align='C')
        pdf.ln()

        # داده‌ها
        pdf.set_font('Helvetica', '', 7)
        for day in report['days']:
            def fmt_time(dt):
                return dt.strftime('%H:%M') if dt else '-'

            def fmt_hours(h):
                if h == 0:
                    return '-'
                hours = int(h)
                minutes = int((h - hours) * 60)
                return f"{hours:02d}:{minutes:02d}"

            pdf.cell(col_widths[0], 5, day['jalali_date'], border=1, align='C')
            pdf.cell(col_widths[1], 5, day['day_name'][:8], border=1, align='C')
            pdf.cell(col_widths[2], 5, 'Holiday' if day['is_day_off'] else 'Work', border=1, align='C')
            pdf.cell(col_widths[3], 5, 'Present' if day['person_status'] == 'P' else 'Other', border=1, align='C')
            pdf.cell(col_widths[4], 5, fmt_time(day['first_enter']), border=1, align='C')
            pdf.cell(col_widths[5], 5, fmt_time(day['last_exit']), border=1, align='C')
            pdf.cell(col_widths[6], 5, fmt_hours(day['work_hours']), border=1, align='C')
            pdf.cell(col_widths[7], 5, fmt_hours(day['overtime']), border=1, align='C')
            pdf.ln()

        pdf.ln(5)

        # خلاصه ماهانه
        pdf.set_font('Helvetica', 'B', 10)
        pdf.cell(0, 8, 'Monthly Summary', ln=True)
        pdf.ln(2)

        pdf.set_font('Helvetica', '', 9)

        # موظفی
        pdf.set_font('Helvetica', 'B', 9)
        pdf.cell(0, 6, 'Duty:', ln=True)
        pdf.set_font('Helvetica', '', 9)
        pdf.cell(0, 5, f"  Duty Days: {summary['duty_days']}", ln=True)
        pdf.cell(0, 5, f"  Duty Hours: {self._fmt_hours(summary['duty_hours'])}", ln=True)

        pdf.ln(2)

        # وضعیت روزها
        pdf.set_font('Helvetica', 'B', 9)
        pdf.cell(0, 6, 'Daily Status:', ln=True)
        pdf.set_font('Helvetica', '', 9)
        pdf.cell(0, 5, f"  Present: {summary['present_days']}", ln=True)
        pdf.cell(0, 5, f"  Leave: {summary['leave_days']}", ln=True)
        pdf.cell(0, 5, f"  Absent: {summary['absent_days']}", ln=True)
        pdf.cell(0, 5, f"  Rest: {summary['rest_days']}", ln=True)
        pdf.cell(0, 5, f"  Friday Work: {summary['friday_work_days']}", ln=True)
        pdf.cell(0, 5, f"  Holiday Work: {summary['holiday_work_days']}", ln=True)

        pdf.ln(2)

        # ساعات کاری
        pdf.set_font('Helvetica', 'B', 9)
        pdf.cell(0, 6, 'Work Hours:', ln=True)
        pdf.set_font('Helvetica', '', 9)
        pdf.cell(0, 5, f"  Total Work: {self._fmt_hours(summary['total_work_hours'])}", ln=True)
        pdf.cell(0, 5, f"  Morning: {self._fmt_hours(summary['total_morning'])}", ln=True)
        pdf.cell(0, 5, f"  Evening: {self._fmt_hours(summary['total_evening'])}", ln=True)
        pdf.cell(0, 5, f"  Night: {self._fmt_hours(summary['total_night'])}", ln=True)

        pdf.ln(2)

        # اضافه کاری
        pdf.set_font('Helvetica', 'B', 9)
        pdf.cell(0, 6, 'Overtime:', ln=True)
        pdf.set_font('Helvetica', '', 9)
        pdf.cell(0, 5, f"  Daily OT: {self._fmt_hours(summary['daily_overtime'])}", ln=True)
        pdf.cell(0, 5, f"  Weekly OT: {self._fmt_hours(summary['weekly_overtime'])}", ln=True)
        pdf.cell(0, 5, f"  Friday Work: {self._fmt_hours(summary['friday_work_hours'])}", ln=True)
        pdf.cell(0, 5, f"  Holiday Work: {self._fmt_hours(summary['holiday_work_hours'])}", ln=True)

        pdf.ln(2)

        # کسری و اضافی
        pdf.set_font('Helvetica', 'B', 9)
        pdf.cell(0, 6, 'Deficit & Surplus:', ln=True)
        pdf.set_font('Helvetica', '', 9)
        pdf.cell(0, 5, f"  Total Deficit: {self._fmt_hours(summary['deficit'])}", ln=True)
        pdf.cell(0, 5, f"  Total Surplus: {self._fmt_hours(summary['surplus'])}", ln=True)

        # ذخیره
        filename = self.output_dir / f"گزارش_تفصیلی_{emp['full_name']}_{report['month_name']}_{report['year']}.pdf"
        pdf.output(filename)
        return str(filename)

    def _fmt_hours(self, h: float) -> str:
        """فرمت ساعات"""
        if h == 0:
            return '00:00'
        hours = int(h)
        minutes = int((h - hours) * 60)
        return f"{hours:02d}:{minutes:02d}"