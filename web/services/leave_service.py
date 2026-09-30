"""
سرویس مدیریت شارژ مرخصی بر اساس قرارداد + سیاست عضویت
"""
import logging
from datetime import date
from typing import List, Optional, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import and_

from models.contract import Contract
from models.employee import Employee
from models.leave_balance import LeaveBalance
from models.leave_transaction import LeaveTransaction
from models.leave_glossary import (
    LEAVE_TYPE_NAMES as GLOSSARY_LEAVE_TYPE_NAMES,
    LEAVE_TYPE_CW,
    MEMBERSHIP_PERMANENT,
    TX_CHARGE,
    TX_DEDUCT,
    TX_REVERSE,
    TX_USE,
)
from web.services.leave_entitlement_service import (
    calculate_entitlement_by_year,
    get_jalali_year_days,
    split_contract_coverage_by_year,
    sync_employee_department_from_active_contract,
)

logger = logging.getLogger(__name__)

# سازگاری با importهای قدیمی
LEAVE_TYPE_NAMES = dict(GLOSSARY_LEAVE_TYPE_NAMES)


def split_contract_by_year(contract: Contract) -> List[Tuple[int, date, Optional[date]]]:
    return split_contract_coverage_by_year(contract)


def calculate_prorated_leave_by_year(
    contract: Contract,
    db: Optional[Session] = None,
    employee: Optional[Employee] = None,
    annual_override: Optional[int] = None,
) -> dict:
    """
    محاسبه مرخصی به تفکیک سال با قواعد عضویت.

    اگر db داده شود از سیاست عضویت/منطقه خوانده می‌شود؛
    در غیر این صورت از annual_leave_days روی قرارداد (یا annual_override).
    """
    if db is not None:
        return calculate_entitlement_by_year(
            db, contract, employee=employee, annual_override=annual_override
        )

    from web.services.leave_entitlement_service import charge_amount_for_segment

    annual = float(
        annual_override if annual_override is not None else contract.annual_leave_days
    )
    sick = float(contract.sick_leave_days or 0)
    result = {}
    for year_j, seg_start, seg_end in split_contract_coverage_by_year(contract):
        al = charge_amount_for_segment(
            contract.contract_type_code, annual, year_j, seg_start, seg_end
        )
        sl = charge_amount_for_segment(
            contract.contract_type_code, sick, year_j, seg_start, seg_end
        )
        if year_j not in result:
            result[year_j] = {'AL': 0.0, 'SL': 0.0}
        result[year_j]['AL'] += al
        result[year_j]['SL'] += sl
    return result


def charge_leave_for_new_contract(db: Session, contract: Contract) -> dict:
    """شارژ مرخصی هنگام ثبت قرارداد جدید (قواعد عضویت + سیاست)."""
    employee = db.query(Employee).filter(Employee.user_id == contract.user_id).first()
    prorated_by_year = calculate_prorated_leave_by_year(
        contract, db=db, employee=employee, annual_override=contract.annual_leave_days
    )
    logger.info(f"🔍 Charging leave for contract {contract.id}: {prorated_by_year}")

    charged = {}
    for year_j, leaves in prorated_by_year.items():
        charged[year_j] = {}
        for leave_type, amount in leaves.items():
            amount_rounded = round(amount)
            logger.info(
                f"📊 Year {year_j}, Type {leave_type}: "
                f"raw={amount:.2f}, rounded={amount_rounded}"
            )
            if amount_rounded <= 0:
                continue

            balance = db.query(LeaveBalance).filter(
                and_(
                    LeaveBalance.user_id == contract.user_id,
                    LeaveBalance.year == year_j,
                    LeaveBalance.leave_type == leave_type,
                )
            ).first()

            if balance:
                balance.balance += amount_rounded
            else:
                balance = LeaveBalance(
                    user_id=contract.user_id,
                    year=year_j,
                    leave_type=leave_type,
                    balance=amount_rounded,
                )
                db.add(balance)

            db.add(LeaveTransaction(
                user_id=contract.user_id,
                year=year_j,
                leave_type=leave_type,
                amount=amount_rounded,
                transaction_type=TX_CHARGE,
                description=(
                    f"شارژ مرخصی قرارداد {contract.contract_type_name} - سال {year_j}"
                ),
                reference_id=contract.id,
            ))
            charged[year_j][leave_type] = amount_rounded

    sync_employee_department_from_active_contract(db, contract.user_id, commit=False)
    db.commit()
    return charged


