"""
سرویس مدیریت شارژ مرخصی بر اساس قرارداد + سیاست عضویت
"""
import logging
from datetime import date
from typing import List, Optional, Tuple

import jdatetime
from sqlalchemy.orm import Session
from sqlalchemy import and_

from models.contract import Contract
from models.employee import Employee
from models.leave_balance import LeaveBalance
from models.leave_buyback_quota import LeaveBuybackQuota
from models.leave_transaction import LeaveTransaction
from models.leave_glossary import (
    LEAVE_TYPE_NAMES as GLOSSARY_LEAVE_TYPE_NAMES,
    LEAVE_TYPE_CW,
    TX_CF_OUT,
    TX_CHARGE,
    TX_DEDUCT,
    TX_REVERSE,
    TX_USE,
)
from web.services.leave_entitlement_service import (
    get_jalali_year_days,
    resolve_max_buyback,
    resolve_membership_for_user,
    split_contract_coverage_by_year,
    sync_employee_department_from_active_contract,
)

logger = logging.getLogger(__name__)

# سازگاری با importهای قدیمی
LEAVE_TYPE_NAMES = dict(GLOSSARY_LEAVE_TYPE_NAMES)


def split_contract_by_year(
    contract: Contract,
    db: Optional[Session] = None,
) -> List[Tuple[int, date, Optional[date]]]:
    return split_contract_coverage_by_year(contract, db=db)


def calculate_prorated_leave_by_year(
    contract: Contract,
    db: Optional[Session] = None,
    employee: Optional[Employee] = None,
    annual_override: Optional[int] = None,
) -> dict:
    """
    محاسبه مرخصی قابل‌شارژ به تفکیک سال (بدون SL).
    برای وظیفه: همه سال‌های دوره؛ برای سایر عضویت‌ها: سال جاری.

    اگر db داده شود از سیاست عضویت/منطقه خوانده می‌شود؛
    در غیر این صورت از annual_leave_days روی قرارداد (یا annual_override).

    Phase 5: when db is set, path is selected by TIMEX_AL_ENTITLEMENT_PATH
    (engine default | shadow | legacy) via leave_entitlement_cutover.
    Mutation callers (charge/update/remove) are unchanged.
    """
    if db is not None:
        from web.services.leave_entitlement_cutover import resolve_prorated_entitlement

        return resolve_prorated_entitlement(
            db,
            contract,
            employee=employee,
            annual_override=annual_override,
        )

    from web.services.leave_entitlement_service import charge_amount_for_segment

    annual = float(
        annual_override if annual_override is not None else contract.annual_leave_days
    )
    result = {}
    for year_j, seg_start, seg_end in split_contract_coverage_by_year(contract, db=None):
        al = charge_amount_for_segment(
            contract.contract_type_code, annual, year_j, seg_start, seg_end, db=None
        )
        if year_j not in result:
            result[year_j] = {'AL': 0.0, 'SL': 0.0}
        result[year_j]['AL'] += al
        result[year_j]['SL'] = 0.0
    return result


def charge_leave_for_new_contract(
    db: Session,
    contract: Contract,
    *,
    years_filter: Optional[set] = None,
) -> dict:
    """شارژ مرخصی هنگام ثبت قرارداد جدید (قواعد عضویت + سیاست).

    ``years_filter``: اگر ست شود فقط همان سال‌ها شارژ می‌شوند
    (مثلاً فقط سال جاری وقتی تاریخچه رسمی سال‌های قبل را می‌سازد).
    """
    employee = db.query(Employee).filter(Employee.user_id == contract.user_id).first()
    prorated_by_year = calculate_prorated_leave_by_year(
        contract, db=db, employee=employee, annual_override=contract.annual_leave_days
    )
    logger.info(f"🔍 Charging leave for contract {contract.id}: {prorated_by_year}")

    charged = {}
    for year_j, leaves in prorated_by_year.items():
        if years_filter is not None and year_j not in years_filter:
            continue
        charged[year_j] = {}
        for leave_type, amount in leaves.items():
            if leave_type == 'SL':
                continue
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


