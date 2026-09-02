"""
سرویس مدیریت شارژ مرخصی بر اساس قرارداد
"""
import math
import logging
from datetime import date, timedelta
from typing import List, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import and_
import jdatetime

from models.contract import Contract
from models.leave_balance import LeaveBalance
from models.leave_transaction import LeaveTransaction

logger = logging.getLogger(__name__)


def get_jalali_year_days(year: int) -> int:
    """تعداد روزهای سال شمسی (365 یا 366)"""
    try:
        jdatetime.date(year, 12, 30)
        return 366  # سال کبیسه
    except ValueError:
        return 365  # سال عادی


def split_contract_by_year(contract: Contract) -> List[Tuple[int, date, date]]:
    """
    🆕 تقسیم قرارداد بر اساس سال‌های شمسی (نسخه اصلاح‌شده)

    Returns:
        لیستی از (سال شمسی, تاریخ شروع میلادی, تاریخ پایان میلادی)
    """
    segments = []

    start_j = jdatetime.date.fromgregorian(date=contract.start_date)

    # قرارداد باز (دائمی)
    if contract.end_date is None:
        segments.append((start_j.year, contract.start_date, None))
        logger.info(f"📅 Contract {contract.id}: Open contract, year {start_j.year}")
        return segments

    end_j = jdatetime.date.fromgregorian(date=contract.end_date)

    # 🆕 پیمایش سال به سال از start تا end
    current_year = start_j.year
    current_start_g = contract.start_date

    while current_year <= end_j.year:
        # پیدا کردن آخرین روز این سال شمسی (اسفند ۲۹ یا ۳۰)
        try:
            year_end_j = jdatetime.date(current_year, 12, 30)
        except ValueError:
            year_end_j = jdatetime.date(current_year, 12, 29)

        year_end_g = year_end_j.togregorian()

        if current_year == end_j.year:
            # سال آخر: پایان = end_date قرارداد
            segment_end_g = contract.end_date
        else:
            # سال‌های دیگر: پایان = پایان سال شمسی
            segment_end_g = year_end_g

        segments.append((current_year, current_start_g, segment_end_g))

        logger.info(
            f"📅 Contract {contract.id}: Year {current_year}, "
            f"from {current_start_g} to {segment_end_g}"
        )

        # شروع سال بعد
        current_year += 1
        if current_year <= end_j.year:
            next_year_start_j = jdatetime.date(current_year, 1, 1)
            current_start_g = next_year_start_j.togregorian()

    return segments


def calculate_prorated_leave_by_year(contract: Contract) -> dict:
    """
    محاسبه مرخصی به نسبت برای هر سال شمسی

    Returns:
        dict: {سال شمسی: {'AL': مقدار, 'SL': مقدار}}
    """
    result = {}
    segments = split_contract_by_year(contract)

    for year_j, start_g, end_g in segments:
        year_days = get_jalali_year_days(year_j)

        # قرارداد باز (دائمی) → مرخصی کامل
        if end_g is None:
            result[year_j] = {
                'AL': float(contract.annual_leave_days),
                'SL': float(contract.sick_leave_days),
            }
            logger.info(
                f"💰 Year {year_j}: Open contract, "
                f"AL={contract.annual_leave_days}, SL={contract.sick_leave_days}"
            )
            continue

        # محاسبه تعداد روزهای این بخش
        duration_days = (end_g - start_g).days + 1

        if duration_days >= year_days:
            # سال کامل → مرخصی کامل
            result[year_j] = {
                'AL': float(contract.annual_leave_days),
                'SL': float(contract.sick_leave_days),
            }
            logger.info(
                f"💰 Year {year_j}: Full year ({duration_days} days), "
                f"AL={contract.annual_leave_days}, SL={contract.sick_leave_days}"
            )
        else:
            # محاسبه به نسبت با round
            ratio = duration_days / year_days
            result[year_j] = {
                'AL': contract.annual_leave_days * ratio,
                'SL': contract.sick_leave_days * ratio,
            }
            logger.info(
                f"💰 Year {year_j}: Prorated ({duration_days}/{year_days} days), "
                f"AL={contract.annual_leave_days * ratio:.2f}, "
                f"SL={contract.sick_leave_days * ratio:.2f}"
            )

    return result