def update_leave_for_contract(
    db: Session,
    contract: Contract,
    old_annual_leave: int,
    old_sick_leave: int,
    old_start_date: date,
    old_end_date: date,
    old_deduction: int,
    old_type_code: Optional[str] = None,
) -> dict:
    """بروزرسانی مرخصی هنگام ویرایش قرارداد با قواعد عضویت."""
    employee = db.query(Employee).filter(Employee.user_id == contract.user_id).first()
    old_code = old_type_code or contract.contract_type_code

    old_contract = Contract(
        user_id=contract.user_id,
        contract_type_code=old_code,
        start_date=old_start_date,
        end_date=old_end_date,
        annual_leave_days=old_annual_leave,
        sick_leave_days=old_sick_leave,
        service_deduction_days=old_deduction,
    )

    old_prorated = calculate_prorated_leave_by_year(
        old_contract, db=db, employee=employee, annual_override=old_annual_leave
    )
    new_prorated = calculate_prorated_leave_by_year(
        contract, db=db, employee=employee, annual_override=contract.annual_leave_days
    )

    logger.info(f"🔄 Old prorated: {old_prorated}")
    logger.info(f"🔄 New prorated: {new_prorated}")

    all_years = set(list(old_prorated.keys()) + list(new_prorated.keys()))
    changes = {}

    for year_j in all_years:
        old_leaves = old_prorated.get(year_j, {'AL': 0, 'SL': 0})
        new_leaves = new_prorated.get(year_j, {'AL': 0, 'SL': 0})

        for leave_type in ['AL', 'SL']:
            # رسمی: تغییر صرفاً end_date نباید AL را عوض کند
            if (
                contract.contract_type_code == MEMBERSHIP_PERMANENT
                and old_code == MEMBERSHIP_PERMANENT
                and leave_type == 'AL'
                and old_start_date == contract.start_date
                and old_annual_leave == contract.annual_leave_days
                and old_end_date != contract.end_date
            ):
                continue

            old_val = round(old_leaves.get(leave_type, 0))
            new_val = round(new_leaves.get(leave_type, 0))
            diff = new_val - old_val
            if diff == 0:
                continue

            balance = db.query(LeaveBalance).filter(
                and_(
                    LeaveBalance.user_id == contract.user_id,
                    LeaveBalance.year == year_j,
                    LeaveBalance.leave_type == leave_type,
                )
            ).first()

            if balance:
                balance.balance += diff
                if balance.balance < 0:
                    balance.balance = 0
            elif diff > 0:
                balance = LeaveBalance(
                    user_id=contract.user_id,
                    year=year_j,
                    leave_type=leave_type,
                    balance=diff,
                )
                db.add(balance)

            tx_type = TX_CHARGE if diff > 0 else TX_DEDUCT
            tx_desc = (
                f"{'افزایش' if diff > 0 else 'کسر'} مرخصی قرارداد "
                f"{contract.contract_type_name} - سال {year_j}"
            )
            db.add(LeaveTransaction(
                user_id=contract.user_id,
                year=year_j,
                leave_type=leave_type,
                amount=abs(diff),
                transaction_type=tx_type,
                description=tx_desc,
                reference_id=contract.id,
            ))
            changes.setdefault(year_j, {})[leave_type] = diff

    sync_employee_department_from_active_contract(db, contract.user_id, commit=False)
    db.commit()
    return changes


