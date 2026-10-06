"""
ورود/ویرایش تاریخچه مرخصی برای قرارداد رسمی قدیمی.

ورودی هر سال گذشته: مصرف‌شده؛ استحقاق از سیاست؛ ثبت CHARGE+USE در دفترکل؛
مانده با سقف انتقال به CW سال جاری و سهمیه بازخرید ماده ۱۱.
"""
from __future__ import annotations

from datetime import date
from typing import Dict, List, Optional

import jdatetime
from sqlalchemy import and_
from sqlalchemy.orm import Session

from models.contract import Contract
from models.employee import Employee
from models.leave_balance import LeaveBalance
from models.leave_transaction import LeaveTransaction
from models.leave_glossary import (
    LEAVE_TYPE_AL,
    LEAVE_TYPE_CW,
    TX_ADJUST,
    TX_BURN,
    TX_CASH_OUT,
    TX_CF_IN,
    TX_CF_OUT,
    TX_CHARGE,
    TX_DEDUCT,
    TX_IMPORT,
    TX_REVERSE,
    TX_USE,
)
from web.services.leave_entitlement_service import (
    charge_amount_for_segment,  # delegates to Pure Engine (live annual history path)
    jalali_year_bounds_g,
    resolve_annual_leave_days,
    resolve_region_code_from_service_location,
)
from web.services import membership_semantics as msem
from web.services.leave_settlement.caps import resolve_settlement_caps
from web.services.leave_service import (
    get_buyback_quota,
    get_stored_leave_balance,
    resync_approved_leave_consumption,
    set_buyback_quota_for_year,
)

HISTORY_PREFIX = "تاریخچه رسمی#"


def _history_desc(kind: str, year_j: int) -> str:
    return f"{HISTORY_PREFIX}{kind} سال {year_j}"


def _resolve_permanent_code(db: Session) -> str:
    """
    کد عضویت با behavior_profile=permanent برای مسیر تاریخچه.
    الگوی Membership Foundation (هم‌خوان با build_year_plan).
    """
    permanent_code = "1"
    for mt_code in ("1",):
        if msem.is_permanent(db, mt_code):
            permanent_code = mt_code
            break
    return permanent_code


def build_year_plan(
    db: Session,
    *,
    user_id: str,
    start_date: date,
    region_code: Optional[str] = None,
) -> List[dict]:
    """
    سال‌های گذشته از استخدام تا قبل از سال جاری + استحقاق محاسبه‌شده.
    """
    start_j = jdatetime.date.fromgregorian(date=start_date)
    current_year = jdatetime.date.today().year
    if not region_code:
        region_code = resolve_region_code_from_service_location(db, user_id)
    # تاریخچه فقط برای profile=permanent معنا دارد؛ code از caller/contract می‌آید
    permanent_code = _resolve_permanent_code(db)
    annual = float(resolve_annual_leave_days(db, permanent_code, region_code=region_code))

    rows = []
    for year_j in range(start_j.year, current_year):
        y_start, y_end = jalali_year_bounds_g(year_j)
        seg_start = max(start_date, y_start)
        if seg_start > y_end:
            continue
        raw = charge_amount_for_segment(
            permanent_code, annual, year_j, seg_start, y_end, db=db
        )
        entitlement = max(0, round(raw))
        rows.append({
            'year': year_j,
            'entitlement': entitlement,
            'used': 0,
        })
    return rows


def get_used_by_year_from_contract(db: Session, contract_id: int) -> Dict[int, int]:
    """مصرف ثبت‌شده از تراکنش‌های USE تاریخچه همین قرارداد."""
    rows = (
        db.query(LeaveTransaction)
        .filter(
            LeaveTransaction.reference_id == contract_id,
            LeaveTransaction.transaction_type == TX_USE,
            LeaveTransaction.leave_type == LEAVE_TYPE_AL,
            LeaveTransaction.description.like(f"{HISTORY_PREFIX}%"),
        )
        .all()
    )
    out: Dict[int, int] = {}
    for tx in rows:
        out[tx.year] = out.get(tx.year, 0) + int(tx.amount or 0)
    return out