def charge_leave_for_new_contract(db: Session, contract: Contract) -> dict:
    """شارژ مرخصی هنگام ثبت قرارداد جدید"""
    prorated_by_year = calculate_prorated_leave_by_year(contract)
    charged = {}

    logger.info(f"🔍 Charging leave for contract {contract.id}: {prorated_by_year}")

    for year_j, leaves in prorated_by_year.items():
        charged[year_j] = {}

        for leave_type, amount in leaves.items():
            # استفاده از round
            amount_rounded = round(amount)

            logger.info(
                f"📊 Year {year_j}, Type {leave_type}: "
                f"raw={amount:.2f}, rounded={amount_rounded}"
            )

            if amount_rounded <= 0:
                continue

            # بررسی balance موجود
            balance = db.query(LeaveBalance).filter(
                and_(
                    LeaveBalance.user_id == contract.user_id,
                    LeaveBalance.year == year_j,
                    LeaveBalance.leave_type == leave_type
                )
            ).first()

            if balance:
                balance.balance += amount_rounded
                logger.info(f"✅ Updated balance: year={year_j}, new_balance={balance.balance}")
            else:
                balance = LeaveBalance(
                    user_id=contract.user_id,
                    year=year_j,
                    leave_type=leave_type,
                    balance=amount_rounded
                )
                db.add(balance)
                logger.info(f"✅ Created balance: year={year_j}, balance={amount_rounded}")

            # ثبت تراکنش
            tx = LeaveTransaction(
                user_id=contract.user_id,
                year=year_j,
                leave_type=leave_type,
                amount=amount_rounded,
                transaction_type='CHARGE',
                description=f"شارژ مرخصی قرارداد {contract.contract_type_name} - سال {year_j}",
                reference_id=contract.id
            )
            db.add(tx)

            charged[year_j][leave_type] = amount_rounded

    db.commit()
    return charged


def update_leave_for_contract(
    db: Session,
    contract: Contract,
    old_annual_leave: int,
    old_sick_leave: int,
    old_start_date: date,
    old_end_date: date,
    old_deduction: int
) -> dict:
    """بروزرسانی مرخصی هنگام ویرایش قرارداد"""
    old_contract = Contract(
        user_id=contract.user_id,
        contract_type_code=contract.contract_type_code,
        start_date=old_start_date,
        end_date=old_end_date,
        annual_leave_days=old_annual_leave,
        sick_leave_days=old_sick_leave,
        service_deduction_days=old_deduction
    )

    old_prorated = calculate_prorated_leave_by_year(old_contract)
    new_prorated = calculate_prorated_leave_by_year(contract)

    logger.info(f"🔄 Old prorated: {old_prorated}")
    logger.info(f"🔄 New prorated: {new_prorated}")

    all_years = set(list(old_prorated.keys()) + list(new_prorated.keys()))
    changes = {}

    for year_j in all_years:
        old_leaves = old_prorated.get(year_j, {'AL': 0, 'SL': 0})
        new_leaves = new_prorated.get(year_j, {'AL': 0, 'SL': 0})

        for leave_type in ['AL', 'SL']:
            old_val = round(old_leaves.get(leave_type, 0))
            new_val = round(new_leaves.get(leave_type, 0))
            diff = new_val - old_val

            if diff == 0:
                continue

            balance = db.query(LeaveBalance).filter(
                and_(
                    LeaveBalance.user_id == contract.user_id,
                    LeaveBalance.year == year_j,
                    LeaveBalance.leave_type == leave_type
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
                    balance=diff
                )
                db.add(balance)

            tx_type = 'CHARGE' if diff > 0 else 'DEDUCT'
            tx_desc = f"{'افزایش' if diff > 0 else 'کسر'} مرخصی قرارداد {contract.contract_type_name} - سال {year_j}"

            tx = LeaveTransaction(
                user_id=contract.user_id,
                year=year_j,
                leave_type=leave_type,
                amount=abs(diff),
                transaction_type=tx_type,
                description=tx_desc,
                reference_id=contract.id
            )
            db.add(tx)

            if year_j not in changes:
                changes[year_j] = {}
            changes[year_j][leave_type] = diff

    db.commit()
    return changes


def remove_leave_for_contract(db: Session, contract: Contract) -> dict:
    """حذف مرخصی هنگام حذف قرارداد"""
    prorated_by_year = calculate_prorated_leave_by_year(contract)
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
                    LeaveBalance.leave_type == leave_type
                )
            ).first()

            if balance:
                balance.balance -= amount_rounded
                if balance.balance < 0:
                    balance.balance = 0

            tx = LeaveTransaction(
                user_id=contract.user_id,
                year=year_j,
                leave_type=leave_type,
                amount=amount_rounded,
                transaction_type='REVERSE',
                description=f"حذف مرخصی قرارداد {contract.contract_type_name} - سال {year_j}",
                reference_id=contract.id
            )
            db.add(tx)

            removed[year_j][leave_type] = amount_rounded

    db.commit()
    return removed


# ============================================
# 🆕 منطق مصرف مرخصی - استاندارد صنعتی (FIFO معکوس)
# ============================================

