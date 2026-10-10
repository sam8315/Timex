"""Seed کامپوننت‌ها، تنظیمات نرخ و قوانین رسمی پایه سنوات."""
from __future__ import annotations

from decimal import Decimal

import jdatetime
from sqlalchemy import text
from sqlalchemy.orm import Session

from core.payroll.night import DEFAULT_EXCLUDED
from core.payroll.official_seniority_laws import OFFICIAL_SENIORITY_LAWS
from models.membership_type import BEHAVIOR_PERMANENT, MembershipType
from models.payroll import (
    PayrollAnnualLaw,
    PayrollChildAllowancePolicy,
    PayrollComponent,
    PayrollMinimumWage,
    PayrollOvertimePolicy,
    PayrollDeficitPolicy,
    PayrollShiftPolicy,
    PayrollNightPolicy,
    PayrollFridayPolicy,
    PayrollEnabledMembership,
    PayrollRateSettings,
)

DEFAULT_COMPONENTS = [
    ("DAILY_WAGE", "حقوق روزانه", "earning", "daily_x_covered", True, True, 10),
    ("SENIORITY", "پایه سنوات", "earning", "seniority_chain", True, True, 20),
    ("HOUSING", "حق مسکن", "earning", "fixed_monthly_prorata", True, True, 30),
    ("WORKER_VOUCHER", "بن کارگری", "earning", "fixed_monthly_prorata", True, True, 40),
    ("MARRIAGE", "حق تأهل", "earning", "fixed_monthly_prorata", True, True, 50),
    ("CHILD_ALLOWANCE", "حق اولاد", "earning", "child_allowance", True, True, 60),
    ("OVERTIME", "اضافه‌کار", "earning", "overtime_policy", True, True, 70),
    ("HOLIDAY_WORK", "تعطیل‌کاری", "earning", "holiday_work", True, True, 75),
    ("FRIDAY_WORK", "جمعه‌کاری", "earning", "friday_attendance", True, True, 80),
    ("NIGHT_WORK", "شب‌کاری", "earning", "night_work", True, True, 85),
    ("SHIFT", "نوبت‌کاری", "earning", "shift_policy", True, True, 90),
    ("BONUS", "پاداش", "earning", "policy_bonus", True, True, 100),
    ("EIDI", "عیدی", "earning", "policy_eidi", True, True, 110),
    ("WORK_DEFICIT", "کسر کار", "deduction", "work_deficit", False, False, 190),
    ("INSURANCE_EMPLOYEE", "بیمه سهم کارمند", "deduction", "percent_insurance", False, False, 200),
    ("TAX", "مالیات", "deduction", "percent_tax", False, False, 210),
]


def _jalali_start(year_j: int):
    return jdatetime.date(year_j, 1, 1).togregorian()


def ensure_official_seniority_laws(db: Session, *, overwrite: bool = False) -> int:
    """درج/به‌روزرسانی قوانین رسمی پایه سنوات در Policy.

    اگر overwrite=False فقط سال‌های مفقود اضافه می‌شوند.
    اگر overwrite=True مقادیر نسخه official برای همان سال به‌روز می‌شوند.
    """
    existing = {
        (row.year_j, row.version): row
        for row in db.query(PayrollAnnualLaw).all()
    }
    inserted = 0
    for year_j, n, r, source in OFFICIAL_SENIORITY_LAWS:
        key = (year_j, "official")
        if key in existing:
            if not overwrite:
                continue
            row = existing[key]
            row.new_seniority_daily = Decimal(n)
            row.wage_increase_factor = Decimal(r)
            row.source_reference = source
            row.status = "active"
            row.effective_from = _jalali_start(year_j)
        else:
            # اگر نسخه دیگری برای سال هست و official نیست، official را جداگانه می‌گذاریم
            db.add(
                PayrollAnnualLaw(
                    year_j=year_j,
                    new_seniority_daily=Decimal(n),
                    wage_increase_factor=Decimal(r),
                    effective_from=_jalali_start(year_j),
                    version="official",
                    source_reference=source,
                    status="active",
                )
            )
            inserted += 1
    db.commit()
    return inserted