def _adjust_balance(
    db: Session,
    *,
    user_id: str,
    year: int,
    leave_type: str,
    delta: int,
) -> None:
    if delta == 0:
        return
    bal = db.query(LeaveBalance).filter(
        and_(
            LeaveBalance.user_id == user_id,
            LeaveBalance.year == year,
            LeaveBalance.leave_type == leave_type,
        )
    ).first()
    if bal:
        # بدون clamp: clear/reapply باید CHARGE را کامل برگرداند
        bal.balance = int(bal.balance or 0) + int(delta)
    elif delta != 0:
        db.add(LeaveBalance(
            user_id=user_id,
            year=year,
            leave_type=leave_type,
            balance=int(delta),
        ))


def _tx_signed_delta(tx: LeaveTransaction) -> int:
    """اثر تراکنش روی مانده همان سطل (leave_type/year)."""
    amount = int(tx.amount or 0)
    t = tx.transaction_type
    if t in (TX_CHARGE, TX_CF_IN, TX_IMPORT):
        return amount
    if t in (TX_USE, TX_CF_OUT, TX_DEDUCT, TX_REVERSE, TX_BURN, TX_CASH_OUT):
        return -amount
    if t == TX_ADJUST:
        return amount
    return 0


def _rebuild_balance_from_ledger(
    db: Session,
    *,
    user_id: str,
    year: int,
    leave_type: str,
) -> None:
    """بازنویسی LeaveBalance از جمع تراکنش‌های باقی‌مانده."""
    txs = (
        db.query(LeaveTransaction)
        .filter(
            LeaveTransaction.user_id == user_id,
            LeaveTransaction.year == year,
            LeaveTransaction.leave_type == leave_type,
        )
        .all()
    )
    total = sum(_tx_signed_delta(tx) for tx in txs)
    bal = db.query(LeaveBalance).filter(
        and_(
            LeaveBalance.user_id == user_id,
            LeaveBalance.year == year,
            LeaveBalance.leave_type == leave_type,
        )
    ).first()
    if bal:
        bal.balance = total
    elif total != 0:
        db.add(LeaveBalance(
            user_id=user_id,
            year=year,
            leave_type=leave_type,
            balance=total,
        ))


def clear_permanent_history(db: Session, contract: Contract) -> None:
    """حذف تراکنش‌های تاریخچه این قرارداد و بازسازی مانده از دفترکل باقی‌مانده."""
    txs = (
        db.query(LeaveTransaction)
        .filter(
            LeaveTransaction.reference_id == contract.id,
            LeaveTransaction.description.like(f"{HISTORY_PREFIX}%"),
        )
        .order_by(LeaveTransaction.id.asc())
        .all()
    )
    touched = {(tx.year, tx.leave_type) for tx in txs}
    for tx in txs:
        db.delete(tx)
    db.flush()
    for year, leave_type in touched:
        _rebuild_balance_from_ledger(
            db,
            user_id=contract.user_id,
            year=year,
            leave_type=leave_type,
        )
    db.flush()


