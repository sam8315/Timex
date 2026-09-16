"""
ماژول تحلیل و بررسی ترددهای ناقص
"""
from datetime import datetime, date
from typing import List, Dict, Optional
from sqlalchemy import func, and_, case
from sqlalchemy.orm import Session
from jdatetime import date as jdate

from database.engine import SessionLocal
from models.user import User
from models.attendance import Attendance

from datetime import datetime, timedelta, date


def calculate_night_hours(start_time: datetime, end_time: datetime) -> float:
    """
    محاسبه ساعات شب‌کاری (بین ۲۲:۰۰ تا ۰۶:۰۰ صبح)
    """
    if not start_time or not end_time or start_time >= end_time:
        return 0.0

    night_hours = 0.0
    current = start_time

    while current < end_time:
        # تعیین شروع بازه شب برای روز جاری
        if current.hour < 6:
            # اگر ساعت فعلی بین ۰۰:۰۰ تا ۰۵:۵۹ است، شب از ۲۲:۰۰ روز قبل شروع شده
            night_start = (current - timedelta(days=1)).replace(hour=22, minute=0, second=0, microsecond=0)
        else:
            night_start = current.replace(hour=22, minute=0, second=0, microsecond=0)

        night_end = night_start + timedelta(hours=8)  # ۰۶:۰۰ صبح روز بعد

        # محاسبه اشتراک بازه شیفت با بازه شب
        intersect_start = max(current, night_start)
        intersect_end = min(end_time, night_end)

        if intersect_start < intersect_end:
            delta = intersect_end - intersect_start
            night_hours += delta.total_seconds() / 3600.0

        # حرکت به پایان این بازه شب برای بررسی روز بعد (جلوگیری از حلقه بی‌نهایت)
        current = night_end

    return round(night_hours, 2)

