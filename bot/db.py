"""
عملیات دیتابیس ربات بله
"""
from datetime import date, timedelta
from sqlalchemy import and_, func
from sqlalchemy.orm import Session

from models.user import User
from models.employee import Employee
from models.attendance import Attendance
from models.employee_phone import EmployeePhone
from models.bale_user import BaleUser


def normalize_phone(phone: str) -> str:
    """نرمال‌سازی شماره موبایل ایرانی به فرمت 09121234567"""
    if not phone:
        return ""
    # حذف کاراکترهای اضافی
    phone = phone.replace('+', '').replace(' ', '').replace('-', '').replace('(', '').replace(')', '')

    if phone.startswith('0098'):
        phone = '0' + phone[4:]
    elif phone.startswith('98') and len(phone) == 12:
        phone = '0' + phone[2:]
    elif not phone.startswith('0') and len(phone) == 10:
        phone = '0' + phone

    return phone


def find_user_by_phone(db: Session, phone: str):
    """یافتن کاربر بر اساس شماره موبایل"""
    normalized = normalize_phone(phone)

    # جستجوی دقیق
    phone_record = db.query(EmployeePhone).filter(
        EmployeePhone.phone_number == normalized
    ).first()

    if phone_record:
        return phone_record.user_id

    # جستجوی انعطاف‌پذیر (نرمال‌سازی سمت دیتابیس)
    all_phones = db.query(EmployeePhone).all()
    for p in all_phones:
        if normalize_phone(p.phone_number) == normalized:
            return p.user_id

    return None


def get_bale_user(db: Session, chat_id):
    """دریافت کاربر بله بر اساس chat_id"""
    return db.query(BaleUser).filter(
        and_(BaleUser.chat_id == str(chat_id), BaleUser.is_active == True)
    ).first()


def register_bale_user(db: Session, chat_id, user_id: str, phone: str):
    """ثبت یا به‌روزرسانی کاربر بله"""
    existing = db.query(BaleUser).filter(BaleUser.chat_id == str(chat_id)).first()

    if existing:
        existing.user_id = user_id
        existing.phone_number = normalize_phone(phone)
        existing.is_active = True
    else:
        new_user = BaleUser(
            chat_id=str(chat_id),
            user_id=user_id,
            phone_number=normalize_phone(phone),
            is_active=True
        )
        db.add(new_user)

    db.commit()


def get_employee_name(db: Session, user_id: str) -> str:
    """دریافت نام کامل کارمند"""
    employee = db.query(Employee).filter(Employee.user_id == user_id).first()
    if employee:
        return employee.full_name
    return "نامشخص"


def get_attendance_records(db: Session, user_id: str, target_date: date) -> list:
    """دریافت رکوردهای تردد یک روز"""
    records = db.query(Attendance).filter(
        and_(
            Attendance.user_id == user_id,
            func.date(Attendance.timestamp) == target_date,
            Attendance.is_deleted == False
        )
    ).order_by(Attendance.timestamp).all()

    return records


def get_leave_balances(db: Session, user_id: str, year: int) -> dict:
    """🆕 دریافت مانده مرخصی کاربر برای یک سال"""
    from models.leave_balance import LeaveBalance

    balances = db.query(LeaveBalance).filter(
        and_(
            LeaveBalance.user_id == user_id,
            LeaveBalance.year == year
        )
    ).all()

    result = {
        'AL': 0,  # استحقاقی
        'SL': 0,  # استعلاجی
        'RL': 0,  # تشویقی
        'CW': 0,  # ذخیره سال قبل
    }

    for b in balances:
        if b.leave_type in result:
            result[b.leave_type] = b.balance

    return result