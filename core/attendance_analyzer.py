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
                func.date(Attendance.timestamp) <= to_date
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
                func.date(Attendance.timestamp) <= to_date
            )
        ).count()

        # تعداد ورود و خروج
        enter_count = self.db.query(Attendance).filter(
            and_(
                Attendance.punch == 0,
                func.date(Attendance.timestamp) >= from_date,
                func.date(Attendance.timestamp) <= to_date
            )
        ).count()

        exit_count = self.db.query(Attendance).filter(
            and_(
                Attendance.punch == 1,
                func.date(Attendance.timestamp) >= from_date,
                func.date(Attendance.timestamp) <= to_date
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

    def get_user_attendance_range(
            self,
            user_id: str,
            from_date: date,
            to_date: date
    ) -> Dict:
        """
        دریافت جزئیات تردد یک کاربر در یک بازه زمانی
        با نمایش تمام ورودها و خروج‌ها
        """
        user = self.db.query(User).filter(User.user_id == user_id).first()
        if not user:
            return {'error': 'کاربر یافت نشد'}

        # دریافت تمام رکوردها در بازه زمانی
        all_records = self.db.query(Attendance).filter(
            and_(
                Attendance.user_id == user_id,
                func.date(Attendance.timestamp) >= from_date,
                func.date(Attendance.timestamp) <= to_date
            )
        ).order_by(Attendance.timestamp).all()

        # گروه‌بندی بر اساس روز
        days_dict = {}
        for record in all_records:
            day = record.timestamp.date()
            if day not in days_dict:
                days_dict[day] = []
            days_dict[day].append(record)

        # پردازش هر روز
        days = []
        for day_date in sorted(days_dict.keys(), reverse=True):
            day_records = days_dict[day_date]

            # مرتب‌سازی بر اساس زمان
            day_records.sort(key=lambda r: r.timestamp)

            # شمارش ورود و خروج
            enters = [r for r in day_records if r.punch == 0]
            exits = [r for r in day_records if r.punch == 1]

            enter_count = len(enters)
            exit_count = len(exits)

            # اولین ورود و آخرین خروج
            first_enter = enters[0].timestamp if enters else None
            last_exit = exits[-1].timestamp if exits else None

            # بررسی کامل بودن
            is_complete = enter_count > 0 and exit_count > 0 and enter_count == exit_count

            # محاسبه ساعات کاری
            work_hours = None
            if first_enter and last_exit:
                delta = last_exit - first_enter
                work_hours = delta.total_seconds() / 3600

            # بررسی صحت ترتیب
            sequence_check = self._check_sequence_validity(day_records)

            # ✅ ذخیره تمام رکوردها برای نمایش
            all_times = [
                {
                    'timestamp': r.timestamp,
                    'punch': r.punch,
                    'punch_name': 'ورود' if r.punch == 0 else 'خروج'
                }
                for r in day_records
            ]

            days.append({
                'date': day_date,
                'first_enter': first_enter,
                'last_exit': last_exit,
                'enter_count': enter_count,
                'exit_count': exit_count,
                'is_complete': is_complete,
                'work_hours': work_hours,
                'has_sequence_error': not sequence_check['is_valid'],
                'sequence_errors': sequence_check['errors'],
                'all_records': all_times  # 🆕 تمام رکوردها
            })

        # محاسبه آمار کلی
        total_days = len(days)
        complete_days = sum(1 for d in days if d['is_complete'])
        incomplete_days = total_days - complete_days
        sequence_error_days = sum(1 for d in days if d['has_sequence_error'])
        total_work_hours = sum(d['work_hours'] or 0 for d in days)

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
                'total_work_hours': total_work_hours
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
                status=status
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
        حذف یک رکورد تردد بر اساس شناسه
        """
        try:
            record = self.db.query(Attendance).filter(Attendance.id == record_id).first()
            if not record:
                return {'success': False, 'message': '❌ رکورد یافت نشد'}

            # ذخیره اطلاعات برای گزارش
            info = {
                'user_id': record.user_id,
                'timestamp': record.timestamp,
                'punch': record.punch
            }

            self.db.delete(record)
            self.db.commit()

            return {
                'success': True,
                'message': f'✅ رکورد حذف شد (کاربر: {info["user_id"]}, زمان: {info["timestamp"]})'
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
            if prev_punch is not None and record.punch == prev_punch:
                # دو ورود یا دو خروج متوالی
                punch_name = "ورود" if record.punch == 0 else "خروج"
                errors.append({
                    'index': i,
                    'record_id': record.id,
                    'timestamp': record.timestamp,
                    'punch': record.punch,
                    'message': f'❌ دو {punch_name} متوالی'
                })

            prev_punch = record.punch

        return {
            'is_valid': len(errors) == 0,
            'errors': errors
        }