def ensure_minimum_wage_schema(db: Session) -> None:
    """ستون عضویت و یکتایی سال+عضویت؛ ردیف بدون عضویت پیش‌فرض همان سال است."""
    db.execute(text(
        "ALTER TABLE payroll_minimum_wages "
        "ADD COLUMN IF NOT EXISTS membership_type_code VARCHAR(10)"
    ))
    db.execute(text(
        "ALTER TABLE payroll_minimum_wages "
        "DROP CONSTRAINT IF EXISTS uq_payroll_minimum_wages_year"
    ))
    db.execute(text(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_payroll_min_wage_year_mem "
        "ON payroll_minimum_wages (year_j, COALESCE(membership_type_code, ''))"
    ))
    db.commit()


def ensure_child_allowance_defaults(db: Session) -> None:
    """سیاست اولیه حق اولاد و حداقل مزد — دادهٔ قابل ویرایش، نه شرط داخل موتور."""
    ensure_minimum_wage_schema(db)
    db.execute(text(
        "ALTER TABLE payroll_components DROP CONSTRAINT IF EXISTS ck_payroll_components_calc_mode"
    ))
    db.commit()

    if db.query(PayrollMinimumWage).count() == 0:
        db.add(
            PayrollMinimumWage(
                year_j=1405,
                membership_type_code=None,
                daily_amount=Decimal("5541850"),
                effective_from=jdatetime.date(1405, 1, 1).togregorian(),
                source_reference="بخشنامه مزد ۱۴۰۵ — حداقل مزد روزانه (پیش‌فرض)",
                status="active",
            )
        )
        db.commit()

    # فقط بار اول؛ حذف کاربر نباید با مراجعهٔ بعدی دوباره ساخته شود.
    if db.query(PayrollChildAllowancePolicy).count() > 0:
        return
    types = db.query(MembershipType).filter(MembershipType.is_active.is_(True)).all()
    start = jdatetime.date(1405, 1, 1).togregorian()
    for mt in types:
        name = mt.name or ""
        is_permanent = mt.behavior_profile == BEHAVIOR_PERMANENT
        is_contract = "قرارداد" in name
        if not is_permanent and not is_contract:
            continue
        db.add(
            PayrollChildAllowancePolicy(
                membership_type_code=mt.code,
                applies_to_female=not is_permanent,
                age_limit_years=18,
                require_study_above_age=True,
                wage_day_multiplier=Decimal("3"),
                count_only_verified=False,
                effective_from=start,
                is_active=True,
                notes=(
                    "عضویت رسمی: حق اولاد شامل کارکنان زن نمی‌شود"
                    if is_permanent
                    else "قراردادی: فرزند زنده زیر حد سن، و بالاتر در صورت اشتغال به تحصیل"
                ),
            )
        )
    db.commit()


def ensure_overtime_defaults(db: Session) -> None:
    """سیاست اولیه اضافه‌کار گروه قراردادی. حذف کاربر دوباره ساخته نمی‌شود."""
    db.execute(text(
        """
        CREATE TABLE IF NOT EXISTS payroll_overtime_policies (
            id SERIAL PRIMARY KEY,
            membership_type_code VARCHAR(10) NOT NULL,
            method VARCHAR(40) NOT NULL DEFAULT 'monthly_div',
            basis_codes TEXT NOT NULL DEFAULT '',
            divisor NUMERIC(18, 4) NOT NULL DEFAULT 157,
            premium_factor NUMERIC(8, 4) NOT NULL DEFAULT 1.4,
            ordinary_month_hours NUMERIC(18, 4) NOT NULL DEFAULT 220,
            effective_from DATE NOT NULL,
            effective_to DATE NULL,
            is_active BOOLEAN NOT NULL DEFAULT TRUE,
            notes TEXT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_payroll_overtime_membership UNIQUE (membership_type_code)
        )
        """
    ))
    db.commit()
    if db.query(PayrollOvertimePolicy).count() > 0:
        return
    types = db.query(MembershipType).filter(MembershipType.is_active.is_(True)).all()
    start = jdatetime.date(1405, 1, 1).togregorian()
    for mt in types:
        if "قرارداد" not in (mt.name or ""):
            continue
        db.add(
            PayrollOvertimePolicy(
                membership_type_code=mt.code,
                method="monthly_div",
                basis_codes="DAILY_WAGE",
                divisor=Decimal("157"),
                premium_factor=Decimal("1.4"),
                ordinary_month_hours=Decimal("220"),
                effective_from=start,
                is_active=True,
                notes="گروه قراردادی — مبنای اولیه فقط حقوق روزانه؛ آیتم‌ها و روش قابل ویرایش است",
            )
        )
    db.commit()


