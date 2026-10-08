"""مشخصات فردی قابل نمایش روی فیش."""
from __future__ import annotations

from sqlalchemy.orm import Session, joinedload

from core.payroll.payslip_present import fa_digits, jalali_text, money_text


def load_payslip_profile(db: Session, result) -> dict:
    from models.employee import Employee
    from models.membership_type import MembershipType

    employee = (
        db.query(Employee)
        .options(joinedload(Employee.position_rel))
        .filter(Employee.user_id == result.user_id)
        .first()
    )
    membership = None
    if result.membership_type_code:
        membership = (
            db.query(MembershipType)
            .filter(MembershipType.code == result.membership_type_code)
            .first()
        )
    if membership is not None:
        membership_label = f"{membership.code} — {membership.name}"
    else:
        membership_label = result.membership_type_code or "—"

    return {
        "name": (employee.full_name if employee else None) or result.employee_name or "—",
        "user_id": fa_digits(result.user_id) or "—",
        "national_code": fa_digits(employee.national_code) if employee and employee.national_code else "—",
        "father_name": (employee.father_name if employee and employee.father_name else "—"),
        "gender": employee.gender_name if employee else "—",
        "marital": employee.marital_status_name if employee else "—",
        "position": (employee.position_name if employee and employee.position_name else "—"),
        "department": (employee.department if employee and employee.department else "—"),
        "hire_date": jalali_text(employee.hire_date) if employee else "—",
        "membership": membership_label,
        "covered_days": money_text(result.covered_days),
        "month_days": money_text(result.month_days),
    }