def apply_permanent_history(
    db: Session,
    contract: Contract,
    used_by_year: Dict[int, int],
    *,
    commit: bool = True,
) -> dict:
    """
    اعمال تاریخچه برای سال‌های قبل از سال جاری.
    Returns: {years: [...], stored_cw, buyback, errors}
    """
    if not msem.is_permanent(db, contract.contract_type_code):
        raise ValueError("تاریخچه فقط برای عضویت رسمی است")

    clear_permanent_history(db, contract)

    region_code = resolve_region_code_from_service_location(db, contract.user_id)
    plan = build_year_plan(
        db, user_id=contract.user_id, start_date=contract.start_date, region_code=region_code
    )
    membership_code = contract.contract_type_code

    stored = 0
    buybackable = 0
    applied = []
    for row in plan:
        year_j = row['year']
        entitlement = int(row['entitlement'])
        used = int(used_by_year.get(year_j, 0) or 0)
        if used < 0:
            raise ValueError(f"مصرف سال {year_j} نمی‌تواند منفی باشد")
        if used > entitlement:
            raise ValueError(
                f"مصرف سال {year_j} ({used}) بیشتر از استحقاق ({entitlement}) است"
            )

        year_caps = resolve_settlement_caps(
            db,
            membership_code,
            region_code=region_code,
            user_id=contract.user_id,
            year_j=year_j,
        )
        cf_cap = year_caps.get('storage_cap')
        bb_cap = year_caps.get('buyback_cap')

        if entitlement > 0:
            _adjust_balance(
                db, user_id=contract.user_id, year=year_j,
                leave_type=LEAVE_TYPE_AL, delta=entitlement,
            )
            db.add(LeaveTransaction(
                user_id=contract.user_id,
                year=year_j,
                leave_type=LEAVE_TYPE_AL,
                amount=entitlement,
                transaction_type=TX_CHARGE,
                description=_history_desc("شارژ", year_j),
                reference_id=contract.id,
            ))

        if used > 0:
            _adjust_balance(
                db, user_id=contract.user_id, year=year_j,
                leave_type=LEAVE_TYPE_AL, delta=-used,
            )
            db.add(LeaveTransaction(
                user_id=contract.user_id,
                year=year_j,
                leave_type=LEAVE_TYPE_AL,
                amount=used,
                transaction_type=TX_USE,
                description=_history_desc("مصرف", year_j),
                reference_id=contract.id,
            ))

        unused = entitlement - used
        carry = 0
        year_bb = 0
        if unused > 0:
            carry = unused if cf_cap is None else min(unused, int(cf_cap))
            # خروج از AL سال گذشته
            _adjust_balance(
                db, user_id=contract.user_id, year=year_j,
                leave_type=LEAVE_TYPE_AL, delta=-carry,
            )
            db.add(LeaveTransaction(
                user_id=contract.user_id,
                year=year_j,
                leave_type=LEAVE_TYPE_AL,
                amount=carry,
                transaction_type=TX_CF_OUT,
                description=_history_desc("انتقال‌به‌ذخیره", year_j),
                reference_id=contract.id,
            ))
            stored += carry
            year_bb = carry if bb_cap is None else min(carry, int(bb_cap))
            buybackable += year_bb

        applied.append({
            'year': year_j,
            'entitlement': entitlement,
            'used': used,
            'carried': carry,
            'buybackable': year_bb,
            'storage_cap': cf_cap,
            'buyback_cap': bb_cap,
        })

    current_year = jdatetime.date.today().year
    # CHARGE خالص تاریخچه (نه set مطلق) تا USEهای موجود در دفترکل حفظ شوند
    if stored > 0:
        db.add(LeaveTransaction(
            user_id=contract.user_id,
            year=current_year,
            leave_type=LEAVE_TYPE_CW,
            amount=stored,
            transaction_type=TX_CHARGE,
            description=(
                f"{HISTORY_PREFIX}تنظیم ذخیره از تاریخچه قرارداد #{contract.id}"
            ),
            reference_id=contract.id,
        ))
    db.flush()
    _rebuild_balance_from_ledger(
        db,
        user_id=contract.user_id,
        year=current_year,
        leave_type=LEAVE_TYPE_CW,
    )

    current_caps = resolve_settlement_caps(
        db,
        membership_code,
        region_code=region_code,
        user_id=contract.user_id,
        year_j=current_year,
    )
    bb_result = set_buyback_quota_for_year(
        db,
        user_id=contract.user_id,
        year=current_year,
        target_days=buybackable,
        source='MANUAL',
        notes=f"{HISTORY_PREFIX}از تاریخچه قرارداد #{contract.id}",
        commit=False,
    )

    # درخواست‌های تأییدشده‌ای که USEشان با پاک‌سازی دفترکل از بین رفته
    resync = resync_approved_leave_consumption(
        db, contract.user_id, commit=False
    )
    db.flush()

    # هم‌ترازی نهایی مانده با دفترکل
    years_to_rebuild = {row['year'] for row in applied} | {current_year}
    for year_j in years_to_rebuild:
        _rebuild_balance_from_ledger(
            db, user_id=contract.user_id, year=year_j, leave_type=LEAVE_TYPE_AL,
        )
    _rebuild_balance_from_ledger(
        db, user_id=contract.user_id, year=current_year, leave_type=LEAVE_TYPE_CW,
    )
    for extra_lt in ('SL', 'RL'):
        _rebuild_balance_from_ledger(
            db, user_id=contract.user_id, year=current_year, leave_type=extra_lt,
        )
    db.flush()

    cw_final = get_stored_leave_balance(db, contract.user_id, current_year)

    if commit:
        db.commit()

    return {
        'years': applied,
        'stored_cw': cw_final,
        'buyback': bb_result['new'],
        'carry_forward_cap': current_caps.get('storage_cap'),
        'buyback_cap': current_caps.get('buyback_cap'),
        'resynced_leave_requests': resync.get('synced') or [],
        'history_stored_cw': stored,
    }