def apply_al_proration_diff(
    db: Session,
    contract: Contract,
    old_prorated: dict,
    new_prorated: dict,
    *,
    description_prefix: Optional[str] = None,
    skip_year_fn=None,
) -> dict:
    """
    Apply AL balance/transaction diffs between two prorated-by-year maps.

    ``skip_year_fn(year_j, leave_type) -> bool`` may skip a cell (e.g. permanent
    end-date-only edits in ``update_leave_for_contract``).
    """
    all_years = set(list(old_prorated.keys()) + list(new_prorated.keys()))
    changes = {}
    prefix = description_prefix or (
        f"مرخصی قرارداد {contract.contract_type_name}"
    )

    for year_j in all_years:
        old_leaves = old_prorated.get(year_j, {'AL': 0, 'SL': 0})
        new_leaves = new_prorated.get(year_j, {'AL': 0, 'SL': 0})

        for leave_type in ['AL']:
            if skip_year_fn is not None and skip_year_fn(year_j, leave_type):
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
                f"{'افزایش' if diff > 0 else 'کسر'} {prefix} - سال {year_j}"
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

    return changes


def update_leave_for_contract(
    db: Session,
    contract: Contract,
    old_annual_leave: int,
    old_sick_leave: int,
    old_start_date: date,
    old_end_date: date,
    old_deduction: int,
    old_type_code: Optional[str] = None,
    *,
    commit: bool = True,
    skip_years: Optional[set] = None,
) -> dict:
    """بروزرسانی مرخصی هنگام ویرایش قرارداد با قواعد عضویت.

    ``skip_years``: سال‌هایی که از diff پروراتا رد می‌شوند
    (مثلاً سال‌های تاریخچه رسمی که جداگانه rebuild می‌شوند).
    """
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

    from web.services import membership_semantics as msem

    def _skip_fn(year_j, leave_type):
        if skip_years is not None and year_j in skip_years:
            return True
        return (
            msem.is_permanent(db, contract.contract_type_code)
            and msem.is_permanent(db, old_code)
            and leave_type == 'AL'
            and old_start_date == contract.start_date
            and old_annual_leave == contract.annual_leave_days
            and old_end_date != contract.end_date
        )

    changes = apply_al_proration_diff(
        db,
        contract,
        old_prorated,
        new_prorated,
        skip_year_fn=_skip_fn,
    )

    sync_employee_department_from_active_contract(db, contract.user_id, commit=False)
    if commit:
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
            if leave_type == 'SL':
                continue
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


def get_buyback_quota(db: Session, user_id: str, year: int) -> int:
    """سهمیه قابل‌بازخرید ثبت‌شده برای کاربر/سال."""
    quota = db.query(LeaveBuybackQuota).filter(
        and_(
            LeaveBuybackQuota.user_id == user_id,
            LeaveBuybackQuota.year == year,
        )
    ).first()
    return int(quota.days) if quota else 0


def resolve_cw_buyback_limit(
    db: Session,
    user_id: str,
    year: int,
) -> Optional[int]:
    """
    حد قابل‌بازخرید برای تقسیم ذخیره (CW).

    - اگر سهمیه ثبت‌شده (LeaveBuybackQuota) باشد → همان مقدار (حتی ۰)
    - وگرنه سقف سیاست عضویت/منطقه (None = همهٔ CW قابل‌بازخرید)
    """
    quota = db.query(LeaveBuybackQuota).filter(
        and_(
            LeaveBuybackQuota.user_id == user_id,
            LeaveBuybackQuota.year == year,
        )
    ).first()
    if quota is not None:
        return max(0, int(quota.days or 0))
    membership = resolve_membership_for_user(db, user_id)
    return resolve_max_buyback(db, membership, user_id=user_id, year_j=year)


