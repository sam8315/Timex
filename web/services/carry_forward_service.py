"""
سرویس انتقال مرخصی استفاده نشده به سال بعد
"""
from datetime import datetime, date, timedelta
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_
import jdatetime

from models.leave_balance import LeaveBalance
from models.leave_transaction import LeaveTransaction
from models.leave_carry_forward_request import LeaveCarryForwardRequest
from models.contract import Contract
from models.employee import Employee

# 🆕 کد نوع مرخصی ذخیره
CARRY_FORWARD_LEAVE_TYPE = 'CW'

# 🆕 سقف پیش‌فرض اگر هیچ قراردادی پیدا نشد
DEFAULT_CARRY_FORWARD_LIMIT = 9


def _membership_name(db: Session, code) -> str:
    if not code:
        return 'نامشخص'
    try:
        from web.services.membership_service import get_membership_type
        mt = get_membership_type(db, str(code))
        if mt:
            return mt.name
    except Exception:
        pass
    return f'نامشخص ({code})'


# ============================================
# 📊 توابع تحلیلی
# ============================================

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


def _get_employment_type(employee, db=None, on_date=None) -> str:
    """سطل سازگاری انتقال مانده از کد عضویت، نه از دپارتمان."""
    from web.services.membership_resolve import membership_code_for
    from web.services import membership_semantics as msem

    code = None
    if db is not None and employee is not None:
        code = membership_code_for(db, employee, on_date or date.today())
    elif employee is not None:
        code = getattr(employee, "membership_type_code", None)
    if not code or db is None:
        return "UNRESOLVED"
    if msem.is_permanent(db, code):
        return "PERMANENT"
    if msem.is_conscript(db, code):
        return "CONSCRIPT"
    if msem.is_physician(db, code):
        return "PHYSICIAN"
    if str(code) == "3":
        return "CONTRACTOR"
    if str(code) == "4":
        return "LABOR_LAW"
    return "LABOR_LAW"


def _get_year_range_g(year: int) -> tuple:
    """🆕 محاسبه بازه میلادی یک سال شمسی"""
    year_start_j = jdatetime.date(year, 1, 1)
    try:
        year_end_j = jdatetime.date(year, 12, 30)  # سال کبیسه
    except ValueError:
        year_end_j = jdatetime.date(year, 12, 29)  # سال عادی
    return year_start_j.togregorian(), year_end_j.togregorian()


def _was_employee_active_in_year(db: Session, user_id: str, year: int) -> bool:
    """
    🆕 بررسی اینکه آیا کارمند در سال مشخص فعال بوده است
    بر اساس تاریخ استخدام و ترک کار
    """
    employee = db.query(Employee).filter(Employee.user_id == user_id).first()
    if not employee:
        return False

    year_start_g, year_end_g = _get_year_range_g(year)

    # اگر تاریخ استخدام ندارد، فرض کن فعال بوده
    if not employee.hire_date:
        return True

    # اگر بعد از پایان سال استخدام شده → فعال نبوده
    if employee.hire_date > year_end_g:
        return False

    # اگر قبل از شروع سال ترک کار کرده → فعال نبوده
    if employee.termination_date and employee.termination_date < year_start_g:
        return False

    # در غیر این صورت فعال بوده
    return True