def remove_leave_for_contract(db: Session, contract: Contract) -> dict:
    """حذف مرخصی هنگام حذف قرارداد"""
    employee = db.query(Employee).filter(Employee.user_id == contract.user_id).first()
    prorated_by_year = calculate_prorated_leave_by_year(
        contract, db=db, employee=employee, annual_override=contract.annual_leave_days
    )
    removed = {}

    for year_j, leaves in prorated_by_year.items():
        removed[year_j] = {}
        for leave_type, amount in leaves.items():
            amount_rounded = round(amount)
            if amount_rounded <= 0:
                continue

            balance = db.query(LeaveBalance).filter(
                and_(
                    LeaveBalance.user_id == contract.user_id,
                    LeaveBalance.year == year_j,
                    LeaveBalance.leave_type == leave_type,
                )
            ).first()

            if balance:
                balance.balance -= amount_rounded
                if balance.balance < 0:
                    balance.balance = 0

            db.add(LeaveTransaction(
                user_id=contract.user_id,
                year=year_j,
                leave_type=leave_type,
                amount=amount_rounded,
                transaction_type=TX_REVERSE,
                description=(
                    f"حذف مرخصی قرارداد {contract.contract_type_name} - سال {year_j}"
                ),
                reference_id=contract.id,
            ))
            removed[year_j][leave_type] = amount_rounded

    db.flush()
    sync_employee_department_from_active_contract(db, contract.user_id, commit=False)
    db.commit()
    return removed


def get_stored_leave_balance(db: Session, user_id: str, year: int) -> int:
    """مانده CW برای یک سال شمسی."""
    bal = db.query(LeaveBalance).filter(
        and_(
            LeaveBalance.user_id == user_id,
            LeaveBalance.year == year,
            LeaveBalance.leave_type == LEAVE_TYPE_CW,
        )
    ).first()
    return bal.balance if bal else 0


def set_stored_leave_for_year(
    db: Session,
    *,
    user_id: str,
    year: int,
    target_days: int,
    reference_id: Optional[int] = None,
    description: str = "",
    commit: bool = True,
) -> dict:
    """
    تنظیم مطلق مانده CW به target_days با اعمال مابه‌التفاوت.
    Returns: {'old': int, 'new': int, 'diff': int}
    """
    if target_days < 0:
        raise ValueError("مرخصی ذخیره نمی‌تواند منفی باشد")

    balance = db.query(LeaveBalance).filter(
        and_(
            LeaveBalance.user_id == user_id,
            LeaveBalance.year == year,
            LeaveBalance.leave_type == LEAVE_TYPE_CW,
        )
    ).first()
    old = balance.balance if balance else 0
    diff = target_days - old
    if diff == 0:
        return {'old': old, 'new': old, 'diff': 0}

    if balance:
        balance.balance = target_days
    else:
        balance = LeaveBalance(
            user_id=user_id,
            year=year,
            leave_type=LEAVE_TYPE_CW,
            balance=target_days,
            is_carried_forward=True,
            carried_from_year=year - 1,
        )
        db.add(balance)

    db.add(LeaveTransaction(
        user_id=user_id,
        year=year,
        leave_type=LEAVE_TYPE_CW,
        amount=abs(diff),
        transaction_type=TX_CHARGE if diff > 0 else TX_DEDUCT,
        description=description or (
            f"{'افزایش' if diff > 0 else 'کسر'} مرخصی ذخیره سال {year}"
        ),
        reference_id=reference_id,
    ))
    if commit:
        db.commit()
    return {'old': old, 'new': target_days, 'diff': diff}


# ============================================
# منطق مصرف مرخصی - استاندارد صنعتی (FIFO معکوس)
# ============================================

