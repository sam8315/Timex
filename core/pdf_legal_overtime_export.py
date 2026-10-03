"""خروجی PDF گزارش اضافه‌کار قانونی — یک صفحه A4 با خلاصهٔ درشت."""
from typing import Dict, List, Optional

from fpdf import FPDF

from core.pdf_detailed_export_v2 import DetailedPDFExporterV2


class LegalOvertimePDFExporter(DetailedPDFExporterV2):
    """PDF اختصاصی با بلوک پایین‌صفحه: کارکرد / موظفی / اضافه‌کار / جمعه."""

    def export_detailed_report(self, report: Dict, output=None):
        pdf, font_name = self._new_pdf()
        pdf.add_page()
        self._render_employee_page(pdf, report, font_name)
        emp = report['employee']
        filename = (
            f"گزارش_اضافه‌کار_قانونی_{emp['full_name']}_"
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

        filename = (
            f"گزارش_گروهی_اضافه‌کار_{group_label}_{month_name}_{year}.pdf"
        )
        return self._write_output(pdf, output, filename)

    def _render_employee_page(self, pdf: FPDF, report: Dict, font_name: str):
        emp = report['employee']
        summary = report['summary']
        days = report.get('days') or []

        pdf.set_font(font_name, 'B', 13)
        pdf.cell(
            0, 7,
            self._fix_rtl(f"گزارش اضافه‌کار قانونی — {emp['full_name']}"),
            new_x='LMARGIN', new_y='NEXT', align='C',
        )
        pdf.set_font(font_name, '', 9)
        pdf.cell(
            0, 5,
            self._fix_rtl(
                f"کد: {emp['user_id']} | عضویت: "
                f"{emp.get('department_name') or emp.get('department') or '-'} | "
                f"{report['month_name']} {report['year']}"
            ),
            new_x='LMARGIN', new_y='NEXT', align='C',
        )
        pdf.ln(1)

        headers = [
            'تاریخ', 'روز', 'وضعیت روز', 'وضعیت فرد',
            'و۱', 'خ۱', 'و۲', 'خ۲', 'و۳', 'خ۳',
            'وضعیت تردد', 'کارکرد', 'تأخیر', 'تعجیل', 'هفتگی',
        ]
        col_widths = [14, 11, 11, 14, 9, 9, 9, 9, 9, 9, 14, 11, 10, 10, 18]
        page_width = pdf.w - pdf.l_margin - pdf.r_margin
        table_width = sum(col_widths)
        scale = min(1.0, page_width / table_width)
        col_widths = [w * scale for w in col_widths]
        table_width = sum(col_widths)
        start_x = pdf.l_margin + (page_width - table_width)

        row_h = 4.0 if len(days) <= 31 else 3.5
        header_h = 4.6

        pdf.set_font(font_name, 'B', 6.5)
        self._draw_row(
            pdf, start_x, table_width, col_widths, headers, header_h,
            bold_rtl=True,
        )

        pdf.set_font(font_name, '', 6)
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

            week_cell = '-'
            if day.get('week_rowspan') and day.get('week_block'):
                wb = day['week_block']
                week_cell = (
                    f"ک:{self._fmt_hours(wb.get('work_hours') or 0)} "
                    f"م:{self._fmt_hours(wb.get('duty_hours') or 0)} "
                    f"ه:{self._fmt_hours(wb.get('weekly_overtime') or 0)}"
                )
            elif not day.get('week_rowspan'):
                week_cell = ''

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
                week_cell,
            ]
            # ستون هفتگی ممکن است فارسی/مختلط باشد
            ltr_cols = {0, 4, 5, 6, 7, 8, 9, 11, 12, 13}
            self._draw_row(
                pdf, start_x, table_width, col_widths, values, row_h,
                ltr_cols=ltr_cols,
            )

        pdf.ln(3)

        # بلوک پایین — درشت و تفکیک‌شده
        pdf.set_font(font_name, 'B', 11)
        pdf.cell(
            0, 6, self._fix_rtl('خلاصه ماهانه (تفکیک پرداختی)'),
            new_x='LMARGIN', new_y='NEXT', align='C',
        )
        pdf.ln(1)

        box_h = 14
        gap = 1.5
        usable = page_width
        y0 = pdf.get_y()
        # دو ردیف سه‌ستونه تا برچسب‌های بلند جا شوند
        box_rows = [
            [
                (
                    'کل کارکرد',
                    (
                        f"{self._fmt_hours(summary.get('total_work_hours') or 0)}\n"
                        f"{summary.get('total_work_days', 0)} روز"
                    ),
                ),
                (
                    'موظفی',
                    f"{summary.get('duty_days', 0)} روز / "
                    f"{self._fmt_hours(summary.get('duty_hours') or 0)}",
                ),
                (
                    'اضافه‌کار',
                    self._fmt_hours(summary.get('overtime_total') or 0),
                ),
            ],
            [
                (
                    'تعطیل‌کاری',
                    (
                        f"{self._fmt_hours(summary.get('holiday_work_hours') or 0)}\n"
                        f"{summary.get('holiday_work_days', 0)} روز"
                    ),
                ),
                (
                    'مجموع اضافه‌کار و تعطیل‌کاری',
                    self._fmt_hours(summary.get('overtime_holiday_total') or 0),
                ),
                (
                    'جمعه‌کاری',
                    (
                        f"{self._fmt_hours(summary.get('friday_work_hours') or 0)}\n"
                        f"{summary.get('friday_work_days', 0)} روز"
                    ),
                ),
            ],
            [
                (
                    'صبح',
                    (
                        f"{self._fmt_hours(summary.get('total_morning') or 0)}\n"
                        f"{summary.get('morning_percent', 0)}٪"
                    ),
                ),
                (
                    'عصر',
                    (
                        f"{self._fmt_hours(summary.get('total_evening') or 0)}\n"
                        f"{summary.get('evening_percent', 0)}٪"
                    ),
                ),
                (
                    'شب',
                    (
                        f"{self._fmt_hours(summary.get('total_night') or 0)}\n"
                        f"{summary.get('night_percent', 0)}٪"
                    ),
                ),
            ],
        ]

        for row_boxes in box_rows:
            n = len(row_boxes)
            box_w = (usable - (n - 1) * gap) / n
            x = pdf.l_margin
            for title, value in row_boxes:
                pdf.set_xy(x, y0)
                pdf.set_draw_color(100, 116, 139)
                pdf.set_fill_color(241, 245, 249)
                pdf.rect(x, y0, box_w, box_h, style='DF')
                pdf.set_xy(x, y0 + 1.5)
                pdf.set_font(font_name, 'B', 7)
                pdf.cell(box_w, 4, self._fix_rtl(title), align='C')
                pdf.set_xy(x, y0 + 6)
                pdf.set_font(font_name, 'B', 9)
                for i, line in enumerate(str(value).split('\n')[:2]):
                    pdf.set_xy(x, y0 + 6 + i * 3.5)
                    if any('\u0600' <= c <= '\u06FF' for c in line):
                        text = self._fix_rtl(line)
                    else:
                        text = line
                    pdf.cell(box_w, 3.5, text, align='C')
                x += box_w + gap
            y0 += box_h + gap

        pdf.set_y(y0 + 1)
        pdf.set_font(font_name, '', 7.5)
        meta = (
            f"حضور {summary.get('present_days', 0)} | "
            f"مرخصی {summary.get('leave_days', 0)} | "
            f"مرخصی‌ساعتی {self._fmt_hours(summary.get('hourly_leave_hours') or 0)} | "
            f"مأموریت {summary.get('mission_days', 0)} | "
            f"مأموریت‌ساعتی {self._fmt_hours(summary.get('hourly_mission_hours') or 0)} | "
            f"عدم‌حضور {summary.get('absent_days', 0)} | "
            f"استراحت {summary.get('rest_days', 0)} | "
            f"تعطیل {summary.get('holiday_days', 0)} | "
            f"تعطیل‌کاری {self._fmt_hours(summary.get('holiday_work_hours') or 0)} | "
            f"کسرکار {self._fmt_hours(summary.get('monthly_deficit') or 0)} | "
            f"تأخیر {self._fmt_hours(summary.get('total_late_violation') or 0)} | "
            f"تعجیل {self._fmt_hours(summary.get('total_early_leave_violation') or 0)}"
        )
        pdf.cell(
            0, 4.5, self._fix_rtl(meta),
            new_x='LMARGIN', new_y='NEXT', align='C',
        )
