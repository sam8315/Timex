"""
سرویس مدیریت شارژ مرخصی بر اساس قرارداد

منطق:
- ثبت قرارداد: اضافه شدن استحقاق با توجه به مدت قرارداد
- بروزرسانی قرارداد: اضافه یا کسر استحقاق
- حذف قرارداد: حذف استحقاق
"""
import math
from datetime import date
from sqlalchemy.orm import Session
from sqlalchemy import and_
import jdatetime

from models.contract import Contract
from models.leave_balance import LeaveBalance
from models.leave_transaction import LeaveTransaction


def _get_contract_year(contract: Contract) -> int:
    """دریافت سال شمسی قرارداد"""
    j_start = jdatetime.date.fromgregorian(date=contract.start_date)
    return j_start.year


def _calculate_prorated_leave(contract: Contract) -> dict:
    """محاسبه مرخصی به نسبت مدت قرارداد"""
    return {
        'AL': contract.prorated_annual_leave,
        'SL': contract.prorated_sick_leave,
    }


def _update_balance(
        db: Session,
        user_id: str,
        year: int,
        leave_type: str,
        new_amount: int
) -> LeaveBalance:
    """به‌روزرسانی مانده مرخصی"""
    balance = db.query(LeaveBalance).filter(
        and_(
            LeaveBalance.user_id == user_id,
            LeaveBalance.year == year,
            LeaveBalance.leave_type == leave_type
        )
    ).first()

    if balance:
        balance.balance = new_amount
    else:
        balance = LeaveBalance(
            user_id=user_id,
            year=year,
            leave_type=leave_type,
            balance=new_amount
        )
        db.add(balance)

    return balance


def _record_transaction(
        db: Session,
        user_id: str,
        year: int,
        leave_type: str,
        amount: int,
        transaction_type: str,
        description: str,
        reference_id: int
):
    """ثبت تراکنش مرخصی"""
    transaction = LeaveTransaction(
        user_id=user_id,
        year=year,
        leave_type=leave_type,
        amount=amount,
        transaction_type=transaction_type,
        description=description,
        reference_id=reference_id
    )
    db.add(transaction)


# ============================================
# ۱. ثبت قرارداد → شارژ مرخصی
# ============================================
def charge_leave_for_new_contract(db: Session, contract: Contract) -> dict:
    """
    🆕 شارژ مرخصی هنگام ثبت قرارداد جدید

    - مرخصی به نسبت مدت قرارداد محاسبه می‌شود
    - در LeaveBalance شارژ می‌شود
    - تراکنش CHARGE ثبت می‌شود
    """
    year = _get_contract_year(contract)
    prorated = _calculate_prorated_leave(contract)
    duration = contract.contract_duration_days
    duration_text = f"{duration} روز" if duration else "باز (دائمی)"

    charged = {}

    for leave_type, amount in prorated.items():
        if amount <= 0:
            continue

        amount_rounded = math.ceil(amount)  # گرد کردن به بالا

        # بررسی balance موجود
        balance = db.query(LeaveBalance).filter(
            and_(
                LeaveBalance.user_id == contract.user_id,
                LeaveBalance.year == year,
                LeaveBalance.leave_type == leave_type
            )
        ).first()

        if balance:
            # اضافه کردن به balance موجود
            balance.balance += amount_rounded
        else:
            balance = LeaveBalance(
                user_id=contract.user_id,
                year=year,
                leave_type=leave_type,
                balance=amount_rounded
            )
            db.add(balance)

        # ثبت تراکنش
        _record_transaction(
            db=db,
            user_id=contract.user_id,
            year=year,
            leave_type=leave_type,
            amount=amount_rounded,
            transaction_type='CHARGE',
            description=f"شارژ مرخصی قرارداد {contract.contract_type_name} - مدت: {duration_text}",
            reference_id=contract.id
        )

        charged[leave_type] = amount_rounded

    db.commit()
    return charged