def ensure_deficit_defaults(db: Session) -> None:
    """سیاست اولیه کسر کار. حذف کاربر دوباره ساخته نمی‌شود."""
    db.execute(text(
        """
        CREATE TABLE IF NOT EXISTS payroll_deficit_policies (
            id SERIAL PRIMARY KEY,
            membership_type_code VARCHAR(10) NOT NULL,
            basis_codes TEXT NOT NULL DEFAULT '',
            ordinary_month_hours NUMERIC(18, 4) NOT NULL DEFAULT 220,
            basis_days NUMERIC(8, 2) NOT NULL DEFAULT 30,
            effective_from DATE NOT NULL,
            effective_to DATE NULL,
            is_active BOOLEAN NOT NULL DEFAULT TRUE,
            notes TEXT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_payroll_deficit_membership UNIQUE (membership_type_code)
        )
        """
    ))
    db.commit()
    if db.query(PayrollDeficitPolicy).count() > 0:
        return
    start = jdatetime.date(1405, 1, 1).togregorian()
    overtime_rows = {
        row.membership_type_code: row
        for row in db.query(PayrollOvertimePolicy).all()
    }
    types = db.query(MembershipType).filter(MembershipType.is_active.is_(True)).all()
    for mt in types:
        if "قرارداد" not in (mt.name or ""):
            continue
        source = overtime_rows.get(mt.code)
        db.add(
            PayrollDeficitPolicy(
                membership_type_code=mt.code,
                basis_codes=(source.basis_codes if source and source.basis_codes else "DAILY_WAGE"),
                ordinary_month_hours=(source.ordinary_month_hours if source else Decimal("220")),
                basis_days=Decimal("30"),
                effective_from=start,
                is_active=True,
                notes="نرخ کسر کار = جمع آیتم‌های مبنا ÷ ساعت عادی ماه",
            )
        )
    db.commit()


