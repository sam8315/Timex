"""
سرویس مرخصی ساعتی (Hourly Leave Service)

مسئول:
- Policy Resolution (Employee Override → Employment Type → None)
- Submission-time validation (working hours, conflicts, granularity, overlap)
- Approval-time accounting (daily limit, monthly exempt, annual accumulation, AL deduction)
- Reversal flow (admin delete approved HL)
- Query helpers for attendance/report integration
"""
from datetime import date, datetime, time, timedelta
from typing import Optional, Dict, List, Tuple

from sqlalchemy.orm import Session
from sqlalchemy import and_, func

import jdatetime

from models.employee import Employee
from models.attendance import (
    AttendancePolicy, AttendancePolicyDay,
    HourlyLeavePolicy, HourlyLeaveResolution, HourlyLeaveTransaction,
)
from models.leave_request import LeaveRequest
from models.leave_balance import LeaveBalance
from models.leave_transaction import LeaveTransaction
from models.daily_status import DailyStatus
from web.services.attendance_policy_service import (
    resolve_policy as resolve_attendance_policy,
    resolve_policy_day,
    time_to_minutes,
)


# ============================================
# Policy Resolution
# ============================================

def resolve_hourly_leave_policy(
    db: Session,
    employee: Employee,
    target_date: date
) -> Optional[HourlyLeavePolicy]:
    """
    پیدا کردن سیاست مرخصی ساعتی معتبر برای یک کارمند در یک تاریخ

    Priority:
    1. Employee Override (user_id = employee.user_id)
    2. Employment Type Policy (employment_type_code = employee.department)

    Returns:
        HourlyLeavePolicy یا None اگر پیدا نشود
    """
    employment_type = employee.department if employee else None
    if not employment_type:
        return None

    # مرحله ۱: Employee Override
    override = db.query(HourlyLeavePolicy).filter(
        and_(
            HourlyLeavePolicy.user_id == employee.user_id,
            HourlyLeavePolicy.is_active == True,
            HourlyLeavePolicy.effective_from_date <= target_date,
            (
                HourlyLeavePolicy.effective_to_date.is_(None) |
                (HourlyLeavePolicy.effective_to_date >= target_date)
            )
        )
    ).order_by(HourlyLeavePolicy.effective_from_date.desc()).first()

    if override:
        return override

    # مرحله ۲: Employment Type Policy
    emp_policy = db.query(HourlyLeavePolicy).filter(
        and_(
            HourlyLeavePolicy.employment_type_code == employment_type,
            HourlyLeavePolicy.user_id.is_(None),
            HourlyLeavePolicy.is_active == True,
            HourlyLeavePolicy.effective_from_date <= target_date,
            (
                HourlyLeavePolicy.effective_to_date.is_(None) |
                (HourlyLeavePolicy.effective_to_date >= target_date)
            )
        )
    ).order_by(HourlyLeavePolicy.effective_from_date.desc()).first()

    return emp_policy


# ============================================
# Query Helpers
# ============================================

def _time_to_minutes(t: time) -> int:
    """تبدیل time به دقیقه از ابتدای روز"""
    return t.hour * 60 + t.minute