def get_available_leave(db: Session, user_id: str, year: int, leave_type: str = 'AL') -> dict:
    """
    محاسبه مرخصی قابل استفاده (نمایش یکپارچه)
    برای نوع استحقاقی: AL + CW (انتقالی)
    """
    result = {'total': 0, 'breakdown': {}}

    main_balance = db.query(LeaveBalance).filter(
        and_(
            LeaveBalance.user_id == user_id,
            LeaveBalance.year == year,
            LeaveBalance.leave_type == leave_type,
        )
    ).first()

    if main_balance and main_balance.balance > 0:
        result['breakdown'][leave_type] = main_balance.balance
        result['total'] += main_balance.balance

    if leave_type == 'AL':
        cw_balance = db.query(LeaveBalance).filter(
            and_(
                LeaveBalance.user_id == user_id,
                LeaveBalance.year == year,
                LeaveBalance.leave_type == 'CW',
            )
        ).first()

        if cw_balance and cw_balance.balance > 0:
            result['breakdown']['CW'] = cw_balance.balance
            result['total'] += cw_balance.balance

    return result


def consume_leave(
    db: Session,
    user_id: str,
    year: int,
    days_needed: float,
    leave_type: str = 'AL',
    *,
    commit: bool = True,
    reference_id: Optional[int] = None,
    allow_negative: bool = False,
) -> dict:
    """
    مصرف مرخصی:
    1. اول از CW (انتقالی)
    2. سپس از AL (استحقاقی)
    """
    remaining = float(days_needed)
    consumed_from = {}

    if leave_type == 'AL':
        cw = db.query(LeaveBalance).filter(
            and_(
                LeaveBalance.user_id == user_id,
                LeaveBalance.year == year,
                LeaveBalance.leave_type == 'CW',
            )
        ).first()

        if cw and cw.balance > 0:
            use_from_cw = min(remaining, float(cw.balance))
            cw.balance -= use_from_cw
            remaining -= use_from_cw
            consumed_from['CW'] = use_from_cw

            db.add(LeaveTransaction(
                user_id=user_id,
                year=year,
                leave_type='CW',
                amount=use_from_cw,
                transaction_type=TX_USE,
                description="مصرف مرخصی انتقالی از سال قبل (اولویت اول)",
                reference_id=reference_id,
            ))

    if remaining > 0:
        main = db.query(LeaveBalance).filter(
            and_(
                LeaveBalance.user_id == user_id,
                LeaveBalance.year == year,
                LeaveBalance.leave_type == leave_type,
            )
        ).first()

        if main and (main.balance > 0 or allow_negative):
            if allow_negative:
                use_from_main = remaining
            else:
                use_from_main = min(remaining, float(main.balance))
            main.balance -= use_from_main
            remaining -= use_from_main
            consumed_from[leave_type] = use_from_main

            db.add(LeaveTransaction(
                user_id=user_id,
                year=year,
                leave_type=leave_type,
                amount=use_from_main,
                transaction_type=TX_USE,
                description=f"مصرف مرخصی {LEAVE_TYPE_NAMES.get(leave_type, leave_type)}",
                reference_id=reference_id,
            ))
        elif remaining > 0 and allow_negative:
            use_from_main = remaining
            main = LeaveBalance(
                user_id=user_id,
                year=year,
                leave_type=leave_type,
                balance=-use_from_main,
            )
            db.add(main)
            remaining = 0
            consumed_from[leave_type] = use_from_main
            db.add(LeaveTransaction(
                user_id=user_id,
                year=year,
                leave_type=leave_type,
                amount=use_from_main,
                transaction_type=TX_USE,
                description=f"مصرف مرخصی {LEAVE_TYPE_NAMES.get(leave_type, leave_type)}",
                reference_id=reference_id,
            ))

    if commit:
        db.commit()

    return {
        'success': remaining <= 0,
        'consumed': days_needed - remaining,
        'remaining': max(0, remaining),
        'consumed_from': consumed_from,
    }