def ensure_shift_defaults(db: Session) -> None:
    """سیاست اولیه نوبت‌کاری گروه قراردادی. حذف کاربر دوباره ساخته نمی‌شود."""
    db.execute(text(
        """
        CREATE TABLE IF NOT EXISTS payroll_shift_policies (
            id SERIAL PRIMARY KEY,
            membership_type_code VARCHAR(10) NOT NULL,
            basis_codes TEXT NOT NULL DEFAULT '',
            pct_morning_evening NUMERIC(8, 4) NOT NULL DEFAULT 10,
            pct_morning_evening_night NUMERIC(8, 4) NOT NULL DEFAULT 15,
            pct_morning_night NUMERIC(8, 4) NOT NULL DEFAULT 22.5,
            pct_evening_night NUMERIC(8, 4) NOT NULL DEFAULT 22.5,
            effective_from DATE NOT NULL,
            effective_to DATE NULL,
            is_active BOOLEAN NOT NULL DEFAULT TRUE,
            notes TEXT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_payroll_shift_membership UNIQUE (membership_type_code)
        )
        """
    ))
    db.execute(text(
        """
        CREATE TABLE IF NOT EXISTS payroll_shift_choices (
            id SERIAL PRIMARY KEY,
            run_id INTEGER NOT NULL
                REFERENCES payroll_runs(id) ON DELETE CASCADE,
            user_id VARCHAR(50) NOT NULL
                REFERENCES users(user_id) ON DELETE CASCADE,
            pattern VARCHAR(40) NOT NULL DEFAULT 'none',
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_payroll_shift_choice_run_user UNIQUE (run_id, user_id)
        )
        """
    ))
    db.commit()
    if db.query(PayrollShiftPolicy).count() > 0:
        return
    start = jdatetime.date(1405, 1, 1).togregorian()
    overtime_rows = {
        row.membership_type_code: row
        for row in db.query(PayrollOvertimePolicy).all()
    }
    types = db.query(MembershipType).filter(MembershipType.is_active.is_(True)).all()
    for mt in types:
        if "قرارداد" not in (mt.name or ""):
            continue
        source = overtime_rows.get(mt.code)
        db.add(
            PayrollShiftPolicy(
                membership_type_code=mt.code,
                basis_codes=(source.basis_codes if source and source.basis_codes else "DAILY_WAGE"),
                pct_morning_evening=Decimal("10"),
                pct_morning_evening_night=Decimal("15"),
                pct_morning_night=Decimal("22.5"),
                pct_evening_night=Decimal("22.5"),
                effective_from=start,
                is_active=True,
                notes="درصدهای اولیه قابل ویرایش است. مبنا از آیتم‌های انتخاب‌شده ساخته می‌شود",
            )
        )
    db.commit()


def ensure_night_defaults(db: Session) -> None:
    """سیاست اولیه شب‌کاری گروه قراردادی. حذف کاربر دوباره ساخته نمی‌شود."""
    db.execute(text(
        """
        CREATE TABLE IF NOT EXISTS payroll_night_policies (
            id SERIAL PRIMARY KEY,
            membership_type_code VARCHAR(10) NOT NULL,
            premium_percent NUMERIC(8, 4) NOT NULL DEFAULT 35,
            basis_codes TEXT NOT NULL DEFAULT 'DAILY_WAGE',
            excluded_patterns TEXT NOT NULL DEFAULT '',
            effective_from DATE NOT NULL,
            effective_to DATE NULL,
            is_active BOOLEAN NOT NULL DEFAULT TRUE,
            notes TEXT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_payroll_night_membership UNIQUE (membership_type_code)
        )
        """
    ))
    db.execute(text(
        "ALTER TABLE payroll_night_policies "
        "ADD COLUMN IF NOT EXISTS basis_codes TEXT NOT NULL DEFAULT 'DAILY_WAGE'"
    ))
    db.execute(text(
        "UPDATE payroll_night_policies SET basis_codes = 'DAILY_WAGE' "
        "WHERE basis_codes IS NULL OR btrim(basis_codes) = ''"
    ))
    db.commit()
    if db.query(PayrollNightPolicy).count() > 0:
        return
    start = jdatetime.date(1405, 1, 1).togregorian()
    types = db.query(MembershipType).filter(MembershipType.is_active.is_(True)).all()
    excluded = ",".join(DEFAULT_EXCLUDED)
    for mt in types:
        if "قرارداد" not in (mt.name or ""):
            continue
        db.add(
            PayrollNightPolicy(
                membership_type_code=mt.code,
                premium_percent=Decimal("35"),
                basis_codes="DAILY_WAGE",
                excluded_patterns=excluded,
                effective_from=start,
                is_active=True,
                notes="درصد اولیه ۳۵ است. نوبت‌کارها در مقدار اولیه شب‌کاری نمی‌گیرند",
            )
        )
    db.commit()


