"""
سرویس انتقال مرخصی استفاده نشده به سال بعد
"""
from datetime import datetime
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_
import jdatetime

from models.leave_balance import LeaveBalance
from models.leave_transaction import LeaveTransaction
from models.leave_carry_forward_request import LeaveCarryForwardRequest


# 🆕 کد نوع مرخصی ذخیره
CARRY_FORWARD_LEAVE_TYPE = 'CW'


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


def user_chooses_cash_out(db: Session, user_id: str, leave_type: str = 'AL') -> dict:
    """
    💰 کاربر درخواست بازخرید می‌دهد:
    - 🆕 اعمال سقف بر اساس قرارداد
    - ثبت درخواست در انتظار برای مدیر
    """
    current_year_j = jdatetime.date.today().year
    prev_year = current_year_j - 1

    # 🆕 محاسبه سقف انتقال
    limit_info = calculate_carry_forward_limit(db, user_id, prev_year)
    max_days = limit_info['max_days']

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

    total_days = prev_balance.balance

    # 🆕 بررسی سقف
    if max_days <= 0:
        return {
            'success': False,
            'error': f'نوع قرارداد شما ({limit_info["contract_type_name"]}) اجازه ذخیره یا بازخرید مرخصی را نمی‌دهد.'
        }

    # 🆕 مقدار قابل بازخرید = min(مانده, سقف)
    cash_days = min(total_days, max_days)

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

    # ثبت درخواست با مقدار قابل بازخرید
    request = LeaveCarryForwardRequest(
        user_id=user_id,
        from_year=prev_year,
        to_year=current_year_j,
        leave_type=leave_type,
        days_count=cash_days,
        user_choice='CASH',
        status='P'
    )
    db.add(request)
    db.commit()

    return {
        'success': True,
        'days': cash_days,
        'total_days': total_days,
        'max_days': max_days,
        'request_id': request.id
    }

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


def user_chooses_use_leave(db: Session, user_id: str, leave_type: str = 'AL') -> dict:
    """
    🏖️ کاربر قصد استفاده دارد:
    - مانده سال قبل صفر شود
    - به عنوان مرخصی ذخیره (CW) در سال جدید ثبت شود
    - 🆕 اعمال سقف بر اساس قرارداد
    """
    current_year_j = jdatetime.date.today().year
    prev_year = current_year_j - 1

    # 🆕 محاسبه سقف انتقال
    limit_info = calculate_carry_forward_limit(db, user_id, prev_year)
    max_days = limit_info['max_days']

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

    total_days = prev_balance.balance

    # 🆕 اعمال سقف
    if max_days <= 0:
        # نوع قرارداد اجازه ذخیره نمی‌دهد
        # صفر کردن مانده
        prev_balance.balance = 0

        tx = LeaveTransaction(
            user_id=user_id,
            year=prev_year,
            leave_type=leave_type,
            amount=total_days,
            transaction_type='EXPIRE',
            description=f"سوخت مرخصی سال {prev_year} (نوع قرارداد اجازه ذخیره نمی‌دهد)"
        )
        db.add(tx)
        db.commit()

        return {
            'success': False,
            'error': f'نوع قرارداد شما ({limit_info["contract_type_name"]}) اجازه ذخیره مرخصی را نمی‌دهد. {total_days} روز سوخت شد.'
        }

    # 🆕 مقدار قابل انتقال = min(مانده, سقف)
    transfer_days = min(total_days, max_days)
    burned_days = total_days - transfer_days  # مازاد بر سقف

    # ۲. صفر کردن مانده سال قبل
    prev_balance.balance = 0

    # ۳. تراکنش CF_OUT برای مقدار منتقل شده
    tx_out = LeaveTransaction(
        user_id=user_id,
        year=prev_year,
        leave_type=leave_type,
        amount=transfer_days,
        transaction_type='CF_OUT',
        description=f"انتقال مرخصی به سال {current_year_j} (سقف: {max_days} روز)"
    )
    db.add(tx_out)

    # 🆕 تراکنش EXPIRE برای مازاد بر سقف
    if burned_days > 0:
        tx_expire = LeaveTransaction(
            user_id=user_id,
            year=prev_year,
            leave_type=leave_type,
            amount=burned_days,
            transaction_type='EXPIRE',
            description=f"سوخت مرخصی مازاد بر سقف ({burned_days} روز از {total_days})"
        )
        db.add(tx_expire)

    # ۴. ایجاد/بروزرسانی مانده CW در سال جدید
    cw_balance = db.query(LeaveBalance).filter(
        and_(
            LeaveBalance.user_id == user_id,
            LeaveBalance.year == current_year_j,
            LeaveBalance.leave_type == CARRY_FORWARD_LEAVE_TYPE
        )
    ).first()

    if cw_balance:
        cw_balance.balance += transfer_days
    else:
        cw_balance = LeaveBalance(
            user_id=user_id,
            year=current_year_j,
            leave_type=CARRY_FORWARD_LEAVE_TYPE,
            balance=transfer_days,
            is_carried_forward=True,
            carried_from_year=prev_year
        )
        db.add(cw_balance)

    # ۵. تراکنش CF_IN
    tx_in = LeaveTransaction(
        user_id=user_id,
        year=current_year_j,
        leave_type=CARRY_FORWARD_LEAVE_TYPE,
        amount=transfer_days,
        transaction_type='CF_IN',
        description=f"مرخصی ذخیره از سال {prev_year}"
    )
    db.add(tx_in)

    # ۶. ثبت درخواست
    request = LeaveCarryForwardRequest(
        user_id=user_id,
        from_year=prev_year,
        to_year=current_year_j,
        leave_type=leave_type,
        days_count=transfer_days,
        user_choice='USE',
        status='A',
        processed_at=datetime.now(),
        processed_by=user_id
    )
    db.add(request)

    db.commit()

    return {
        'success': True,
        'days': transfer_days,
        'burned_days': burned_days,
        'max_days': max_days,
    }