def _reduce_buyback_after_consume(
    db: Session,
    user_id: str,
    year: int,
    used_buyback: float,
    *,
    prior_limit: Optional[int],
) -> None:
    """پس از مصرف از بخش قابل‌بازخرید CW، سهمیه باقی‌مانده را کم می‌کند."""
    used = int(round(float(used_buyback or 0)))
    if used <= 0:
        return
    quota = db.query(LeaveBuybackQuota).filter(
        and_(
            LeaveBuybackQuota.user_id == user_id,
            LeaveBuybackQuota.year == year,
        )
    ).first()
    if quota is not None:
        quota.days = max(0, int(quota.days or 0) - used)
        return
    if prior_limit is None:
        return
    db.add(LeaveBuybackQuota(
        user_id=user_id,
        year=year,
        days=max(0, int(prior_limit) - used),
        source='CONSUME',
        notes='باقی‌مانده پس از مصرف ذخیره قابل‌بازخرید',
    ))


def set_buyback_quota_for_year(
    db: Session,
    *,
    user_id: str,
    year: int,
    target_days: int,
    source: str = 'MANUAL',
    notes: str = "",
    commit: bool = True,
) -> dict:
    """
    تنظیم مطلق سهمیه قابل‌بازخرید به target_days.
    Returns: {'old': int, 'new': int, 'diff': int}
    """
    if target_days < 0:
        raise ValueError("قابل‌بازخرید نمی‌تواند منفی باشد")

    quota = db.query(LeaveBuybackQuota).filter(
        and_(
            LeaveBuybackQuota.user_id == user_id,
            LeaveBuybackQuota.year == year,
        )
    ).first()
    old = int(quota.days) if quota else 0
    if old == target_days:
        return {'old': old, 'new': old, 'diff': 0}

    if quota:
        quota.days = target_days
        quota.source = source
        if notes:
            quota.notes = notes
    else:
        db.add(LeaveBuybackQuota(
            user_id=user_id,
            year=year,
            days=target_days,
            source=source,
            notes=notes or None,
        ))

    if commit:
        db.commit()
    return {'old': old, 'new': target_days, 'diff': target_days - old}


# ============================================
# منطق مصرف مرخصی — اولویت سطل‌ها (همه عضویت‌ها)
# 1) ذخیره − قابل‌بازخرید (non-buyback CW)
# 2) استحقاقی سال جاری (AL)
# 3) ذخیره قابل‌بازخرید (buyback CW)
# ============================================

def split_cw_buckets(cw_balance: float, buyback_limit: Optional[int]) -> dict:
    """
    تقسیم مانده CW: قابل‌بازخرید = min(CW, limit)؛ بقیه غیرقابل‌بازخرید.

    buyback_limit=None → همه CW قابل‌بازخرید (non_buyback=0)
    """
    cw = max(0.0, float(cw_balance or 0))
    if buyback_limit is None:
        return {'non_buyback': 0.0, 'buybackable': cw}
    cap = max(0, int(buyback_limit))
    buybackable = min(cw, float(cap))
    return {'non_buyback': cw - buybackable, 'buybackable': buybackable}


def get_available_leave(db: Session, user_id: str, year: int, leave_type: str = 'AL') -> dict:
    """
    محاسبه مرخصی قابل استفاده (نمایش یکپارچه).
    برای AL: مجموع AL+CW و breakdown سه‌سطلی با همان قانون مصرف.
    """
    result = {'total': 0, 'breakdown': {}}

    main_balance = db.query(LeaveBalance).filter(
        and_(
            LeaveBalance.user_id == user_id,
            LeaveBalance.year == year,
            LeaveBalance.leave_type == leave_type,
        )
    ).first()

    al_days = float(main_balance.balance) if main_balance and main_balance.balance > 0 else 0.0
    if al_days > 0:
        result['breakdown'][leave_type] = al_days
        result['total'] += al_days

    if leave_type == 'AL':
        cw_balance = db.query(LeaveBalance).filter(
            and_(
                LeaveBalance.user_id == user_id,
                LeaveBalance.year == year,
                LeaveBalance.leave_type == 'CW',
            )
        ).first()
        cw_days = float(cw_balance.balance) if cw_balance and cw_balance.balance > 0 else 0.0
        if cw_days > 0:
            result['breakdown']['CW'] = cw_days
            result['total'] += cw_days

        membership = resolve_membership_for_user(db, user_id)
        buyback_limit = resolve_cw_buyback_limit(db, user_id, year)
        buckets = split_cw_buckets(cw_days, buyback_limit)
        result['breakdown']['CW_NON_BUYBACK'] = buckets['non_buyback']
        result['breakdown']['CW_BUYBACK'] = buckets['buybackable']
        result['buyback_cap'] = buyback_limit
        result['buyback_quota'] = get_buyback_quota(db, user_id, year)
        result['membership_code'] = membership

    return result


