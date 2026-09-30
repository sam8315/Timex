"""
واردسازی مانده‌های اولیه از نیروی انسانی (ذخیره / قابل‌بازخرید / سوخت).
"""
from __future__ import annotations

from typing import Optional
from sqlalchemy.orm import Session
from sqlalchemy import and_

from models.employee import Employee
from models.leave_balance import LeaveBalance
from models.leave_transaction import LeaveTransaction
from models.leave_buyback_quota import LeaveBuybackQuota
from models.leave_glossary import LEAVE_TYPE_CW, TX_BURN, TX_IMPORT


def _add_cw(db: Session, user_id: str, year: int, days: int, admin_name: str) -> str:
    if days <= 0:
        return "ذخیره صفر — رد شد"
    balance = db.query(LeaveBalance).filter(
        and_(
            LeaveBalance.user_id == user_id,
            LeaveBalance.year == year,
            LeaveBalance.leave_type == LEAVE_TYPE_CW,
        )
    ).first()
    if balance:
        old = balance.balance
        balance.balance += days
        action = f"ذخیره: {old} → {balance.balance}"
    else:
        db.add(LeaveBalance(
            user_id=user_id,
            year=year,
            leave_type=LEAVE_TYPE_CW,
            balance=days,
            is_carried_forward=True,
            carried_from_year=year - 1,
        ))
        action = f"ذخیره ایجاد شد ({days})"
    db.add(LeaveTransaction(
        user_id=user_id,
        year=year,
        leave_type=LEAVE_TYPE_CW,
        amount=days,
        transaction_type=TX_IMPORT,
        description=f"ورود ذخیره از منابع انسانی توسط {admin_name}",
    ))
    return action


def _add_buyback(db: Session, user_id: str, year: int, days: int, admin_name: str) -> str:
    if days < 0:
        raise ValueError("قابل‌بازخرید نمی‌تواند منفی باشد")
    quota = db.query(LeaveBuybackQuota).filter(
        and_(
            LeaveBuybackQuota.user_id == user_id,
            LeaveBuybackQuota.year == year,
        )
    ).first()
    if quota:
        old = quota.days
        quota.days += days
        quota.source = 'HR_IMPORT'
        quota.notes = f"به‌روزرسانی توسط {admin_name}"
        return f"قابل‌بازخرید: {old} → {quota.days}"
    db.add(LeaveBuybackQuota(
        user_id=user_id,
        year=year,
        days=days,
        source='HR_IMPORT',
        notes=f"ورود اولیه توسط {admin_name}",
    ))
    return f"قابل‌بازخرید ثبت شد ({days})"


def _add_burn(db: Session, user_id: str, year: int, days: int, admin_name: str) -> str:
    if days <= 0:
        return "سوخت صفر — رد شد"
    db.add(LeaveTransaction(
        user_id=user_id,
        year=year,
        leave_type=LEAVE_TYPE_CW,
        amount=days,
        transaction_type=TX_BURN,
        description=f"سوخت‌شده — ورود از منابع انسانی توسط {admin_name}",
    ))
    return f"سوخت ثبت شد ({days})"


def import_hr_opening_line(
    db: Session,
    *,
    user_id: str,
    year: int,
    stored_days: int = 0,
    buyback_days: int = 0,
    burned_days: int = 0,
    admin_name: str = "admin",
    membership_hint: Optional[str] = None,
) -> dict:
    """
    ورود یک خط از HR.

    رسمی: stored + buyback
    قراردادی: stored + buyback + burned
    """
    employee = db.query(Employee).filter(Employee.user_id == user_id).first()
    if not employee:
        return {'success': False, 'error': f'کاربر {user_id} یافت نشد'}

    dept = membership_hint or employee.department or ''
    actions = []

    if stored_days:
        actions.append(_add_cw(db, user_id, year, stored_days, admin_name))
    if buyback_days:
        actions.append(_add_buyback(db, user_id, year, buyback_days, admin_name))

    # سوخت عمدتاً برای قراردادی؛ برای رسمی اگر ارسال شود هم در ledger ثبت می‌شود
    if burned_days:
        if dept == '1' and burned_days > 0:
            # رسمی معمولاً سوخت ندارد — باز هم ثبت تاریخچه مجاز است با هشدار
            actions.append(_add_burn(db, user_id, year, burned_days, admin_name) + " (هشدار: رسمی)")
        else:
            actions.append(_add_burn(db, user_id, year, burned_days, admin_name))

    if not actions:
        return {'success': False, 'error': 'هیچ مقداری برای ورود داده نشد'}

    return {
        'success': True,
        'user_id': user_id,
        'full_name': employee.full_name,
        'department': dept,
        'action': ' | '.join(actions),
    }
