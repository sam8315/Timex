"""
سرویس انتقال مرخصی استفاده نشده به سال بعد
"""
from datetime import datetime
from sqlalchemy.orm import Session
from sqlalchemy import and_
import jdatetime

from models.leave_balance import LeaveBalance
from models.leave_transaction import LeaveTransaction
from models.leave_carry_forward_request import LeaveCarryForwardRequest


def get_unused_leave_from_previous_year(db: Session, user_id: str) -> dict:
    """
    بررسی مرخصی استفاده نشده از سال قبل

    Returns:
        dict: {'AL': مقدار, 'SL': مقدار} - فقط مرخصی‌هایی که مانده > 0 دارند
    """
    current_year_j = jdatetime.date.today().year
    prev_year = current_year_j - 1

    result = {}

    for leave_type in ['AL', 'SL']:
        balance = db.query(LeaveBalance).filter(
            and_(
                LeaveBalance.user_id == user_id,
                LeaveBalance.year == prev_year,
                LeaveBalance.leave_type == leave_type
            )
        ).first()

        if balance and balance.balance > 0:
            result[leave_type] = balance.balance

    return result


def has_carry_forward_request(db: Session, user_id: str, from_year: int) -> bool:
    """بررسی وجود درخواست (هر وضعیتی) برای این سال - جلوگیری از نمایش مجدد مودال"""
    request = db.query(LeaveCarryForwardRequest).filter(
        and_(
            LeaveCarryForwardRequest.user_id == user_id,
            LeaveCarryForwardRequest.from_year == from_year
        )
    ).first()
    return request is not None


def user_chooses_use_leave(db: Session, user_id: str, leave_type: str = 'AL') -> dict:
    """
    🏖️ کاربر قصد استفاده دارد:
    - مانده سال قبل صفر شود
    - به مانده سال جدید اضافه شود (به عنوان مرخصی انتقالی)
    """
    current_year_j = jdatetime.date.today().year
    prev_year = current_year_j - 1

    # ۱. خواندن مانده سال قبل
    prev_balance = db.query(LeaveBalance).filter(
        and_(
            LeaveBalance.user_id == user_id,
            LeaveBalance.year == prev_year,
            LeaveBalance.leave_type == leave_type
        )
    ).first()

    if not prev_balance or prev_balance.balance <= 0:
        return {'success': False, 'error': 'مانده‌ای برای انتقال وجود ندارد'}

    days = prev_balance.balance

    # ۲. صفر کردن مانده سال قبل
    prev_balance.balance = 0

    # ۳. تراکنش CF_OUT برای سال قبل
    tx_out = LeaveTransaction(
        user_id=user_id,
        year=prev_year,
        leave_type=leave_type,
        amount=days,
        transaction_type='CF_OUT',
        description=f"انتقال مرخصی استفاده نشده به سال {current_year_j} (قصد استفاده)"
    )
    db.add(tx_out)

    # ۴. اضافه به مانده سال جدید
    new_balance = db.query(LeaveBalance).filter(
        and_(
            LeaveBalance.user_id == user_id,
            LeaveBalance.year == current_year_j,
            LeaveBalance.leave_type == leave_type
        )
    ).first()

    if new_balance:
        new_balance.balance += days
    else:
        new_balance = LeaveBalance(
            user_id=user_id,
            year=current_year_j,
            leave_type=leave_type,
            balance=days,
            is_carried_forward=True,
            carried_from_year=prev_year
        )
        db.add(new_balance)

    # ۵. تراکنش CF_IN برای سال جدید
    tx_in = LeaveTransaction(
        user_id=user_id,
        year=current_year_j,
        leave_type=leave_type,
        amount=days,
        transaction_type='CF_IN',
        description=f"مرخصی انتقالی از سال {prev_year} (قصد استفاده)"
    )
    db.add(tx_in)

    # ۶. ثبت درخواست با وضعیت تایید خودکار
    request = LeaveCarryForwardRequest(
        user_id=user_id,
        from_year=prev_year,
        to_year=current_year_j,
        leave_type=leave_type,
        days_count=days,
        user_choice='USE',
        status='A',
        processed_at=datetime.now(),
        processed_by=user_id
    )
    db.add(request)

    db.commit()

    return {'success': True, 'days': days}