class AttendanceAnalyzer:
    """تحلیل‌گر ترددها برای شناسایی موارد ناقص"""

    def __init__(self):
        self.db: Session = SessionLocal()

    def close(self):
        """بستن اتصال دیتابیس"""
        if self.db:
            self.db.close()

    def get_incomplete_attendances(
        self,
        from_date: Optional[date] = None,
        to_date: Optional[date] = None
    ) -> List[Dict]:
        """
        شناسایی ترددهای ناقص (ورود بدون خروج یا خروج بدون ورود)

        Returns:
            List[Dict]: لیست ترددهای ناقص با اطلاعات کاربر و تاریخ
        """
        # اگر تاریخ مشخص نشده، 30 روز اخیر
        if not to_date:
            to_date = date.today()
        if not from_date:
            from_date = date(to_date.year, to_date.month, 1)

        # کوئری: برای هر کاربر در هر روز، تعداد ورود و خروج را بشمار
        query = self.db.query(
            User.user_id,
            User.name,
            func.date(Attendance.timestamp).label('attendance_date'),
            func.sum(case((Attendance.punch == 0, 1), else_=0)).label('enter_count'),
            func.sum(case((Attendance.punch == 1, 1), else_=0)).label('exit_count'),
            func.min(case((Attendance.punch == 0, Attendance.timestamp))).label('first_enter'),
            func.max(case((Attendance.punch == 1, Attendance.timestamp))).label('last_exit')
        ).join(
            User, Attendance.user_id == User.user_id
        ).filter(
            and_(
                func.date(Attendance.timestamp) >= from_date,
                func.date(Attendance.timestamp) <= to_date,
                Attendance.is_deleted == False  # ✅ فیلتر جدید
            )
        ).group_by(
            User.user_id,
            User.name,
            func.date(Attendance.timestamp)
        ).order_by(
            func.date(Attendance.timestamp).desc(),
            User.name
        )

        results = []
        for row in query:
            # شناسایی موارد ناقص
            if row.enter_count == 0 and row.exit_count > 0:
                # فقط خروج دارد (ورود فراموش شده)
                results.append({
                    'user_id': row.user_id,
                    'name': row.name,
                    'date': row.attendance_date,
                    'type': '❌ خروج بدون ورود',
                    'enter_count': row.enter_count,
                    'exit_count': row.exit_count,
                    'first_enter': None,
                    'last_exit': row.last_exit,
                    'issue': 'missing_enter'
                })
            elif row.enter_count > 0 and row.exit_count == 0:
                # فقط ورود دارد (خروج فراموش شده)
                results.append({
                    'user_id': row.user_id,
                    'name': row.name,
                    'date': row.attendance_date,
                    'type': '⚠️  ورود بدون خروج',
                    'enter_count': row.enter_count,
                    'exit_count': row.exit_count,
                    'first_enter': row.first_enter,
                    'last_exit': None,
                    'issue': 'missing_exit'
                })
            elif row.enter_count != row.exit_count:
                # عدم تعادل بین ورود و خروج
                results.append({
                    'user_id': row.user_id,
                    'name': row.name,
                    'date': row.attendance_date,
                    'type': '🔄 عدم تعادل ورود/خروج',
                    'enter_count': row.enter_count,
                    'exit_count': row.exit_count,
                    'first_enter': row.first_enter,
                    'last_exit': row.last_exit,
                    'issue': 'imbalance'
                })

        return results

    def get_summary_statistics(self, from_date: Optional[date] = None, to_date: Optional[date] = None) -> Dict:
        """
        دریافت آمار کلی ترددها در بازه زمانی
        """
        if not to_date:
            to_date = date.today()

        today_jalali = jdate.fromgregorian(date=to_date)
        first_day_jalali = jdate(today_jalali.year, today_jalali.month, 1)
        if not from_date:
            # from_date = date(to_date.year, to_date.month, 1)
            from_date = first_day_jalali.togregorian()

        # کل رکوردها
        total_records = self.db.query(Attendance).filter(
            and_(
                func.date(Attendance.timestamp) >= from_date,
                func.date(Attendance.timestamp) <= to_date,
                Attendance.is_deleted == False
            )
        ).count()

        # تعداد ورود و خروج
        enter_count = self.db.query(Attendance).filter(
            and_(
                Attendance.punch == 0,
                func.date(Attendance.timestamp) >= from_date,
                func.date(Attendance.timestamp) <= to_date,
                Attendance.is_deleted == False
            )
        ).count()

        exit_count = self.db.query(Attendance).filter(
            and_(
                Attendance.punch == 1,
                func.date(Attendance.timestamp) >= from_date,
                func.date(Attendance.timestamp) <= to_date,
                Attendance.is_deleted == False
            )
        ).count()

        # تعداد کاربران منحصر به فرد
        unique_users = self.db.query(func.count(func.distinct(Attendance.user_id))).filter(
            and_(
                func.date(Attendance.timestamp) >= from_date,
                func.date(Attendance.timestamp) <= to_date
            )
        ).scalar()

        # تعداد ترددهای ناقص
        incomplete = self.get_incomplete_attendances(from_date, to_date)

        return {
            'total_records': total_records,
            'enter_count': enter_count,
            'exit_count': exit_count,
            'unique_users': unique_users,
            'incomplete_count': len(incomplete),
            'from_date': from_date,
            'to_date': to_date
        }

    def get_user_attendance_range(self, user_id: str, from_date: date, to_date: date) -> Dict:
        """
        دریافت جزئیات تردد با جفت‌کردن ورود/خروج و محاسبه شب‌کاری
        """
        user = self.db.query(User).filter(User.user_id == user_id).first()
        if not user:
            return {'error': 'کاربر یافت نشد'}

        # دریافت تمام رکوردها مرتب شده بر اساس زمان
        records = self.db.query(Attendance).filter(
            and_(
                Attendance.user_id == user_id,
                func.date(Attendance.timestamp) >= from_date,
                func.date(Attendance.timestamp) <= to_date,
                Attendance.is_deleted == False
            )
        ).order_by(Attendance.timestamp).all()

        # --- منطق جفت‌کردن (Pairing) ---
        shifts = []
        pending_in = None
        current_day_records = []

        for record in records:
            current_day_records.append(record)

            if record.punch == 0:  # ورود
                if pending_in is not None:
                    # ورود قبلی بدون خروج مانده بود (خطای ترتیب)
                    shifts.append({
                        'in_record': pending_in,
                        'out_record': None,
                        'date': pending_in.timestamp.date(),
                        'records': current_day_records[:-1],
                        'error': 'consecutive_in'
                    })
                pending_in = record
                current_day_records = [record]  # شروع روز جدید برای این شیفت

            elif record.punch == 1:  # خروج
                if pending_in is not None:
                    # جفت کامل شد
                    shifts.append({
                        'in_record': pending_in,
                        'out_record': record,
                        'date': pending_in.timestamp.date(),  # تاریخ شیفت بر اساس روز ورود است
                        'records': current_day_records,
                        'error': None
                    })
                    pending_in = None
                    current_day_records = []
                else:
                    # خروج بدون ورود
                    shifts.append({
                        'in_record': None,
                        'out_record': record,
                        'date': record.timestamp.date(),
                        'records': current_day_records,
                        'error': 'exit_without_in'
                    })

        # اگر در پایان بازه، ورودی بدون خروج باقی مانده باشد
        if pending_in is not None:
            shifts.append({
                'in_record': pending_in,
                'out_record': None,
                'date': pending_in.timestamp.date(),
                'records': current_day_records,
                'error': 'missing_exit'
            })

        # --- پردازش شیفت‌ها و گروه‌بندی بر اساس روز ---
        days_dict = {}
        for shift in shifts:
            day = shift['date']
            if day not in days_dict:
                days_dict[day] = {'shifts': [], 'errors': []}

            days_dict[day]['shifts'].append(shift)
            if shift['error']:
                days_dict[day]['errors'].append(shift)

        # ساخت خروجی نهایی
        days = []
        for day_date in sorted(days_dict.keys(), reverse=True):
            day_data = days_dict[day_date]
            day_shifts = day_data['shifts']

            first_enter = None
            last_exit = None
            total_work_hours = 0.0
            total_night_hours = 0.0
            enter_count = 0
            exit_count = 0
            all_records = []
            has_sequence_error = len(day_data['errors']) > 0

            for shift in day_shifts:
                if shift['in_record']:
                    enter_count += 1
                    if first_enter is None or shift['in_record'].timestamp < first_enter:
                        first_enter = shift['in_record'].timestamp

                if shift['out_record']:
                    exit_count += 1
                    if last_exit is None or shift['out_record'].timestamp > last_exit:
                        last_exit = shift['out_record'].timestamp

                # محاسبه ساعات کار و شب‌کاری برای شیفت‌های کامل
                if shift['in_record'] and shift['out_record']:
                    delta = shift['out_record'].timestamp - shift['in_record'].timestamp
                    total_work_hours += delta.total_seconds() / 3600.0

                    night_h = calculate_night_hours(shift['in_record'].timestamp, shift['out_record'].timestamp)
                    total_night_hours += night_h

                all_records.extend(shift['records'])

            # مرتب‌سازی رکوردها برای نمایش
            all_records.sort(key=lambda r: r.timestamp)
            all_records_display = [
                {
                    'timestamp': r.timestamp,
                    'punch': r.punch,
                    'punch_name': 'ورود' if r.punch == 0 else 'خروج',
                    'source': r.source
                }
                for r in all_records
            ]

            is_complete = (enter_count > 0 and exit_count > 0 and enter_count == exit_count and not has_sequence_error)

            # ✅ ساخت sequence_errors با ساختار صحیح
            sequence_errors_list = []
            for shift in day_data['errors']:
                error_record = shift['in_record'] if shift['in_record'] else shift['out_record']
                error_type = shift['error']

                # تبدیل نوع خطا به پیام خوانا
                if error_type == 'consecutive_in':
                    message = '❌ دو ورود متوالی'
                    error_type_display = 'consecutive'
                elif error_type == 'exit_without_in':
                    message = '❌ خروج قبل از ورود'
                    error_type_display = 'exit_before_enter'
                elif error_type == 'missing_exit':
                    message = '⚠️ ورود بدون خروج'
                    error_type_display = 'missing_exit'
                else:
                    message = f'⚠️ خطای نامشخص: {error_type}'
                    error_type_display = 'unknown'

                sequence_errors_list.append({
                    'index': 0,
                    'record_id': error_record.id if error_record else None,
                    'timestamp': error_record.timestamp if error_record else None,
                    'punch': error_record.punch if error_record else None,
                    'error_type': error_type_display,
                    'message': message
                })

            days.append({
                'date': day_date,
                'first_enter': first_enter,
                'last_exit': last_exit,
                'enter_count': enter_count,
                'exit_count': exit_count,
                'is_complete': is_complete,
                'work_hours': round(total_work_hours, 2) if total_work_hours > 0 else None,
                'night_hours': round(total_night_hours, 2) if total_night_hours > 0 else None,
                'has_sequence_error': has_sequence_error,
                'sequence_errors': sequence_errors_list,
                'all_records': all_records_display
            })
        # آمار کلی
        total_days = len(days)
        complete_days = sum(1 for d in days if d['is_complete'])
        incomplete_days = total_days - complete_days
        sequence_error_days = sum(1 for d in days if d['has_sequence_error'])
        total_work = sum(d['work_hours'] or 0 for d in days)
        total_night = sum(d['night_hours'] or 0 for d in days)

        return {
            'user': {'user_id': user.user_id, 'name': user.name},
            'from_date': from_date,
            'to_date': to_date,
            'days': days,
            'summary': {
                'total_days': total_days,
                'complete_days': complete_days,
                'incomplete_days': incomplete_days,
                'sequence_error_days': sequence_error_days,
                'total_work_hours': round(total_work, 2),
                'total_night_hours': round(total_night, 2)
            }
        }
    def get_attendance_records_by_date(self, user_id: str, target_date: date) -> List[Dict]:
        """
        دریافت تمام رکوردهای یک کاربر در یک روز خاص (با شناسه)
        """
        records = self.db.query(Attendance).filter(
            and_(
                Attendance.user_id == user_id,
                func.date(Attendance.timestamp) == target_date
            )
        ).order_by(Attendance.timestamp).all()

        return [
            {
                'id': r.id,
                'timestamp': r.timestamp,
                'punch': r.punch,
                'status': r.status,
                'punch_name': 'ورود' if r.punch == 0 else 'خروج' if r.punch == 1 else f'نامشخص({r.punch})'
            }
            for r in records
        ]

    def add_attendance_record(
            self,
            user_id: str,
            timestamp: datetime,
            punch: int,
            status: int = 0
    ) -> Dict:
        """
        افزودن یک رکورد تردد جدید

        Args:
            user_id: کد پرسنلی کاربر
            timestamp: زمان تردد
            punch: 0=ورود، 1=خروج
            status: روش احراز هویت (پیش‌فرض: 0=اثر انگشت)

        Returns:
            Dict: نتیجه عملیات
        """
        from sqlalchemy.dialects.postgresql import insert

        # بررسی وجود کاربر
        user = self.db.query(User).filter(User.user_id == user_id).first()
        if not user:
            return {'success': False, 'message': f'کاربر با کد {user_id} یافت نشد'}

        try:
            stmt = insert(Attendance).values(
                user_id=user_id,
                timestamp=timestamp,
                punch=punch,
                status=status,
                source=Attendance.SOURCE_MANUAL  # ✅ منبع: دستی
            ).on_conflict_do_nothing(
                index_elements=['user_id', 'timestamp']
            )

            result = self.db.execute(stmt)
            self.db.commit()

            if result.rowcount > 0:
                return {
                    'success': True,
                    'message': f'✅ رکورد {("ورود" if punch == 0 else "خروج")} با موفقیت اضافه شد'
                }
            else:
                return {
                    'success': False,
                    'message': '⚠️  رکورد تکراری است (این کاربر در این زمان قبلاً تردد ثبت کرده)'
                }

        except Exception as e:
            self.db.rollback()
            return {'success': False, 'message': f'❌ خطا: {e}'}

    def delete_attendance_record(self, record_id: int) -> Dict:
        """
        حذف منطقی یک رکورد تردد (Soft Delete)
        """
        try:
            record = self.db.query(Attendance).filter(Attendance.id == record_id).first()
            if not record:
                return {'success': False, 'message': '❌ رکورد یافت نشد'}

            if record.is_deleted:
                return {'success': False, 'message': '⚠️  این رکورد قبلاً حذف شده است'}

            # ✅ به جای حذف واقعی، فقط is_deleted را True می‌کنیم
            record.is_deleted = True
            self.db.commit()

            info = {
                'user_id': record.user_id,
                'timestamp': record.timestamp,
                'punch': record.punch
            }

            return {
                'success': True,
                'message': f'✅ رکورد به صورت منطقی حذف شد (کاربر: {info["user_id"]}, زمان: {info["timestamp"]})'
            }

        except Exception as e:
            self.db.rollback()
            return {'success': False, 'message': f'❌ خطا در حذف: {e}'}

    def update_attendance_punch(self, record_id: int, new_punch: int) -> Dict:
        """
        تغییر وضعیت (punch) یک رکورد تردد
        """
        if new_punch not in [0, 1]:
            return {'success': False, 'message': '❌ مقدار punch باید 0 (ورود) یا 1 (خروج) باشد'}

        try:
            record = self.db.query(Attendance).filter(Attendance.id == record_id).first()
            if not record:
                return {'success': False, 'message': '❌ رکورد یافت نشد'}

            old_punch = record.punch
            record.punch = new_punch
            self.db.commit()

            old_name = 'ورود' if old_punch == 0 else 'خروج'
            new_name = 'ورود' if new_punch == 0 else 'خروج'

            return {
                'success': True,
                'message': f'✅ وضعیت تغییر کرد: {old_name} → {new_name}'
            }

        except Exception as e:
            self.db.rollback()
            return {'success': False, 'message': f'❌ خطا در تغییر: {e}'}

    def _check_sequence_validity(self, records: List[Attendance]) -> Dict:
        """
        بررسی صحت ترتیب ورود و خروج

        قوانین:
        1. دو ورود متوالی ممنوع
        2. دو خروج متوالی ممنوع
        3. اولین رکورد روز نمی‌تواند خروج باشد (مگر ادامه از روز قبل)
        4. بعد از هر ورود، باید خروج باشد (و برعکس)

        Returns:
            Dict: شامل وضعیت صحت و جزئیات خطا
        """
        if not records:
            return {'is_valid': True, 'errors': []}

        # مرتب‌سازی بر اساس زمان
        sorted_records = sorted(records, key=lambda r: r.timestamp)

        errors = []
        prev_punch = None

        for i, record in enumerate(sorted_records):
            current_punch = record.punch
            punch_name = "ورود" if current_punch == 0 else "خروج"

            # قانون 1 و 2: دو ورود یا دو خروج متوالی
            if prev_punch is not None and current_punch == prev_punch:
                errors.append({
                    'index': i,
                    'record_id': record.id,
                    'timestamp': record.timestamp,
                    'punch': current_punch,
                    'error_type': 'consecutive',
                    'message': f'❌ دو {punch_name} متوالی'
                })

            # قانون 3: اولین رکورد نمی‌تواند خروج باشد
            # (مگر اینکه فقط یک خروج در روز باشد که آن هم مشکوک است)
            if i == 0 and current_punch == 1:
                # اگر فقط یک رکورد در روز باشد و آن خروج باشد → خطا
                # اگر چند رکورد باشد و اولی خروج باشد → باید دومی ورود باشد
                if len(sorted_records) == 1:
                    errors.append({
                        'index': i,
                        'record_id': record.id,
                        'timestamp': record.timestamp,
                        'punch': current_punch,
                        'error_type': 'exit_before_enter',
                        'message': f'❌ خروج بدون ورود قبلی'
                    })
                elif len(sorted_records) > 1 and sorted_records[1].punch != 0:
                    errors.append({
                        'index': i,
                        'record_id': record.id,
                        'timestamp': record.timestamp,
                        'punch': current_punch,
                        'error_type': 'exit_before_enter',
                        'message': f'❌ خروج قبل از ورود'
                    })

            prev_punch = current_punch

        return {
            'is_valid': len(errors) == 0,
            'errors': errors
        }

    def restore_attendance_record(self, record_id: int) -> Dict:
        """
        بازیابی یک رکورد حذف شده (Undo Soft Delete)
        """

        try:
            record = self.db.query(Attendance).filter(Attendance.id == record_id).first()
            if not record:
                return {'success': False, 'message': '❌ رکورد یافت نشد'}

            if not record.is_deleted:
                return {'success': False, 'message': '⚠️  این رکورد حذف نشده است'}

            record.is_deleted = False
            self.db.commit()

            return {
                'success': True,
                'message': f'✅ رکورد با موفقیت بازیابی شد'
            }

        except Exception as e:
            self.db.rollback()
            return {'success': False, 'message': f'❌ خطا در بازیابی: {e}'}