def analyze_yearly_contracts(db, user_id: str, year: int) -> dict:
    """
    🆕 تحلیل همه قراردادهای یک کاربر در سال مشخص
    🐛 اصلاح شده: اگر قرارداد نباشد ولی کارمند فعال باشد، کل سال در نظر گرفته می‌شود
    """
    year_start_g, year_end_g = _get_year_range_g(year)
    year_total_days = (year_end_g - year_start_g).days + 1

    contracts = db.query(Contract).filter(
        and_(
            Contract.user_id == user_id,
            Contract.start_date <= year_end_g,
            or_(
                Contract.end_date == None,
                Contract.end_date >= year_start_g
            )
        )
    ).order_by(Contract.start_date).all()

    if not contracts:
        employee = db.query(Employee).filter(Employee.user_id == user_id).first()
        employment_type = _get_employment_type(employee, db, year_end_g)

        # 🆕 اصلاح: بررسی فعال بودن کارمند در سال مورد نظر
        if _was_employee_active_in_year(db, user_id, year):
            # ✅ کارمند فعال بوده ولی قرارداد ثبت نشده
            # → فرض می‌کنیم کل سال قرارداد فعال داشته
            return {
                'contracts_count': 0,
                'total_days': year_total_days,
                'covers_full_year': True,
                'employment_type': employment_type,
                'has_gap': False,
                'contracts': [],
                'assumed_full_year': True,  # 🆕 علامت‌گذاری
            }
        else:
            # ❌ کارمند در آن سال فعال نبوده
            return {
                'contracts_count': 0,
                'total_days': 0,
                'covers_full_year': False,
                'employment_type': employment_type,
                'has_gap': False,
                'contracts': [],
                'assumed_full_year': False,
            }

    # محاسبه مجموع روزهای کارکرد (با حذف هم‌پوشانی)
    covered_days = set()
    for c in contracts:
        start = max(c.start_date, year_start_g)
        end = min(c.end_date or year_end_g, year_end_g)
        current = start
        while current <= end:
            covered_days.add(current)
            current += timedelta(days=1)

    total_days = len(covered_days)
    covers_full_year = total_days >= year_total_days - 5

    # بررسی فاصله بین قراردادها
    has_gap = False
    for i in range(1, len(contracts)):
        prev_end = contracts[i - 1].end_date or year_end_g
        curr_start = contracts[i].start_date
        if (curr_start - prev_end).days > 1:
            has_gap = True
            break

    # نوع استخدام: پرتکرارترین نوع قراردادها
    type_counts = {}
    for c in contracts:
        c_type = getattr(c, 'contract_type', None) or getattr(c, 'contract_type_code', None)
        if c_type:
            type_counts[c_type] = type_counts.get(c_type, 0) + 1

    employee = db.query(Employee).filter(Employee.user_id == user_id).first()
    if type_counts:
        employment_type = max(type_counts, key=type_counts.get)
    else:
        employment_type = _get_employment_type(employee, db, year_end_g)

    return {
        'contracts_count': len(contracts),
        'total_days': total_days,
        'covers_full_year': covers_full_year,
        'employment_type': employment_type,
        'has_gap': has_gap,
        'contracts': contracts,
        'assumed_full_year': False,
    }


def calculate_leave_ceiling(year: int, employment_type: str, grade: int = 1) -> dict:
    """
    محاسبه سقف ذخیره و بازخرید بر اساس سال و نوع استخدام
    """
    if employment_type == 'PERMANENT':  # رسمی
        if year <= 1389:
            return {'max_carry_forward': 9, 'max_buyback': None}
        elif 1390 <= year <= 1398:
            return {'max_carry_forward': 9, 'max_buyback': 15}
        else:  # >= 1399
            buyback_limits = {1: 15, 2: 18, 3: 20, 4: 22}
            return {'max_carry_forward': 9, 'max_buyback': buyback_limits.get(grade, 15)}

    elif employment_type == 'LABOR_LAW':  # قراردادی اداره کار
        return {'max_carry_forward': 9, 'max_buyback': None}

    elif employment_type == 'CONSCRIPT':  # وظیفه
        return {'max_carry_forward': 0, 'max_buyback': 0}

    else:
        return {'max_carry_forward': 0, 'max_buyback': 0}


# ============================================
# 🆕 توابع کمکی برای calculate_carry_forward_limit
# ============================================

def _get_contract_limit_days(
    contracts: list, year_start_g, year_end_g, db=None, year_j: int | None = None
) -> tuple:
    """
    محاسبه روزهای کارکرد و سقف پایه از لیست قراردادها (+ سیاست در صورت وجود).
    Returns: (total_worked_days, base_limit, last_contract_type)
    base_limit=None یعنی بدون سقف سیاستی.
    """
    from web.services.leave_settlement import resolve_storage_cap

    total_worked_days = 0
    base_limit = 0
    last_contract_type = None
    unlimited = False

    for contract in contracts:
        if db is not None:
            policy_cap = resolve_storage_cap(
                db, contract.contract_type_code, year_j=year_j
            )
            if policy_cap is None:
                unlimited = True
                type_limit = None
            else:
                type_limit = policy_cap
        else:
            # بدون DB: fallback سراسری 0 (نه per-code hardcode)
            type_limit = 0

        if type_limit is None:
            last_contract_type = contract.contract_type_code
        elif type_limit > (base_limit or 0):
            base_limit = type_limit
            last_contract_type = contract.contract_type_code
        elif last_contract_type is None:
            last_contract_type = contract.contract_type_code

        period_start = max(contract.start_date, year_start_g)
        if contract.end_date is None:
            period_end = year_end_g
        else:
            period_end = min(contract.end_date, year_end_g)

        if period_start <= period_end:
            days = (period_end - period_start).days + 1
            total_worked_days += days

    if unlimited:
        return total_worked_days, None, last_contract_type
    return total_worked_days, base_limit, last_contract_type