LEAVE_TYPE_NAMES = {
    'AL': 'استحقاقی',
    'SL': 'استعلاجی',
    'RL': 'تشویقی',
    'UL': 'بدون حقوق',
    'CW': 'ذخیره سال قبل'
}


def get_available_leave(db: Session, user_id: str, year: int, leave_type: str = 'AL') -> dict:
    """
    🆕 محاسبه مرخصی قابل استفاده (نمایش یکپارچه)
    برای نوع استحقاقی: AL + CW (انتقالی)
    برای سایر انواع: فقط خود نوع

    Returns:
        dict: {'total': مقدار کل, 'breakdown': {نوع: مقدار}}
    """
    result = {'total': 0, 'breakdown': {}}

    # مرخصی اصلی
    main_balance = db.query(LeaveBalance).filter(
        and_(
            LeaveBalance.user_id == user_id,
            LeaveBalance.year == year,
            LeaveBalance.leave_type == leave_type
        )
    ).first()

    if main_balance and main_balance.balance > 0:
        result['breakdown'][leave_type] = main_balance.balance
        result['total'] += main_balance.balance

    # 🆕 برای استحقاقی، انتقالی را هم اضافه کن
    if leave_type == 'AL':
        cw_balance = db.query(LeaveBalance).filter(
            and_(
                LeaveBalance.user_id == user_id,
                LeaveBalance.year == year,
                LeaveBalance.leave_type == 'CW'
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
        leave_type: str = 'AL'
) -> dict:
    """
    🆕 مصرف مرخصی با منطق استاندارد صنعتی:

    اولویت مصرف:
    1. اول از CW (انتقالی) - چون زودتر منقضی می‌شود
    2. سپس از AL (استحقاقی)

    ⚠️ فقط برای نوع استحقاقی (AL) از انتقالی کم می‌شود.
    برای سایر انواع (استعلاجی، تشویقی و...) مستقیماً از خودش کم می‌شود.

    Args:
        db: Session دیتابیس
        user_id: کد کاربر
        year: سال شمسی
        days_needed: تعداد روز مورد نیاز
        leave_type: نوع مرخصی (پیش‌فرض: استحقاقی)

    Returns:
        dict: {
            'success': bool,
            'consumed': float,
            'remaining': float,
            'consumed_from': dict  # {'CW': مقدار, 'AL': مقدار}
        }
    """
    remaining = days_needed
    consumed_from = {}

    # ============================================
    # مرحله ۱: مصرف از انتقالی (فقط برای مرخصی استحقاقی)
    # ============================================
    if leave_type == 'AL':
        cw = db.query(LeaveBalance).filter(
            and_(
                LeaveBalance.user_id == user_id,
                LeaveBalance.year == year,
                LeaveBalance.leave_type == 'CW'
            )
        ).first()

        if cw and cw.balance > 0:
            use_from_cw = min(remaining, cw.balance)
            cw.balance -= use_from_cw
            remaining -= use_from_cw
            consumed_from['CW'] = use_from_cw

            tx = LeaveTransaction(
                user_id=user_id,
                year=year,
                leave_type='CW',
                amount=use_from_cw,
                transaction_type='USE',
                description=f"مصرف مرخصی انتقالی از سال قبل (اولویت اول)"
            )
            db.add(tx)
            logger.info(
                f"📤 Consumed {use_from_cw} days from CW for user {user_id}, "
                f"year {year}. Remaining CW: {cw.balance}"
            )

    # ============================================
    # مرحله ۲: مصرف از مرخصی اصلی
    # ============================================
    if remaining > 0:
        main = db.query(LeaveBalance).filter(
            and_(
                LeaveBalance.user_id == user_id,
                LeaveBalance.year == year,
                LeaveBalance.leave_type == leave_type
            )
        ).first()

        if main and main.balance > 0:
            use_from_main = min(remaining, main.balance)
            main.balance -= use_from_main
            remaining -= use_from_main
            consumed_from[leave_type] = use_from_main

            tx = LeaveTransaction(
                user_id=user_id,
                year=year,
                leave_type=leave_type,
                amount=use_from_main,
                transaction_type='USE',
                description=f"مصرف مرخصی {LEAVE_TYPE_NAMES.get(leave_type, leave_type)}"
            )
            db.add(tx)
            logger.info(
                f"📤 Consumed {use_from_main} days from {leave_type} for user {user_id}, "
                f"year {year}. Remaining {leave_type}: {main.balance}"
            )

    db.commit()

    return {
        'success': remaining <= 0,
        'consumed': days_needed - remaining,
        'remaining': max(0, remaining),
        'consumed_from': consumed_from,
    }