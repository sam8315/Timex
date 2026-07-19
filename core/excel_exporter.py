"""
ماژول خروجی اکسل
"""
from datetime import date
from typing import List, Dict
from pathlib import Path
import jdatetime
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side


class ExcelExporter:
    """تولید فایل‌های اکسل"""

    def __init__(self, output_dir: str = "exports"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(exist_ok=True)

    def _apply_header_style(self, ws, row_num: int):
        """اعمال استایل هدر"""
        header_fill = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")
        header_font = Font(bold=True, color="FFFFFF", size=11)

        for cell in ws[row_num]:
            cell.fill = header_fill
            cell.font = header_font
            cell.alignment = Alignment(horizontal='center', vertical='center')

    def _apply_borders(self, ws):
        """اعمال حاشیه به تمام سلول‌ها"""
        thin_border = Border(
            left=Side(style='thin'),
            right=Side(style='thin'),
            top=Side(style='thin'),
            bottom=Side(style='thin')
        )
        for row in ws.iter_rows():
            for cell in row:
                cell.border = thin_border

    def export_monthly_report(
            self,
            reports: List[Dict],
            year: int,
            month: int
    ) -> str:
        """خروجی گزارش ماهانه به اکسل"""
        wb = Workbook()
        ws = wb.active
        ws.title = f"گزارش {year}-{month:02d}"

        # هدر
        j_month_name = self._get_jalali_month_name(month)
        ws.append([f"گزارش ماهانه {j_month_name} {year}"])
        ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=14)
        ws['A1'].font = Font(bold=True, size=14)
        ws['A1'].alignment = Alignment(horizontal='center')

        # زیر هدر
        ws.append([])
        headers = [
            'ردیف', 'کد پرسنلی', 'نام', 'گروه',
            'حاضر', 'غایب', 'تعطیل', 'استحقاقی',
            'استعلاجی', 'تشویقی', 'بدون حقوق', 'ماموریت',
            'حضور کم', 'ویژه', 'ساعت کار', 'ساعت شب‌کاری'
        ]
        ws.append(headers)
        self._apply_header_style(ws, 3)

        # داده‌ها
        for i, r in enumerate(reports, 1):
            ws.append([
                i,
                r['user_id'],
                r['name'],
                r['group_id'] or '-',
                r['present_days'],
                r['absent_days'],
                r['holiday_days'],
                r['annual_leave'],
                r['sick_leave'],
                r['reward_leave'],
                r['unpaid_leave'],
                r['mission_days'],
                r['late_days'],
                r['special_days'],
                f"{int(r['work_hours'])}:{int((r['work_hours'] % 1) * 60):02d}",
                f"{int(r['night_hours'])}:{int((r['night_hours'] % 1) * 60):02d}"
            ])

        # تنظیم عرض ستون‌ها
        for column in ws.columns:
            max_length = 0
            column_letter = column[0].column_letter
            for cell in column:
                try:
                    if len(str(cell.value)) > max_length:
                        max_length = len(str(cell.value))
                except:
                    pass
            ws.column_dimensions[column_letter].width = max(max_length + 2, 12)

        self._apply_borders(ws)

        # ذخیره
        j_date = jdatetime.date.today()
        filename = self.output_dir / f"monthly_report_{year}_{month:02d}_{j_date.strftime('%Y%m%d')}.xlsx"
        wb.save(filename)
        return str(filename)

    def export_absent_report(
            self,
            reports: List[Dict],
            from_date: date,
            to_date: date
    ) -> str:
        """خروجی گزارش غیبت‌ها به اکسل"""
        wb = Workbook()
        ws = wb.active
        ws.title = "گزارش غیبت"

        j_from = jdatetime.date.fromgregorian(date=from_date)
        j_to = jdatetime.date.fromgregorian(date=to_date)

        ws.append([f"گزارش غیبت‌ها از {j_from.strftime('%Y/%m/%d')} تا {j_to.strftime('%Y/%m/%d')}"])
        ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=4)
        ws['A1'].font = Font(bold=True, size=14)
        ws['A1'].alignment = Alignment(horizontal='center')

        ws.append([])
        headers = ['ردیف', 'کد پرسنلی', 'نام', 'تعداد غیبت', 'تاریخ‌های غیبت']
        ws.append(headers)
        self._apply_header_style(ws, 3)

        for i, r in enumerate(reports, 1):
            dates_str = ', '.join([
                jdatetime.date.fromgregorian(date=d).strftime('%Y/%m/%d')
                for d in r['absent_dates']
            ])
            ws.append([i, r['user_id'], r['name'], r['absent_count'], dates_str])

        for column in ws.columns:
            max_length = max(len(str(cell.value or '')) for cell in column)
            ws.column_dimensions[column[0].column_letter].width = max(max_length + 2, 12)

        self._apply_borders(ws)

        j_date = jdatetime.date.today()
        filename = self.output_dir / f"absent_report_{j_date.strftime('%Y%m%d')}.xlsx"
        wb.save(filename)
        return str(filename)

    def export_leave_report(
            self,
            reports: List[Dict],
            year: int,
            month: int = None
    ) -> str:
        """خروجی گزارش مرخصی‌ها به اکسل"""
        wb = Workbook()
        ws = wb.active

        title = f"گزارش مرخصی‌های سال {year}"
        if month:
            title = f"گزارش مرخصی‌های {self._get_jalali_month_name(month)} {year}"

        ws.title = title
        ws.append([title])
        ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=8)
        ws['A1'].font = Font(bold=True, size=14)
        ws['A1'].alignment = Alignment(horizontal='center')

        ws.append([])
        headers = ['ردیف', 'کد پرسنلی', 'نام', 'استحقاقی', 'استعلاجی', 'تشویقی', 'بدون حقوق', 'مجموع روز',
                   'تعداد درخواست']
        ws.append(headers)
        self._apply_header_style(ws, 3)

        for i, r in enumerate(reports, 1):
            ws.append([
                i, r['user_id'], r['name'],
                r['annual_leave'], r['sick_leave'],
                r['reward_leave'], r['unpaid_leave'],
                r['total_days'], r['total_requests']
            ])

        for column in ws.columns:
            max_length = max(len(str(cell.value or '')) for cell in column)
            ws.column_dimensions[column[0].column_letter].width = max(max_length + 2, 12)

        self._apply_borders(ws)

        j_date = jdatetime.date.today()
        suffix = f"_{month:02d}" if month else ""
        filename = self.output_dir / f"leave_report_{year}{suffix}_{j_date.strftime('%Y%m%d')}.xlsx"
        wb.save(filename)
        return str(filename)

    def _get_jalali_month_name(self, month: int) -> str:
        """دریافت نام ماه شمسی"""
        names = {
            1: 'فروردین', 2: 'اردیبهشت', 3: 'خرداد',
            4: 'تیر', 5: 'مرداد', 6: 'شهریور',
            7: 'مهر', 8: 'آبان', 9: 'آذر',
            10: 'دی', 11: 'بهمن', 12: 'اسفند'
        }
        return names.get(month, '')