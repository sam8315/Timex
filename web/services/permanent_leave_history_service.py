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
    TX_CHARGE,
    TX_CF_OUT,
    TX_DEDUCT,
    TX_USE,
)
from web.services.leave_entitlement_service import (
    charge_amount_for_segment,
    jalali_year_bounds_g,
    resolve_annual_leave_days,
    resolve_max_buyback,
    resolve_max_carry_forward,
    resolve_region_code_from_service_location,
)
from web.services import membership_semantics as msem
from web.services.leave_service import (
    get_buyback_quota,
    get_stored_leave_balance,
    set_buyback_quota_for_year,
    set_stored_leave_for_year,
)

HISTORY_PREFIX = "تاریخچه رسمی#"


def _history_desc(kind: str, year_j: int) -> str:
    return f"{HISTORY_PREFIX}{kind} سال {year_j}"


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
    permanent_code = "1"
    for mt_code in ("1",):
        if msem.is_permanent(db, mt_code):
            permanent_code = mt_code
            break
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
        bal.balance = max(0, int(bal.balance) + delta)
    elif delta > 0:
        db.add(LeaveBalance(
            user_id=user_id,
            year=year,
            leave_type=leave_type,
            balance=delta,
        ))


def clear_permanent_history(db: Session, contract: Contract) -> None:
    """حذف اثر تراکنش‌های تاریخچه قبلی این قرارداد و خود تراکنش‌ها."""
    txs = (
        db.query(LeaveTransaction)
        .filter(
            LeaveTransaction.reference_id == contract.id,
            LeaveTransaction.description.like(f"{HISTORY_PREFIX}%"),
        )
        .order_by(LeaveTransaction.id.asc())
        .all()
    )
    for tx in txs:
        amount = int(tx.amount or 0)
        if tx.transaction_type == TX_CHARGE:
            _adjust_balance(
                db, user_id=contract.user_id, year=tx.year,
                leave_type=tx.leave_type, delta=-amount,
            )
        elif tx.transaction_type in (TX_USE, TX_CF_OUT, TX_DEDUCT):
            _adjust_balance(
                db, user_id=contract.user_id, year=tx.year,
                leave_type=tx.leave_type, delta=amount,
            )
        db.delete(tx)
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
    if contract.contract_type_code != MEMBERSHIP_PERMANENT:
        raise ValueError("تاریخچه فقط برای عضویت رسمی است")

    clear_permanent_history(db, contract)

    region_code = resolve_region_code_from_service_location(db, contract.user_id)
    plan = build_year_plan(
        db, user_id=contract.user_id, start_date=contract.start_date, region_code=region_code
    )
    cf_cap = resolve_max_carry_forward(db, MEMBERSHIP_PERMANENT)
    buyback_cap = resolve_max_buyback(
        db, MEMBERSHIP_PERMANENT, user_id=contract.user_id, region_code=region_code
    )

    stored = 0
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

        applied.append({
            'year': year_j,
            'entitlement': entitlement,
            'used': used,
            'carried': (entitlement - used) if cf_cap is None else min(entitlement - used, int(cf_cap or 0)),
        })

    current_year = jdatetime.date.today().year
    cw_result = set_stored_leave_for_year(
        db,
        user_id=contract.user_id,
        year=current_year,
        target_days=stored,
        reference_id=contract.id,
        description=f"{HISTORY_PREFIX}تنظیم ذخیره از تاریخچه قرارداد #{contract.id}",
        commit=False,
    )

    if buyback_cap is None:
        bb_days = stored
    else:
        bb_days = min(stored, int(buyback_cap))
    bb_result = set_buyback_quota_for_year(
        db,
        user_id=contract.user_id,
        year=current_year,
        target_days=bb_days,
        source='MANUAL',
        notes=f"{HISTORY_PREFIX}از تاریخچه قرارداد #{contract.id}",
        commit=False,
    )

    if commit:
        db.commit()

    return {
        'years': applied,
        'stored_cw': cw_result['new'],
        'buyback': bb_result['new'],
        'carry_forward_cap': cf_cap,
        'buyback_cap': buyback_cap,
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
    cf_cap = resolve_max_carry_forward(db, MEMBERSHIP_PERMANENT)
    buyback_cap = resolve_max_buyback(
        db, MEMBERSHIP_PERMANENT, user_id=user_id, region_code=region_code
    )
    stored = 0
    years = []
    for row in plan:
        year_j = row['year']
        entitlement = int(row['entitlement'])
        used = int(used_by_year.get(year_j, 0) or 0)
        used = max(0, min(used, entitlement))
        unused = entitlement - used
        carry = unused if cf_cap is None else min(unused, int(cf_cap))
        stored += carry
        years.append({
            'year': year_j,
            'entitlement': entitlement,
            'used': used,
            'carry': carry,
        })
    bb = stored if buyback_cap is None else min(stored, int(buyback_cap))
    return {
        'years': years,
        'stored_cw': stored,
        'buyback': bb,
        'carry_forward_cap': cf_cap,
        'buyback_cap': buyback_cap,
        'region_code': region_code,
    }