def get_user_al_year_snapshot(db: Session, user_id: str, year: int) -> dict:
    """
    خلاصه استحقاق / استفاده / مانده مرخصی استحقاقی برای یک سال شمسی.

    - entitlement: خالص شارژ AL (CHARGE − DEDUCT − REVERSE)
    - used: TX_USE (AL/CW) + CF_OUT (AL) — انتقال به ذخیره هم «مصرف‌شده از سال» است
    - remaining / cw_days: از get_available_leave
    """
    charge_txs = db.query(LeaveTransaction).filter(
        and_(
            LeaveTransaction.user_id == user_id,
            LeaveTransaction.year == year,
            LeaveTransaction.leave_type == 'AL',
            LeaveTransaction.transaction_type.in_(
                [TX_CHARGE, TX_DEDUCT, TX_REVERSE]
            ),
        )
    ).all()

    entitlement = 0
    for tx in charge_txs:
        if tx.transaction_type == TX_CHARGE:
            sign = 1
        else:
            # DEDUCT and REVERSE both undo entitlement
            sign = -1
        entitlement += sign * int(tx.amount or 0)
    entitlement = max(0, entitlement)

    use_txs = db.query(LeaveTransaction).filter(
        and_(
            LeaveTransaction.user_id == user_id,
            LeaveTransaction.year == year,
            LeaveTransaction.leave_type.in_(['AL', 'CW']),
            LeaveTransaction.transaction_type == TX_USE,
        )
    ).all()
    used = sum(int(tx.amount or 0) for tx in use_txs)

    cf_out_txs = db.query(LeaveTransaction).filter(
        and_(
            LeaveTransaction.user_id == user_id,
            LeaveTransaction.year == year,
            LeaveTransaction.leave_type == 'AL',
            LeaveTransaction.transaction_type == TX_CF_OUT,
        )
    ).all()
    cf_out = sum(int(tx.amount or 0) for tx in cf_out_txs)
    used += cf_out

    available = get_available_leave(db, user_id, year, leave_type='AL')
    remaining = float(available.get('total') or 0)
    breakdown = available.get('breakdown') or {}
    cw_days = float(breakdown.get('CW') or 0)
    al_days = float(breakdown.get('AL') or 0)

    return {
        'entitlement': entitlement,
        'used': used,
        'cf_out': cf_out,
        'remaining': remaining,
        'al_days': al_days,
        'cw_days': cw_days,
        'breakdown': breakdown,
    }


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
    مصرف مرخصی استحقاقی برای همه عضویت‌ها:
    1) ذخیره − قابل‌بازخرید (اگر > ۰)
    2) استحقاقی همان سال
    3) ذخیره قابل‌بازخرید

    برای وظیفه: پس از سال درخواست، از سایر سال‌های دوره خدمت (قدیم‌تر اول) هم کسر می‌شود.
    سایر انواع: فقط از همان leave_type.
    """
    remaining = float(days_needed)
    consumed_from: dict = {}

    def _use_from_balance(
        bal: Optional[LeaveBalance],
        lt: str,
        amount: float,
        description: str,
        *,
        year_j: int,
        allow_neg: bool = False,
        bucket_key: Optional[str] = None,
    ) -> float:
        nonlocal remaining
        if amount <= 0 or remaining <= 0:
            return 0.0
        if bal is None and not allow_neg:
            return 0.0
        if bal is None and allow_neg:
            use = remaining
            bal = LeaveBalance(
                user_id=user_id,
                year=year_j,
                leave_type=lt,
                balance=-use,
            )
            db.add(bal)
            remaining = 0.0
            consumed_from[lt] = consumed_from.get(lt, 0) + use
            if bucket_key:
                consumed_from[bucket_key] = consumed_from.get(bucket_key, 0) + use
            db.add(LeaveTransaction(
                user_id=user_id,
                year=year_j,
                leave_type=lt,
                amount=use,
                transaction_type=TX_USE,
                description=description,
                reference_id=reference_id,
            ))
            return use

        available = float(bal.balance)
        if available <= 0 and not allow_neg:
            return 0.0
        if allow_neg:
            use = min(amount, remaining)
        else:
            use = min(amount, remaining, available)
        if use <= 0:
            return 0.0
        bal.balance = float(bal.balance) - use
        remaining -= use
        consumed_from[lt] = consumed_from.get(lt, 0) + use
        if bucket_key:
            consumed_from[bucket_key] = consumed_from.get(bucket_key, 0) + use
        db.add(LeaveTransaction(
            user_id=user_id,
            year=year_j,
            leave_type=lt,
            amount=use,
            transaction_type=TX_USE,
            description=description,
            reference_id=reference_id,
        ))
        return use

    def _consume_al_year(year_j: int, *, allow_neg: bool = False) -> None:
        nonlocal remaining
        if remaining <= 0:
            return
        cw = db.query(LeaveBalance).filter(
            and_(
                LeaveBalance.user_id == user_id,
                LeaveBalance.year == year_j,
                LeaveBalance.leave_type == 'CW',
            )
        ).first()
        cw_days = float(cw.balance) if cw and cw.balance > 0 else 0.0
        buyback_limit = resolve_cw_buyback_limit(db, user_id, year_j)
        buckets = split_cw_buckets(cw_days, buyback_limit)

        if buckets['non_buyback'] > 0 and remaining > 0:
            _use_from_balance(
                cw,
                'CW',
                buckets['non_buyback'],
                f"مصرف ذخیره غیرقابل‌بازخرید سال {year_j} (اولویت ۱)",
                year_j=year_j,
                bucket_key='CW_NON_BUYBACK',
            )

        if remaining > 0:
            main = db.query(LeaveBalance).filter(
                and_(
                    LeaveBalance.user_id == user_id,
                    LeaveBalance.year == year_j,
                    LeaveBalance.leave_type == 'AL',
                )
            ).first()
            if main or allow_neg:
                _use_from_balance(
                    main,
                    'AL',
                    remaining,
                    f"مصرف مرخصی {LEAVE_TYPE_NAMES.get('AL', 'AL')} سال {year_j} (اولویت ۲)",
                    year_j=year_j,
                    allow_neg=allow_neg,
                )

        if remaining > 0:
            cw = db.query(LeaveBalance).filter(
                and_(
                    LeaveBalance.user_id == user_id,
                    LeaveBalance.year == year_j,
                    LeaveBalance.leave_type == 'CW',
                )
            ).first()
            bb_avail = float(cw.balance) if cw and cw.balance > 0 else 0.0
            if buyback_limit is not None:
                bb_avail = min(bb_avail, float(max(0, int(buyback_limit))))
            if bb_avail > 0:
                used_buyback = _use_from_balance(
                    cw,
                    'CW',
                    bb_avail,
                    f"مصرف ذخیره قابل‌بازخرید سال {year_j} (اولویت ۳)",
                    year_j=year_j,
                    bucket_key='CW_BUYBACK',
                )
                _reduce_buyback_after_consume(
                    db,
                    user_id,
                    year_j,
                    used_buyback,
                    prior_limit=buyback_limit,
                )

    if leave_type == 'AL':
        years_to_try = [int(year)]
        try:
            from web.services.leave_balance_overview_service import (
                resolve_user_al_availability,
            )
            avail_info = resolve_user_al_availability(db, user_id, year_j=year)
            if avail_info.get('is_conscript'):
                period_years = [
                    int(y) for y in (avail_info.get('years') or []) if y is not None
                ]
                # سال درخواست اول، سپس سال‌های قدیم‌تر دوره
                others = sorted(
                    (y for y in period_years if y != int(year)),
                    reverse=False,
                )
                years_to_try = [int(year)] + others
        except Exception:
            years_to_try = [int(year)]

        for idx, year_j in enumerate(years_to_try):
            # مانده منفی فقط روی آخرین سال مجاز است
            allow_neg = bool(allow_negative and idx == len(years_to_try) - 1)
            _consume_al_year(year_j, allow_neg=allow_neg)
            if remaining <= 0:
                break
    else:
        main = db.query(LeaveBalance).filter(
            and_(
                LeaveBalance.user_id == user_id,
                LeaveBalance.year == year,
                LeaveBalance.leave_type == leave_type,
            )
        ).first()
        if main or allow_negative:
            _use_from_balance(
                main,
                leave_type,
                remaining,
                f"مصرف مرخصی {LEAVE_TYPE_NAMES.get(leave_type, leave_type)}",
                year_j=year,
                allow_neg=allow_negative,
            )

    if commit:
        db.commit()

    return {
        'success': remaining <= 0,
        'consumed': days_needed - remaining,
        'remaining': max(0, remaining),
        'consumed_from': consumed_from,
    }


def resync_approved_leave_consumption(
    db: Session,
    user_id: str,
    *,
    commit: bool = True,
) -> dict:
    """
    برای درخواست‌های تأییدشده‌ای که تراکنش USE ندارند (مثلاً بعد از
    پاک‌سازی دفترکل هنگام بازسازی قرارداد)، مصرف را دوباره ثبت می‌کند.
    """
    from models.leave_request import LeaveRequest

    approved = (
        db.query(LeaveRequest)
        .filter(
            LeaveRequest.user_id == user_id,
            LeaveRequest.status == 'A',
            LeaveRequest.leave_type.in_(['AL', 'CW', 'SL', 'RL']),
        )
        .order_by(LeaveRequest.id.asc())
        .all()
    )
    synced: List[int] = []
    skipped: List[int] = []
    for req in approved:
        has_use = (
            db.query(LeaveTransaction.id)
            .filter(
                LeaveTransaction.reference_id == req.id,
                LeaveTransaction.transaction_type == TX_USE,
            )
            .first()
        )
        if has_use:
            skipped.append(req.id)
            continue
        days = float(req.days_count or 0)
        if days <= 0 or not req.from_date:
            skipped.append(req.id)
            continue
        year_j = jdatetime.date.fromgregorian(date=req.from_date).year
        if req.leave_type == 'AL':
            consume_leave(
                db,
                user_id,
                year_j,
                days,
                leave_type='AL',
                commit=False,
                reference_id=req.id,
                allow_negative=True,
            )
        else:
            bal = db.query(LeaveBalance).filter(
                and_(
                    LeaveBalance.user_id == user_id,
                    LeaveBalance.year == year_j,
                    LeaveBalance.leave_type == req.leave_type,
                )
            ).first()
            if bal:
                bal.balance = float(bal.balance) - days
            else:
                db.add(LeaveBalance(
                    user_id=user_id,
                    year=year_j,
                    leave_type=req.leave_type,
                    balance=-days,
                ))
            db.add(LeaveTransaction(
                user_id=user_id,
                year=year_j,
                leave_type=req.leave_type,
                amount=days,
                transaction_type=TX_USE,
                description=(
                    f"بازسازی مصرف مرخصی {LEAVE_TYPE_NAMES.get(req.leave_type, req.leave_type)}"
                    f" - درخواست #{req.id}"
                ),
                reference_id=req.id,
            ))
        synced.append(req.id)

    if commit:
        db.commit()
    return {'synced': synced, 'skipped': skipped}