def admin_reject_cash_out(db: Session, request_id: int, admin_user_id: str, note: str = "") -> dict:
    """
    🔄 مدیر درخواست بازخرید را رد می‌کند:
    - مانده سال قبل صفر شود
    - به عنوان مرخصی ذخیره (CW) در سال جدید ثبت شود
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

    # 🆕 ایجاد/بروزرسانی مانده CW در سال جدید
    cw_balance = db.query(LeaveBalance).filter(
        and_(
            LeaveBalance.user_id == request.user_id,
            LeaveBalance.year == request.to_year,
            LeaveBalance.leave_type == CARRY_FORWARD_LEAVE_TYPE
        )
    ).first()

    if cw_balance:
        cw_balance.balance += request.days_count
    else:
        cw_balance = LeaveBalance(
            user_id=request.user_id,
            year=request.to_year,
            leave_type=CARRY_FORWARD_LEAVE_TYPE,
            balance=request.days_count,
            is_carried_forward=True,
            carried_from_year=request.from_year
        )
        db.add(cw_balance)

    # تراکنش CF_IN برای سال جدید (با نوع CW)
    tx_in = LeaveTransaction(
        user_id=request.user_id,
        year=request.to_year,
        leave_type=CARRY_FORWARD_LEAVE_TYPE,
        amount=request.days_count,
        transaction_type='CF_IN',
        description=f"مرخصی ذخیره از سال {request.from_year} (رد درخواست بازخرید)"
    )
    db.add(tx_in)

    # بروزرسانی درخواست
    request.status = 'R'
    request.admin_note = note
    request.processed_at = datetime.now()
    request.processed_by = admin_user_id

    db.commit()

    return {'success': True}


# 🆕 سقف پیش‌فرض اگر هیچ قراردادی پیدا نشد
DEFAULT_CARRY_FORWARD_LIMIT = 9


def _get_contract_limit_days(contracts: list, year_start_g, year_end_g) -> tuple:
    """
    🆕 محاسبه روزهای کارکرد و سقف پایه از لیست قراردادها
    Returns: (total_worked_days, base_limit, last_contract_type)
    """
    from models.contract import CONTRACT_TYPES

    total_worked_days = 0
    base_limit = 0
    last_contract_type = None

    for contract in contracts:
        # 🆕 سقف پایه را خارج از شرط بازه تنظیم کن
        # (حتی اگر قرارداد در سال مورد نظر نباشد، نوع قرارداد مهم است)
        type_config = CONTRACT_TYPES.get(contract.contract_type_code, {})
        type_limit = type_config.get('carry_forward_max', 0)

        if type_limit > base_limit:
            base_limit = type_limit
            last_contract_type = contract.contract_type_code

        # محاسبه بازه قرارداد در این سال
        period_start = max(contract.start_date, year_start_g)

        if contract.end_date is None:
            period_end = year_end_g
        else:
            period_end = min(contract.end_date, year_end_g)

        if period_start <= period_end:
            days = (period_end - period_start).days + 1
            total_worked_days += days

    return total_worked_days, base_limit, last_contract_type

def calculate_carry_forward_limit(db: Session, user_id: str, from_year: int) -> dict:
    """
    🆕 محاسبه سقف انتقال مرخصی با اولویت‌بندی قراردادها

    اولویت:
    1. قراردادهای فعال در سال مورد نظر
    2. قرارداد فعال فعلی
    3. آخرین قرارداد ثبت شده
    4. سقف پیش‌فرض
    """
    import jdatetime
    from datetime import date
    from models.contract import Contract, CONTRACT_TYPES

    # بازه سال شمسی مورد نظر (میلادی)
    year_start_j = jdatetime.date(from_year, 1, 1)
    try:
        year_end_j = jdatetime.date(from_year, 12, 30)  # سال کبیسه
    except ValueError:
        year_end_j = jdatetime.date(from_year, 12, 29)  # سال عادی

    year_start_g = year_start_j.togregorian()
    year_end_g = year_end_j.togregorian()

    # تعداد روزهای سال
    year_days = (year_end_g - year_start_g).days + 1

    contracts = []
    source = None  # منبع قرارداد پیدا شده

    # ============================================
    # اولویت ۱: قراردادهای فعال در سال مورد نظر
    # ============================================
    contracts = db.query(Contract).filter(
        Contract.user_id == user_id,
        Contract.start_date <= year_end_g,
        or_(
            Contract.end_date == None,
            Contract.end_date >= year_start_g
        )
    ).all()

    if contracts:
        source = f'قرارداد سال {from_year}'
    else:
        # ============================================
        # اولویت ۲: قرارداد فعال فعلی
        # ============================================
        today_g = date.today()
        contracts = db.query(Contract).filter(
            Contract.user_id == user_id,
            Contract.start_date <= today_g,
            or_(
                Contract.end_date == None,
                Contract.end_date >= today_g
            )
        ).order_by(Contract.start_date.desc()).all()

        if contracts:
            source = 'قرارداد فعال فعلی'
        else:
            # ============================================
            # اولویت ۳: آخرین قرارداد ثبت شده
            # ============================================
            contracts = db.query(Contract).filter(
                Contract.user_id == user_id
            ).order_by(Contract.start_date.desc()).limit(1).all()

            if contracts:
                source = 'آخرین قرارداد ثبت شده'
            else:
                # ============================================
                # اولویت ۴: هیچ قراردادی وجود ندارد
                # ============================================
                return {
                    'max_days': DEFAULT_CARRY_FORWARD_LIMIT,
                    'base_limit': DEFAULT_CARRY_FORWARD_LIMIT,
                    'worked_days': year_days,  # فرض: سال کامل
                    'year_days': year_days,
                    'full_year': True,
                    'contract_type_code': None,
                    'contract_type_name': 'بدون قرارداد (سقف پیش‌فرض)',
                    'source': 'سقف پیش‌فرض',
                }

    # محاسبه روزهای کارکرد و سقف پایه
    total_worked_days, base_limit, last_contract_type = _get_contract_limit_days(
        contracts, year_start_g, year_end_g
    )

    # اگر در سال مورد نظر کارکردی نبود (برای اولویت ۲ و ۳)
    # از کل مدت قرارداد استفاده کن
    if total_worked_days == 0 and contracts:
        for contract in contracts:
            if contract.end_date is None:
                # قرارداد باز → سال کامل
                total_worked_days = year_days
                break
            else:
                days = (contract.end_date - contract.start_date).days + 1
                total_worked_days += min(days, year_days)

    # اگر سقف پایه صفر است
    if base_limit <= 0:
        return {
            'max_days': 0,
            'base_limit': 0,
            'worked_days': total_worked_days,
            'year_days': year_days,
            'full_year': total_worked_days >= year_days,
            'contract_type_code': last_contract_type,
            'contract_type_name': CONTRACT_TYPES.get(last_contract_type, {}).get('name', 'نامشخص'),
            'source': source,
        }

    # محاسبه سقف به نسبت کارکرد
    if total_worked_days >= year_days:
        # سال کامل → سقف کامل
        final_limit = base_limit
        full_year = True
    else:
        # به نسبت کارکرد
        ratio = total_worked_days / year_days
        final_limit = round(base_limit * ratio)
        full_year = False

    return {
        'max_days': final_limit,
        'base_limit': base_limit,
        'worked_days': total_worked_days,
        'year_days': year_days,
        'full_year': full_year,
        'contract_type_code': last_contract_type,
        'contract_type_name': CONTRACT_TYPES.get(last_contract_type, {}).get('name', 'نامشخص'),
        'source': source,
    }