def calculate_carry_forward_limit(db: Session, user_id: str, from_year: int) -> dict:
    """
    🐛 اصلاح شده: محاسبه سقف انتقال مرخصی با اولویت‌بندی قراردادها
    اگر هیچ قراردادی نباشد ولی کارمند فعال باشد، کل سال در نظر گرفته می‌شود
    """
    year_start_g, year_end_g = _get_year_range_g(from_year)
    year_days = (year_end_g - year_start_g).days + 1

    contracts = []
    source = None

    # اولویت ۱: قراردادهای فعال در سال مورد نظر
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
        # 🆕 اصلاح: به جای رفتن به اولویت‌های بعدی،
        # بررسی کن آیا کارمند در آن سال فعال بوده یا نه
        employee = db.query(Employee).filter(Employee.user_id == user_id).first()
        employment_type = _get_employment_type(employee, db, year_end_g)

        if _was_employee_active_in_year(db, user_id, from_year):
            from web.services.leave_settlement import resolve_storage_cap
            from web.services.membership_resolve import resolve_employee_membership
            resolution = resolve_employee_membership(db, user_id, year_end_g)
            emp_code = resolution.code
            if not emp_code:
                return {
                    'max_days': 0,
                    'base_limit': 0,
                    'unlimited': False,
                    'worked_days': year_days,
                    'year_days': year_days,
                    'full_year': True,
                    'contract_type_code': None,
                    'contract_type_name': 'عضویت نامشخص',
                    'source': f'بدون عضویت قابل‌تشخیص برای سال {from_year}',
                    'assumed_full_year': True,
                    'employment_type': 'UNRESOLVED',
                    'unresolved_membership': True,
                }
            policy_cap = resolve_storage_cap(db, emp_code, year_j=from_year)
            return {
                'max_days': policy_cap if policy_cap is not None else year_days,
                'base_limit': policy_cap,
                'unlimited': policy_cap is None,
                'worked_days': year_days,
                'year_days': year_days,
                'full_year': True,
                'contract_type_code': None,
                'contract_type_name': f'بدون قرارداد ({employment_type})',
                'source': f'فرض قرارداد فعال برای کل سال {from_year}',
                'assumed_full_year': True,
                'employment_type': employment_type,
            }
        else:
            # ❌ کارمند فعال نبوده → سقف صفر
            return {
                'max_days': 0,
                'base_limit': 0,
                'worked_days': 0,
                'year_days': year_days,
                'full_year': False,
                'contract_type_code': None,
                'contract_type_name': 'غیرفعال',
                'source': 'کارمند در این سال فعال نبوده',
                'assumed_full_year': False,
            }

    # محاسبه روزهای کارکرد و سقف پایه
    total_worked_days, base_limit, last_contract_type = _get_contract_limit_days(
        contracts, year_start_g, year_end_g, db=db, year_j=from_year
    )

    # اگر در سال مورد نظر کارکردی نبود
    if total_worked_days == 0 and contracts:
        for contract in contracts:
            if contract.end_date is None:
                total_worked_days = year_days
                break
            else:
                days = (contract.end_date - contract.start_date).days + 1
                total_worked_days += min(days, year_days)

    # بدون سقف سیاستی → عملاً تا سقف کارکرد سال (بدون برش عددی سیاست)
    if base_limit is None:
        return {
            'max_days': total_worked_days if total_worked_days > 0 else year_days,
            'base_limit': None,
            'unlimited': True,
            'worked_days': total_worked_days,
            'year_days': year_days,
            'full_year': total_worked_days >= year_days,
            'contract_type_code': last_contract_type,
            'contract_type_name': _membership_name(db, last_contract_type),
            'source': source,
        }

    if base_limit <= 0:
        return {
            'max_days': 0,
            'base_limit': 0,
            'unlimited': False,
            'worked_days': total_worked_days,
            'year_days': year_days,
            'full_year': total_worked_days >= year_days,
            'contract_type_code': last_contract_type,
            'contract_type_name': _membership_name(db, last_contract_type),
            'source': source,
        }

    # محاسبه سقف به نسبت کارکرد
    if total_worked_days >= year_days:
        final_limit = base_limit
        full_year = True
    else:
        ratio = total_worked_days / year_days
        final_limit = round(base_limit * ratio)
        full_year = False

    return {
        'max_days': final_limit,
        'base_limit': base_limit,
        'unlimited': False,
        'worked_days': total_worked_days,
        'year_days': year_days,
        'full_year': full_year,
        'contract_type_code': last_contract_type,
        'contract_type_name': _membership_name(db, last_contract_type),
        'source': source,
    }