def parse_used_by_year_from_form(form) -> Dict[int, int]:
    """استخراج used_1400 و مشابه از فرم."""
    out: Dict[int, int] = {}
    for key in form.keys():
        if not str(key).startswith('used_'):
            continue
        try:
            year = int(str(key).split('_', 1)[1])
            raw = form.get(key)
            out[year] = int(float(str(raw or '0').strip() or '0'))
        except (TypeError, ValueError):
            continue
    return out


def preview_history_summary(
    db: Session,
    *,
    user_id: str,
    start_date: date,
    used_by_year: Optional[Dict[int, int]] = None,
) -> dict:
    """پیش‌نمایش بدون نوشتن در DB."""
    used_by_year = used_by_year or {}
    region_code = resolve_region_code_from_service_location(db, user_id)
    plan = build_year_plan(
        db, user_id=user_id, start_date=start_date, region_code=region_code
    )
    membership_code = _resolve_permanent_code(db)
    stored = 0
    buybackable = 0
    years = []
    for row in plan:
        year_j = row['year']
        entitlement = int(row['entitlement'])
        used = int(used_by_year.get(year_j, 0) or 0)
        used = max(0, min(used, entitlement))
        unused = entitlement - used
        year_caps = resolve_settlement_caps(
            db,
            membership_code,
            region_code=region_code,
            user_id=user_id,
            year_j=year_j,
        )
        cf_cap = year_caps.get('storage_cap')
        bb_cap = year_caps.get('buyback_cap')
        carry = unused if cf_cap is None else min(unused, int(cf_cap))
        year_bb = carry if bb_cap is None else min(carry, int(bb_cap))
        stored += carry
        buybackable += year_bb
        years.append({
            'year': year_j,
            'entitlement': entitlement,
            'used': used,
            'carry': carry,
            'buybackable': year_bb,
            'storage_cap': cf_cap,
            'buyback_cap': bb_cap,
        })
    current_year = jdatetime.date.today().year
    current_caps = resolve_settlement_caps(
        db,
        membership_code,
        region_code=region_code,
        user_id=user_id,
        year_j=current_year,
    )
    return {
        'years': years,
        'stored_cw': stored,
        'buyback': buybackable,
        'carry_forward_cap': current_caps.get('storage_cap'),
        'buyback_cap': current_caps.get('buyback_cap'),
        'region_code': region_code,
    }