# ============================================
# ۲. بروزرسانی قرارداد → اضافه یا کسر مرخصی
# ============================================
def update_leave_for_contract(
        db: Session,
        contract: Contract,
        old_annual_leave: int,
        old_sick_leave: int,
        old_start_date: date,
        old_end_date: date,
        old_deduction: int
) -> dict:
    """
    🆕 بروزرسانی مرخصی هنگام ویرایش قرارداد

    - مرخصی قدیمی و جدید به نسبت محاسبه می‌شوند
    - مابه‌التفاوت اضافه یا کسر می‌شود
    """
    year = _get_contract_year(contract)

    # محاسبه مرخصی قدیمی (با مقادیر قبلی)
    # باید یک قرارداد موقت با مقادیر قدیمی بسازیم
    old_duration = (old_end_date - old_start_date).days if old_end_date else None

    if old_duration is None or old_duration >= 365:
        old_al = float(old_annual_leave)
        old_sl = float(old_sick_leave)
    else:
        ratio = old_duration / 365.0
        old_al = old_annual_leave * ratio
        old_sl = old_sick_leave * ratio

    # محاسبه مرخصی جدید
    new_al = contract.prorated_annual_leave
    new_sl = contract.prorated_sick_leave

    changes = {}

    for leave_type, old_val, new_val in [
        ('AL', old_al, new_al),
        ('SL', old_sl, new_sl)
    ]:
        old_rounded = math.ceil(old_val) if old_val > 0 else 0
        new_rounded = math.ceil(new_val) if new_val > 0 else 0
        diff = new_rounded - old_rounded

        if diff == 0:
            continue

        # بروزرسانی balance
        balance = db.query(LeaveBalance).filter(
            and_(
                LeaveBalance.user_id == contract.user_id,
                LeaveBalance.year == year,
                LeaveBalance.leave_type == leave_type
            )
        ).first()

        if balance:
            balance.balance += diff
            # جلوگیری از منفی شدن
            if balance.balance < 0:
                balance.balance = 0
        elif diff > 0:
            balance = LeaveBalance(
                user_id=contract.user_id,
                year=year,
                leave_type=leave_type,
                balance=diff
            )
            db.add(balance)

        # ثبت تراکنش
        if diff > 0:
            _record_transaction(
                db=db,
                user_id=contract.user_id,
                year=year,
                leave_type=leave_type,
                amount=diff,
                transaction_type='CHARGE',
                description=f"افزایش مرخصی قرارداد {contract.contract_type_name}",
                reference_id=contract.id
            )
        else:
            _record_transaction(
                db=db,
                user_id=contract.user_id,
                year=year,
                leave_type=leave_type,
                amount=abs(diff),
                transaction_type='DEDUCT',
                description=f"کسر مرخصی قرارداد {contract.contract_type_name}",
                reference_id=contract.id
            )

        changes[leave_type] = diff

    db.commit()
    return changes


# ============================================
# ۳. حذف قرارداد → حذف مرخصی
# ============================================
def remove_leave_for_contract(db: Session, contract: Contract) -> dict:
    """
    🆕 حذف مرخصی هنگام حذف قرارداد

    - مرخصی شارژ شده از این قرارداد کسر می‌شود
    - تراکنش REVERSE ثبت می‌شود
    """
    year = _get_contract_year(contract)
    prorated = _calculate_prorated_leave(contract)

    removed = {}

    for leave_type, amount in prorated.items():
        if amount <= 0:
            continue

        amount_rounded = math.ceil(amount)

        # کسر از balance
        balance = db.query(LeaveBalance).filter(
            and_(
                LeaveBalance.user_id == contract.user_id,
                LeaveBalance.year == year,
                LeaveBalance.leave_type == leave_type
            )
        ).first()

        if balance:
            balance.balance -= amount_rounded
            # جلوگیری از منفی شدن
            if balance.balance < 0:
                balance.balance = 0

        # ثبت تراکنش
        _record_transaction(
            db=db,
            user_id=contract.user_id,
            year=year,
            leave_type=leave_type,
            amount=amount_rounded,
            transaction_type='REVERSE',
            description=f"حذف مرخصی قرارداد {contract.contract_type_name}",
            reference_id=contract.id
        )

        removed[leave_type] = amount_rounded

    db.commit()
    return removed