# ============================================
# 🔄 عملیات کاربر
# ============================================

def user_chooses_cash_out(db, user_id: str, leave_type: str = 'AL', year: int = None) -> dict:
    """ایجاد درخواست بازخرید مرخصی - بر اساس قراردادهای سال قبل"""
    try:
        # 🆕 همیشه سال قبل را در نظر بگیر
        if year is None:
            year = jdatetime.date.today().year - 1

        # 🆕 دریافت اطلاعات قراردادهای سال قبل
        contract_info = analyze_yearly_contracts(db, user_id, year)

        # بررسی نوع استخدام
        if contract_info['employment_type'] == 'CONSCRIPT':
            return {'success': False, 'error': 'برای کارکنان وظیفه امکان بازخرید وجود ندارد'}

        # دریافت مانده مرخصی سال قبل
        balance = db.query(LeaveBalance).filter(
            and_(
                LeaveBalance.user_id == user_id,
                LeaveBalance.year == year,
                LeaveBalance.leave_type == leave_type
            )
        ).first()

        if not balance or balance.balance <= 0:
            return {'success': False, 'error': f'مانده مرخصی برای سال {year} وجود ندارد'}

        remaining_days = balance.balance

        # 🆕 محاسبه سقف بازخرید بر اساس قراردادهای سال قبل
        employee = db.query(Employee).filter(Employee.user_id == user_id).first()
        grade = employee.grade if employee and hasattr(employee, 'grade') else 1
        ceiling = calculate_leave_ceiling(year, contract_info['employment_type'], grade)

        if ceiling['max_buyback'] == 0:
            return {'success': False, 'error': 'برای این نوع استخدام بازخرید مجاز نیست'}

        # محاسبه روزهای قابل بازخرید
        if ceiling['max_buyback'] is None:
            buyback_days = remaining_days
        else:
            buyback_days = min(remaining_days, ceiling['max_buyback'])

        # 🆕 تناسب با کارکرد واقعی در سال قبل
        # اگر کل سال فرض شده (بدون قرارداد)، نیازی به تناسب نیست
        if not contract_info['covers_full_year'] and contract_info['total_days'] > 0:
            year_total_days = 365
            proportional_ratio = contract_info['total_days'] / year_total_days
            buyback_days = int(buyback_days * proportional_ratio)

        if buyback_days <= 0:
            return {'success': False, 'error': 'سقف مجاز بازخرید صفر است'}

        # ایجاد درخواست بازخرید
        request = LeaveCarryForwardRequest(
            user_id=user_id,
            from_year=year,  # ← فیلد صحیح
            to_year=year + 1,  # ← فیلد صحیح
            leave_type=leave_type,
            days_count=buyback_days,
            user_choice='CASH',
            status='P',
            admin_note=f"سال {year} | تعداد قراردادها: {contract_info['contracts_count']} | روزهای کارکرد: {contract_info['total_days']}"
        )
        db.add(request)
        db.commit()

        return {
            'success': True,
            'days': buyback_days,
            'year': year,
            'contracts_count': contract_info['contracts_count'],
            'total_days_worked': contract_info['total_days'],
        }

    except Exception as e:
        db.rollback()
        return {'success': False, 'error': str(e)}