def user_chooses_cash_out(db: Session, user_id: str, leave_type: str = 'AL') -> dict:
    """
    💰 کاربر درخواست بازخرید می‌دهد:
    - ثبت درخواست در انتظار برای مدیر
    - مانده فعلاً دست نخورده باقی می‌ماند
    """
    current_year_j = jdatetime.date.today().year
    prev_year = current_year_j - 1

    # بررسی مانده
    prev_balance = db.query(LeaveBalance).filter(
        and_(
            LeaveBalance.user_id == user_id,
            LeaveBalance.year == prev_year,
            LeaveBalance.leave_type == leave_type
        )
    ).first()

    if not prev_balance or prev_balance.balance <= 0:
        return {'success': False, 'error': 'مانده‌ای برای بازخرید وجود ندارد'}

    days = prev_balance.balance

    # بررسی درخواست تکراری
    existing = db.query(LeaveCarryForwardRequest).filter(
        and_(
            LeaveCarryForwardRequest.user_id == user_id,
            LeaveCarryForwardRequest.from_year == prev_year,
            LeaveCarryForwardRequest.leave_type == leave_type,
            LeaveCarryForwardRequest.status == 'P'
        )
    ).first()

    if existing:
        return {'success': False, 'error': 'درخواست قبلی در انتظار بررسی است'}

    # ثبت درخواست
    request = LeaveCarryForwardRequest(
        user_id=user_id,
        from_year=prev_year,
        to_year=current_year_j,
        leave_type=leave_type,
        days_count=days,
        user_choice='CASH',
        status='P'
    )
    db.add(request)
    db.commit()

    return {'success': True, 'days': days, 'request_id': request.id}


def admin_approve_cash_out(db: Session, request_id: int, admin_user_id: str) -> dict:
    """
    💰 مدیر درخواست بازخرید را تایید می‌کند:
    - مانده سال قبل صفر شود
    - تراکنش CASH_OUT ثبت شود
    """
    request = db.query(LeaveCarryForwardRequest).filter(
        LeaveCarryForwardRequest.id == request_id
    ).first()

    if not request:
        return {'success': False, 'error': 'درخواست یافت نشد'}

    if request.status != 'P':
        return {'success': False, 'error': 'درخواست قبلاً بررسی شده است'}

    # صفر کردن مانده سال قبل
    prev_balance = db.query(LeaveBalance).filter(
        and_(
            LeaveBalance.user_id == request.user_id,
            LeaveBalance.year == request.from_year,
            LeaveBalance.leave_type == request.leave_type
        )
    ).first()

    if prev_balance:
        prev_balance.balance = 0

    # تراکنش CASH_OUT
    tx = LeaveTransaction(
        user_id=request.user_id,
        year=request.from_year,
        leave_type=request.leave_type,
        amount=request.days_count,
        transaction_type='CASH_OUT',
        description=f"بازخرید مرخصی سال {request.from_year} (تایید مدیر)"
    )
    db.add(tx)

    # بروزرسانی درخواست
    request.status = 'C'
    request.processed_at = datetime.now()
    request.processed_by = admin_user_id

    db.commit()

    return {'success': True}


def admin_reject_cash_out(db: Session, request_id: int, admin_user_id: str, note: str = "") -> dict:
    """
    🔄 مدیر درخواست بازخرید را رد می‌کند:
    - مانده سال قبل صفر شود
    - به مانده سال جدید اضافه شود (مرخصی انتقالی)
    """
    request = db.query(LeaveCarryForwardRequest).filter(
        LeaveCarryForwardRequest.id == request_id
    ).first()

    if not request:
        return {'success': False, 'error': 'درخواست یافت نشد'}

    if request.status != 'P':
        return {'success': False, 'error': 'درخواست قبلاً بررسی شده است'}

    # صفر کردن مانده سال قبل
    prev_balance = db.query(LeaveBalance).filter(
        and_(
            LeaveBalance.user_id == request.user_id,
            LeaveBalance.year == request.from_year,
            LeaveBalance.leave_type == request.leave_type
        )
    ).first()

    if prev_balance:
        prev_balance.balance = 0

    # تراکنش CF_OUT برای سال قبل
    tx_out = LeaveTransaction(
        user_id=request.user_id,
        year=request.from_year,
        leave_type=request.leave_type,
        amount=request.days_count,
        transaction_type='CF_OUT',
        description=f"انتقال مرخصی به سال {request.to_year} (رد درخواست بازخرید)"
    )
    db.add(tx_out)

    # اضافه به مانده سال جدید
    new_balance = db.query(LeaveBalance).filter(
        and_(
            LeaveBalance.user_id == request.user_id,
            LeaveBalance.year == request.to_year,
            LeaveBalance.leave_type == request.leave_type
        )
    ).first()

    if new_balance:
        new_balance.balance += request.days_count
    else:
        new_balance = LeaveBalance(
            user_id=request.user_id,
            year=request.to_year,
            leave_type=request.leave_type,
            balance=request.days_count,
            is_carried_forward=True,
            carried_from_year=request.from_year
        )
        db.add(new_balance)

    # تراکنش CF_IN برای سال جدید
    tx_in = LeaveTransaction(
        user_id=request.user_id,
        year=request.to_year,
        leave_type=request.leave_type,
        amount=request.days_count,
        transaction_type='CF_IN',
        description=f"مرخصی انتقالی از سال {request.from_year} (رد درخواست بازخرید)"
    )
    db.add(tx_in)

    # بروزرسانی درخواست
    request.status = 'R'
    request.admin_note = note
    request.processed_at = datetime.now()
    request.processed_by = admin_user_id

    db.commit()

    return {'success': True}