def _minutes_to_time(m: int) -> time:
    """تبدیل دقیقه از ابتدای روز به time"""
    return time(m // 60, m % 60)


def compute_requested_minutes(start_time: time, end_time: time) -> int:
    """محاسبه دقایق درخواست مرخصی ساعتی"""
    return _time_to_minutes(end_time) - _time_to_minutes(start_time)


def get_approved_hl_minutes_on_date(
    db: Session,
    employee: Employee,
    leave_date: date
) -> int:
    """
    مجموع دقایق مرخصی ساعتی تایید شده در یک تاریخ خاص
    فقط درخواست‌های Approved (Pending محاسبه نمی‌شود)
    """
    requests = db.query(LeaveRequest).filter(
        and_(
            LeaveRequest.user_id == employee.user_id,
            LeaveRequest.leave_type == 'HL',
            LeaveRequest.status == 'A',
            LeaveRequest.from_date == leave_date,
        )
    ).all()

    total = 0
    for req in requests:
        if req.start_time and req.end_time:
            total += compute_requested_minutes(req.start_time, req.end_time)
    return total


def get_approved_hl_minutes(
    db: Session,
    employee: Employee,
    start_date: date,
    end_date: date
) -> Dict[date, int]:
    """
    مجموع دقایق مرخصی ساعتی تایید شده برای هر تاریخ در بازه
    Returns: dict[date] → minutes
    """
    requests = db.query(LeaveRequest).filter(
        and_(
            LeaveRequest.user_id == employee.user_id,
            LeaveRequest.leave_type == 'HL',
            LeaveRequest.status == 'A',
            LeaveRequest.from_date >= start_date,
            LeaveRequest.from_date <= end_date,
        )
    ).all()

    result: Dict[date, int] = {}
    for req in requests:
        if req.start_time and req.end_time:
            minutes = compute_requested_minutes(req.start_time, req.end_time)
            result[req.from_date] = result.get(req.from_date, 0) + minutes
    return result


def get_monthly_exempt_usage(
    db: Session,
    user_id: str,
    year: int,
    month: int
) -> int:
    """
    مجموع دقایق معاف استفاده شده در یک ماه خاص
    از HourlyLeaveTransaction محاسبه می‌شود (فقط USE)
    """
    result = db.query(
        func.coalesce(func.sum(HourlyLeaveTransaction.exempt_minutes), 0)
    ).filter(
        and_(
            HourlyLeaveTransaction.user_id == user_id,
            HourlyLeaveTransaction.year == year,
            HourlyLeaveTransaction.month == month,
            HourlyLeaveTransaction.transaction_type == 'USE',
        )
    ).scalar()

    return int(result)


def get_annual_subject_minutes(
    db: Session,
    user_id: str,
    year: int
) -> int:
    """
    محاسبه مجموع دقایق مشمول استحقاقی در یک سال شمسی
    با استفاده از HourlyLeaveResolution + LeaveRequest
    """
    # تمام درخواست‌های HL تایید شده در این سال شمسی
    approved_hl = db.query(LeaveRequest).filter(
        and_(
            LeaveRequest.user_id == user_id,
            LeaveRequest.leave_type == 'HL',
            LeaveRequest.status == 'A',
        )
    ).all()

    total = 0
    for req in approved_hl:
        req_year = jdatetime.date.fromgregorian(date=req.from_date).year
        if req_year == year:
            resolution = db.query(HourlyLeaveResolution).filter(
                and_(
                    HourlyLeaveResolution.leave_request_id == req.id,
                    HourlyLeaveResolution.status == 'APPROVED',
                )
            ).first()
            if resolution:
                total += resolution.minutes_subject_to_al

    return total


# ============================================
# Submission-time Validation
# ============================================

def validate_hourly_leave_request(
    db: Session,
    employee: Employee,
    leave_date: date,
    start_time: time,
    end_time: time,
) -> Tuple[bool, Optional[str]]:
    """
    اعتبارسنجی درخواست مرخصی ساعتی در زمان ثبت

    Returns:
        (is_valid, error_message)
    """
    # ۱. ساعت شروع < ساعت پایان
    if start_time >= end_time:
        return False, "ساعت شروع باید قبل از ساعت پایان باشد"

    # ۲. Policy Resolution
    policy = resolve_hourly_leave_policy(db, employee, leave_date)
    if policy is None:
        return False, "سیاست مرخصی ساعتی برای این کارمند تعریف نشده است"

    # ۳. Granularity check
    granularity = policy.granularity_minutes
    start_min = _time_to_minutes(start_time)
    end_min = _time_to_minutes(end_time)
    if start_min % granularity != 0 or end_min % granularity != 0:
        return False, f"ساعت شروع و پایان باید مضربی از {granularity} دقیقه باشند"

    # ۴. Duration check
    duration = end_min - start_min
    if policy.min_request_minutes and duration < policy.min_request_minutes:
        return False, f"حداقل مدت مرخصی ساعتی {policy.min_request_minutes} دقیقه است"
    if policy.max_request_minutes and duration > policy.max_request_minutes:
        return False, f"حداکثر مدت مرخصی ساعتی {policy.max_request_minutes} دقیقه است"

    # ۵. Working hours check (from AttendancePolicyDay)
    # Python weekday: 0=Mon, 1=Tue, 2=Wed, 3=Thu, 4=Fri, 5=Sat, 6=Sun
    # Persian rest day: Friday (weekday=4)
    weekday = leave_date.weekday()
    if weekday == 4:  # Friday
        return False, "مرخصی ساعتی در روز تعطیل (جمعه) امکان‌پذیر نیست"

    attendance_policy = resolve_attendance_policy(db, employee, leave_date)
    policy_day = resolve_policy_day(attendance_policy, leave_date)
    if policy_day and not policy_day.is_working_day:
        return False, "مرخصی ساعتی فقط در روزهای کاری امکان‌پذیر است"
    if policy_day and policy_day.is_working_day:
        work_start = time_to_minutes(policy_day.start_time) if policy_day.start_time else None
        work_end = time_to_minutes(policy_day.end_time) if policy_day.end_time else None

        if work_start is not None and start_min < work_start:
            return False, "ساعت شروع مرخصی قبل از ساعت شروع شیفت کاری است"
        if work_end is not None and end_min > work_end:
            return False, "ساعت پایان مرخصی بعد از ساعت پایان شیفت کاری است"

    # ۶. Conflict with full-day leave (AL/SL/RL/CW/UL)
    full_day_leave = db.query(LeaveRequest).filter(
        and_(
            LeaveRequest.user_id == employee.user_id,
            LeaveRequest.leave_type != 'HL',
            LeaveRequest.status.in_(['P', 'A']),
            LeaveRequest.from_date <= leave_date,
            LeaveRequest.to_date >= leave_date,
        )
    ).first()
    if full_day_leave:
        return False, "در این تاریخ مرخصی روزانه ثبت شده است"

    # ۷. Conflict with DailyStatus Mission (M) or Rest (R)
    daily_status = db.query(DailyStatus).filter(
        and_(
            DailyStatus.user_id == employee.user_id,
            DailyStatus.status_date == leave_date,
            DailyStatus.status_code.in_(['M', 'R']),
        )
    ).first()
    if daily_status:
        status_name = "مأموریت" if daily_status.status_code == 'M' else "استراحت"
        return False, f"در این تاریخ {status_name} ثبت شده است"

    # ۸. Time overlap with existing approved HL on same date
    existing_hl = db.query(LeaveRequest).filter(
        and_(
            LeaveRequest.user_id == employee.user_id,
            LeaveRequest.leave_type == 'HL',
            LeaveRequest.status.in_(['P', 'A']),
            LeaveRequest.from_date == leave_date,
        )
    ).all()

    for existing in existing_hl:
        if existing.start_time and existing.end_time:
            ex_start = _time_to_minutes(existing.start_time)
            ex_end = _time_to_minutes(existing.end_time)
            # Overlap check: NOT (new_end <= ex_start OR new_start >= ex_end)
            if not (end_min <= ex_start or start_min >= ex_end):
                return False, "با مرخصی ساعتی موجود در این تاریخ تداخل زمانی دارد"

    return True, None


# ============================================
# Approval Flow
# ============================================

def approve_hourly_leave(
    db: Session,
    leave_request: LeaveRequest,
    approver_user_id: str,
) -> Tuple[bool, Optional[str]]:
    """
    تایید درخواست مرخصی ساعتی

    Flow:
    1. Resolve policy
    2. Check daily limit → full_day_conversion if exceeded
    3. Calculate monthly exempt usage
    4. Calculate minutes_subject_to_al
    5. Calculate annual accumulation → new_al_days_deducted
    6. Check AL balance >= new_al_days_deducted
    7. Create HourlyLeaveResolution
    8. Create HourlyLeaveTransaction
    9. If new_al_days_deducted > 0: deduct from LeaveBalance + LeaveTransaction
    10. Update LeaveRequest status

    Returns:
        (success, error_message)
    """
    if leave_request.leave_type != 'HL':
        return False, "این درخواست مرخصی ساعتی نیست"
    if not leave_request.start_time or not leave_request.end_time:
        return False, "ساعت شروع/پایان مشخص نشده است"

    leave_date = leave_request.from_date
    requested_minutes = compute_requested_minutes(
        leave_request.start_time, leave_request.end_time
    )

    # ۱. Resolve Policy
    employee = db.query(Employee).filter(
        Employee.user_id == leave_request.user_id
    ).first()
    if not employee:
        return False, "کارمند یافت نشد"

    policy = resolve_hourly_leave_policy(db, employee, leave_date)
    if not policy:
        return False, "سیاست مرخصی ساعتی یافت نشد"

    # Jalali year/month
    j_date = jdatetime.date.fromgregorian(date=leave_date)
    year_j = j_date.year
    month_j = j_date.month

    # ۲. Daily Limit Check
    daily_usage_before = get_approved_hl_minutes_on_date(db, employee, leave_date)
    daily_usage_after = daily_usage_before + requested_minutes
    daily_limit_exceeded = daily_usage_after > policy.max_daily_minutes
    full_day_conversion = daily_limit_exceeded

    if full_day_conversion:
        # Treat as full day: minutes_subject_to_al will be computed after exempt
        effective_minutes = policy.conversion_minutes_per_day
    else:
        effective_minutes = requested_minutes

    # ۳. Monthly Exempt
    monthly_exempt_used_before = get_monthly_exempt_usage(
        db, leave_request.user_id, year_j, month_j
    )
    remaining_exempt = max(0, policy.monthly_exempt_minutes - monthly_exempt_used_before)

    if policy.hourly_leave_entitled:
        monthly_exempt_applied = min(effective_minutes, remaining_exempt)
    else:
        monthly_exempt_applied = 0

    # ۴. Subject to AL
    minutes_subject_to_al = effective_minutes - monthly_exempt_applied

    # ۵. Annual Accumulation
    annual_subject_minutes_before = get_annual_subject_minutes(
        db, leave_request.user_id, year_j
    )
    annual_subject_minutes_after = annual_subject_minutes_before + minutes_subject_to_al

    previous_complete_days = annual_subject_minutes_before // policy.conversion_minutes_per_day
    new_complete_days = annual_subject_minutes_after // policy.conversion_minutes_per_day
    new_al_days_deducted = new_complete_days - previous_complete_days
    annual_remainder_minutes = annual_subject_minutes_after % policy.conversion_minutes_per_day

    # ۶. Check AL Balance
    if new_al_days_deducted > 0:
        al_balance = db.query(LeaveBalance).filter(
            and_(
                LeaveBalance.user_id == leave_request.user_id,
                LeaveBalance.year == year_j,
                LeaveBalance.leave_type == 'AL',
            )
        ).first()
        current_al = al_balance.balance if al_balance else 0
        if current_al < new_al_days_deducted:
            return False, (
                f"مانده مرخصی استحقاقی کافی نیست! "
                f"مانده: {current_al} روز، مورد نیاز: {new_al_days_deducted} روز"
            )

    # ۷. Create Resolution (audit trail)
    resolution = HourlyLeaveResolution(
        leave_request_id=leave_request.id,
        requested_minutes=requested_minutes,
        policy_conversion_rate=policy.conversion_minutes_per_day,
        policy_monthly_exempt=policy.monthly_exempt_minutes,
        policy_daily_limit=policy.max_daily_minutes,
        policy_entitled=policy.hourly_leave_entitled,
        daily_usage_before=daily_usage_before,
        daily_usage_after=daily_usage_after,
        daily_limit_exceeded=daily_limit_exceeded,
        full_day_conversion=full_day_conversion,
        monthly_exempt_used_before=monthly_exempt_used_before,
        monthly_exempt_applied=monthly_exempt_applied,
        minutes_subject_to_al=minutes_subject_to_al,
        annual_subject_minutes_before=annual_subject_minutes_before,
        annual_subject_minutes_after=annual_subject_minutes_after,
        annual_remainder_minutes=annual_remainder_minutes,
        new_al_days_deducted=new_al_days_deducted,
        status='APPROVED',
    )
    db.add(resolution)

    # ۸. Create HourlyLeaveTransaction
    hl_tx = HourlyLeaveTransaction(
        user_id=leave_request.user_id,
        year=year_j,
        month=month_j,
        amount_minutes=requested_minutes,
        transaction_type='USE',
        exempt_minutes=monthly_exempt_applied,
        subject_to_al_minutes=minutes_subject_to_al,
        description=(
            f"مرخصی ساعتی درخواست #{leave_request.id}"
            + (f" ({leave_request.start_time.strftime('%H:%M')}-{leave_request.end_time.strftime('%H:%M')})"
               if leave_request.start_time and leave_request.end_time else "")
        ),
        reference_id=leave_request.id,
    )
    db.add(hl_tx)

    # ۹. Deduct AL if needed
    if new_al_days_deducted > 0:
        al_balance = db.query(LeaveBalance).filter(
            and_(
                LeaveBalance.user_id == leave_request.user_id,
                LeaveBalance.year == year_j,
                LeaveBalance.leave_type == 'AL',
            )
        ).first()
        if al_balance:
            al_balance.balance -= new_al_days_deducted
        else:
            al_balance = LeaveBalance(
                user_id=leave_request.user_id,
                year=year_j,
                leave_type='AL',
                balance=-new_al_days_deducted,
            )
            db.add(al_balance)

        al_tx = LeaveTransaction(
            user_id=leave_request.user_id,
            year=year_j,
            leave_type='AL',
            amount=new_al_days_deducted,
            transaction_type='USE',
            description=(
                f"کسر از استحقاقی بابت مرخصی ساعتی - درخواست #{leave_request.id} "
                f"({new_al_days_deducted} روز از {minutes_subject_to_al} دقیقه مشمول)"
            ),
            reference_id=leave_request.id,
        )
        db.add(al_tx)

    # ۱۰. Update LeaveRequest status
    leave_request.status = 'A'
    leave_request.approved_by = approver_user_id
    leave_request.approved_at = datetime.now()

    return True, None


# ============================================
# Reversal Flow
# ============================================

def _approved_hl_resolutions(
    db: Session,
    user_id: str,
    year_j: int,
    exclude_request_id: Optional[int] = None,
) -> List[Tuple[date, int, HourlyLeaveResolution]]:
    """
    همه رزولوشن‌های مرخصی ساعتی APPROVED یک کاربر در یک سال شمسی

    Args:
        exclude_request_id: شناسه درخواستی که باید حذف شود (در حال بازگشت).
            صریحاً مستثنی می‌شود تا به زمان flush سشن وابسته نباشد.

    Returns:
        لیست (from_date, request_id, resolution) مرتب‌شده بر اساس تاریخ
    """
    rows = db.query(HourlyLeaveResolution, LeaveRequest).join(
        LeaveRequest,
        LeaveRequest.id == HourlyLeaveResolution.leave_request_id,
    ).filter(
        and_(
            HourlyLeaveResolution.status == 'APPROVED',
            LeaveRequest.leave_type == 'HL',
            LeaveRequest.user_id == user_id,
            LeaveRequest.status == 'A',
        )
    ).all()

    result: List[Tuple[date, int, HourlyLeaveResolution]] = []
    for res, req in rows:
        if exclude_request_id is not None and req.id == exclude_request_id:
            continue
        if jdatetime.date.fromgregorian(date=req.from_date).year == year_j:
            result.append((req.from_date, req.id, res))

    result.sort(key=lambda t: (t[0], t[1]))
    return result


def _recompute_annual_accumulation(
    db: Session,
    user_id: str,
    year_j: int,
    conversion: int,
    exclude_request_id: Optional[int] = None,
) -> int:
    """
    محاسبه مجدد انباشت سالانه روی همه درخواست‌های HL تاییدشده باقی‌مانده

    فقط فیلدهای آستانه سالانه رزولوشن‌ها را بازنویسی می‌کند
    (new_al_days_deducted و annual_*). minutes_subject_to_al تغییر نمی‌کند،
    بنابراین معافیت ماهانه، entitled=False و تبدیل روز کامل حفظ می‌شوند.

    Returns:
        required_al_days = floor(total_subject_minutes / conversion)
    """
    approved = _approved_hl_resolutions(
        db, user_id, year_j, exclude_request_id=exclude_request_id
    )

    cumulative = 0
    for _, _, res in approved:
        before = cumulative
        cumulative += res.minutes_subject_to_al
        res.annual_subject_minutes_before = before
        res.annual_subject_minutes_after = cumulative
        res.annual_remainder_minutes = cumulative % conversion
        res.new_al_days_deducted = (
            cumulative // conversion - before // conversion
        )

    return cumulative // conversion


def reverse_hourly_leave(
    db: Session,
    leave_request: LeaveRequest,
) -> Tuple[bool, Optional[str]]:
    """
    بازگرداندن مرخصی ساعتی تایید شده (حذف توسط مدیر)

    با حذف یک درخواست، درخواست‌های بعدی ممکن است به دلیل آن درخواست از
    آستانه تبدیل سالانه عبور کرده باشند. بنابراین به‌جای بازگرداندن سادهٔ
    new_al_days_deducted همان درخواست، انباشت سالانه روی همه درخواست‌های
    APPROVED باقی‌ماندهٔ همان کاربر و سال شمسی محاسبه مجدد می‌شود و فقط
    اختلاف روزهای استحقاقی قبلی و روزهای موردنیاز جدید به مانده اعمال می‌شود.

    Flow:
    1. Find resolution + guards
    2. previous_deducted = مجموع new_al_days_deducted همه APPROVED (شامل خود درخواست)
    3. Mark resolution as REVERSED
    4. Recompute annual over remaining approved → required_al_days
    5. Reconcile AL balance by difference (required - previous)
    6. Create reverse HourlyLeaveTransaction
    7. Mark LeaveRequest as Deleted
    """
    if leave_request.leave_type != 'HL':
        return False, "این درخواست مرخصی ساعتی نیست"
    if leave_request.status != 'A':
        return False, "فقط درخواست‌های تایید شده قابل بازگشت هستند"

    resolution = db.query(HourlyLeaveResolution).filter(
        and_(
            HourlyLeaveResolution.leave_request_id == leave_request.id,
            HourlyLeaveResolution.status == 'APPROVED',
        )
    ).first()

    if not resolution:
        return False, "تراکنش مرخصی ساعتی یافت نشد"

    leave_date = leave_request.from_date
    j_date = jdatetime.date.fromgregorian(date=leave_date)
    year_j = j_date.year
    month_j = j_date.month
    conversion = resolution.policy_conversion_rate

    # ۱. روزهای استحقاقی کسرشده فعلی (شامل درخواستی که در حال بازگشت است)
    previous_deducted = sum(
        res.new_al_days_deducted
        for _, _, res in _approved_hl_resolutions(db, leave_request.user_id, year_j)
    )

    # ۲. حذف این درخواست از مجموعه APPROVED
    resolution.status = 'REVERSED'

    # ۳. محاسبه مجدد انباشت سالانه روی درخواست‌های باقی‌مانده
    required_al_days = _recompute_annual_accumulation(
        db, leave_request.user_id, year_j, conversion,
        exclude_request_id=leave_request.id,
    )

    # ۴. اعمال اختلاف به مانده استحقاقی
    #    حذف دقایق هرگز floor را افزایش نمی‌دهد، پس difference همیشه <= 0 است.
    difference = required_al_days - previous_deducted
    if difference != 0:
        al_balance = db.query(LeaveBalance).filter(
            and_(
                LeaveBalance.user_id == leave_request.user_id,
                LeaveBalance.year == year_j,
                LeaveBalance.leave_type == 'AL',
            )
        ).first()
        if al_balance:
            al_balance.balance -= difference
        else:
            al_balance = LeaveBalance(
                user_id=leave_request.user_id,
                year=year_j,
                leave_type='AL',
                balance=-difference,
            )
            db.add(al_balance)

        al_tx = LeaveTransaction(
            user_id=leave_request.user_id,
            year=year_j,
            leave_type='AL',
            amount=-difference,  # روزهای برگردانده‌شده به مانده
            transaction_type='REVERSE',
            description=(
                f"بازگشت از استحقاقی بابت حذف مرخصی ساعتی - درخواست #{leave_request.id} "
                f"({-difference} روز)"
            ),
            reference_id=leave_request.id,
        )
        db.add(al_tx)

    # ۵. Create reverse HourlyLeaveTransaction
    reverse_tx = HourlyLeaveTransaction(
        user_id=leave_request.user_id,
        year=year_j,
        month=month_j,
        amount_minutes=-resolution.requested_minutes,
        transaction_type='REVERSE',
        exempt_minutes=-resolution.monthly_exempt_applied,
        subject_to_al_minutes=-resolution.minutes_subject_to_al,
        description=f"حذف مرخصی ساعتی تایید شده - درخواست #{leave_request.id}",
        reference_id=leave_request.id,
    )
    db.add(reverse_tx)

    # ۶. Mark LeaveRequest as Deleted
    leave_request.status = 'D'

    return True, None