def ensure_friday_defaults(db: Session) -> None:
    """سیاست اولیه جمعه‌کاری گروه قراردادی. حذف کاربر دوباره ساخته نمی‌شود."""
    db.execute(text(
        """
        CREATE TABLE IF NOT EXISTS payroll_friday_policies (
            id SERIAL PRIMARY KEY,
            membership_type_code VARCHAR(10) NOT NULL,
            premium_percent NUMERIC(8, 4) NOT NULL DEFAULT 96,
            basis_codes TEXT NOT NULL DEFAULT '',
            excluded_patterns TEXT NOT NULL DEFAULT '',
            effective_from DATE NOT NULL,
            effective_to DATE NULL,
            is_active BOOLEAN NOT NULL DEFAULT TRUE,
            notes TEXT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_payroll_friday_membership UNIQUE (membership_type_code)
        )
        """
    ))
    db.commit()
    if db.query(PayrollFridayPolicy).count() > 0:
        return
    start = jdatetime.date(1405, 1, 1).togregorian()
    excluded = ",".join(DEFAULT_EXCLUDED)
    types = db.query(MembershipType).filter(MembershipType.is_active.is_(True)).all()
    for mt in types:
        if "قرارداد" not in (mt.name or ""):
            continue
        db.add(
            PayrollFridayPolicy(
                membership_type_code=mt.code,
                premium_percent=Decimal("96"),
                basis_codes="DAILY_WAGE",
                excluded_patterns=excluded,
                effective_from=start,
                is_active=True,
                notes="درصد اولیه ۹۶ است. فقط بخش اضافه است. نوبت‌کارها جمعه‌کاری نمی‌گیرند",
            )
        )
    db.commit()


def ensure_payroll_enabled_memberships_table(db: Session) -> None:
    db.execute(text(
        """
        CREATE TABLE IF NOT EXISTS payroll_enabled_memberships (
            membership_type_code VARCHAR(10) NOT NULL
                PRIMARY KEY REFERENCES membership_types(code) ON DELETE CASCADE
        )
        """
    ))
    db.commit()


def ensure_payroll_defaults(db: Session) -> None:
    ensure_payroll_enabled_memberships_table(db)
    db.execute(text(
        "ALTER TABLE payroll_components DROP CONSTRAINT IF EXISTS ck_payroll_components_calc_mode"
    ))
    db.execute(text(
        "ALTER TABLE payroll_runs ADD COLUMN IF NOT EXISTS component_codes TEXT NULL"
    ))
    db.execute(text(
        "ALTER TABLE payroll_runs ADD COLUMN IF NOT EXISTS calculating_by VARCHAR(50) NULL"
    ))
    db.execute(text(
        "ALTER TABLE payroll_runs "
        "ADD COLUMN IF NOT EXISTS calculating_started_at TIMESTAMPTZ NULL"
    ))
    db.commit()
    existing = {c.code for c in db.query(PayrollComponent).all()}
    for code, name, kind, mode, ins, tax, order in DEFAULT_COMPONENTS:
        if code in existing:
            continue
        db.add(
            PayrollComponent(
                code=code,
                name=name,
                kind=kind,
                calc_mode=mode,
                subject_to_insurance=ins,
                subject_to_tax=tax,
                sort_order=order,
            )
        )
    order_by_code = {code: order for code, _name, _kind, _mode, _ins, _tax, order in DEFAULT_COMPONENTS}
    for comp in db.query(PayrollComponent).all():
        wanted = order_by_code.get(comp.code)
        if wanted is not None and comp.sort_order != wanted:
            comp.sort_order = wanted
        if comp.code == "SHIFT" and comp.calc_mode == "manual":
            comp.calc_mode = "shift_policy"
    if db.query(PayrollRateSettings).first() is None:
        db.add(PayrollRateSettings())
    db.commit()
    ensure_official_seniority_laws(db, overwrite=False)
    ensure_child_allowance_defaults(db)
    ensure_overtime_defaults(db)
    ensure_deficit_defaults(db)
    ensure_shift_defaults(db)
    ensure_night_defaults(db)
    ensure_friday_defaults(db)