def user_chooses_use_leave(db, user_id: str, leave_type: str = 'AL', year: int = None) -> dict:
    """انتقال مرخصی به سال جدید (ذخیره)"""
    try:
        if year is None:
            year = jdatetime.date.today().year - 1

        contract_info = analyze_yearly_contracts(db, user_id, year)

        if contract_info['employment_type'] == 'CONSCRIPT':
            return {'success': False, 'error': 'برای کارکنان وظیفه امکان ذخیره مرخصی وجود ندارد'}

        balance = db.query(LeaveBalance).filter(
            and_(
                LeaveBalance.user_id == user_id,
                LeaveBalance.year == year,
                LeaveBalance.leave_type == leave_type
            )
        ).first()

        if not balance or balance.balance <= 0:
            return {'success': False, 'error': 'مانده مرخصی برای انتقال وجود ندارد'}

        remaining_days = balance.balance

        employee = db.query(Employee).filter(Employee.user_id == user_id).first()
        from web.services.leave_settlement import resolve_storage_cap
        from web.services.membership_resolve import membership_code_for
        year_end_g = _get_year_range_g(year)[1]
        emp_code = membership_code_for(db, employee, year_end_g)
        if not emp_code:
            return {'success': False, 'error': 'نوع عضویت برای این سال مشخص نیست'}
        policy_cap = resolve_storage_cap(db, emp_code, year_j=year)

        if policy_cap is None:
            max_days = remaining_days
            if contract_info['employment_type'] == 'LABOR_LAW':
                max_days = remaining_days // 3
        else:
            if contract_info['employment_type'] == 'LABOR_LAW':
                max_days = min(remaining_days // 3, policy_cap)
            else:
                max_days = min(remaining_days, policy_cap)

        # تناسب با کارکرد واقعی
        if not contract_info['covers_full_year'] and contract_info['total_days'] > 0:
            year_total_days = 365
            proportional_ratio = contract_info['total_days'] / year_total_days
            max_days = int(max_days * proportional_ratio)

        if max_days <= 0:
            return {'success': False, 'error': 'سقف مجاز ذخیره مرخصی صفر است'}

        balance.balance -= max_days

        new_year = year + 1
        cw_balance = db.query(LeaveBalance).filter(
            and_(
                LeaveBalance.user_id == user_id,
                LeaveBalance.year == new_year,
                LeaveBalance.leave_type == 'CW'
            )
        ).first()

        if cw_balance:
            cw_balance.balance += max_days
        else:
            cw_balance = LeaveBalance(
                user_id=user_id,
                year=new_year,
                leave_type='CW',
                balance=max_days
            )
            db.add(cw_balance)

        db.commit()

        return {
            'success': True,
            'days': max_days,
            'contracts_count': contract_info['contracts_count'],
            'total_days_worked': contract_info['total_days'],
        }

    except Exception as e:
        db.rollback()
        return {'success': False, 'error': str(e)}


# ============================================
# 🔧 عملیات مدیر
# ============================================

def admin_approve_cash_out(db: Session, request_id: int, admin_user_id: str) -> dict:
    """تایید درخواست بازخرید"""
    request = db.query(LeaveCarryForwardRequest).filter(
        LeaveCarryForwardRequest.id == request_id
    ).first()

    if not request:
        return {'success': False, 'error': 'درخواست یافت نشد'}

    if request.status != 'P':
        return {'success': False, 'error': 'درخواست قبلاً بررسی شده است'}

    prev_balance = db.query(LeaveBalance).filter(
        and_(
            LeaveBalance.user_id == request.user_id,
            LeaveBalance.year == request.from_year,
            LeaveBalance.leave_type == request.leave_type
        )
    ).first()

    if prev_balance:
        prev_balance.balance = 0

    tx = LeaveTransaction(
        user_id=request.user_id,
        year=request.from_year,
        leave_type=request.leave_type,
        amount=request.days_count,
        transaction_type='CASH_OUT',
        description=f"بازخرید مرخصی سال {request.from_year} (تایید مدیر)"
    )
    db.add(tx)

    request.status = 'C'
    request.processed_at = datetime.now()
    request.processed_by = admin_user_id
    db.commit()

    return {'success': True}


def admin_reject_cash_out(db: Session, request_id: int, admin_user_id: str, note: str = "") -> dict:
    """رد درخواست بازخرید → انتقال به سال جدید"""
    request = db.query(LeaveCarryForwardRequest).filter(
        LeaveCarryForwardRequest.id == request_id
    ).first()

    if not request:
        return {'success': False, 'error': 'درخواست یافت نشد'}

    if request.status != 'P':
        return {'success': False, 'error': 'درخواست قبلاً بررسی شده است'}

    prev_balance = db.query(LeaveBalance).filter(
        and_(
            LeaveBalance.user_id == request.user_id,
            LeaveBalance.year == request.from_year,
            LeaveBalance.leave_type == request.leave_type
        )
    ).first()

    if prev_balance:
        prev_balance.balance = 0

    tx_out = LeaveTransaction(
        user_id=request.user_id,
        year=request.from_year,
        leave_type=request.leave_type,
        amount=request.days_count,
        transaction_type='CF_OUT',
        description=f"انتقال مرخصی به سال {request.to_year} (رد درخواست بازخرید)"
    )
    db.add(tx_out)

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

    tx_in = LeaveTransaction(
        user_id=request.user_id,
        year=request.to_year,
        leave_type=CARRY_FORWARD_LEAVE_TYPE,
        amount=request.days_count,
        transaction_type='CF_IN',
        description=f"مرخصی ذخیره از سال {request.from_year} (رد درخواست بازخرید)"
    )
    db.add(tx_in)

    request.status = 'R'
    request.admin_note = note
    request.processed_at = datetime.now()
    request.processed_by = admin_user_id
    db.commit()

    return {'success': True}