"""
ملاک انتخاب افراد در محاسبه حقوق (تنظیم سراسری در سیاست حضور و غیاب).

- all: همه افراد عضویت انتخاب‌شده
- active: افراد فعال عضویت انتخاب‌شده
- contract: افراد با قرارداد معتبر در بازه ماه حقوق (پیش‌فرض)
"""
from __future__ import annotations

from typing import Literal, Optional

from sqlalchemy.orm import Session

from models.policy import Policy, PolicyAuditLog, PolicyValue

PAYROLL_AUDIENCE_CATEGORY = "attendance_payroll_audience"
KEY_MODE = "mode"

PayrollAudienceMode = Literal["all", "active", "contract"]
DEFAULT_MODE: PayrollAudienceMode = "contract"
VALID_MODES = frozenset({"all", "active", "contract"})

MODE_LABELS = {
    "all": "همه",
    "active": "فعال",
    "contract": "قرارداد معتبر",
}


def normalize_payroll_audience_mode(raw: Optional[str]) -> PayrollAudienceMode:
    value = (raw or "").strip().lower()
    if value in VALID_MODES:
        return value  # type: ignore[return-value]
    return DEFAULT_MODE


def _find_policy(db: Session) -> Optional[Policy]:
    return db.query(Policy).filter(Policy.category == PAYROLL_AUDIENCE_CATEGORY).first()


def load_payroll_audience_mode(db: Session) -> PayrollAudienceMode:
    policy = _find_policy(db)
    if not policy:
        return DEFAULT_MODE
    row = (
        db.query(PolicyValue)
        .filter(
            PolicyValue.policy_id == policy.id,
            PolicyValue.parameter_key == KEY_MODE,
        )
        .first()
    )
    if not row:
        return DEFAULT_MODE
    return normalize_payroll_audience_mode(row.parameter_value)


def save_payroll_audience_mode(
    db: Session,
    mode: str,
    changed_by: Optional[str] = None,
) -> PayrollAudienceMode:
    normalized = normalize_payroll_audience_mode(mode)
    policy = _find_policy(db)
    if not policy:
        policy = Policy(
            category=PAYROLL_AUDIENCE_CATEGORY,
            name="ملاک انتخاب افراد حقوق",
            description="نحوه انتخاب افراد در محاسبه حقوق بر اساس عضویت و دوره",
            is_active=True,
        )
        db.add(policy)
        db.flush()

    row = (
        db.query(PolicyValue)
        .filter(
            PolicyValue.policy_id == policy.id,
            PolicyValue.parameter_key == KEY_MODE,
        )
        .first()
    )
    new_value = normalized
    old_value = row.parameter_value if row is not None else None
    if row is not None and row.parameter_value == new_value:
        return normalized
    if row is not None:
        row.parameter_value = new_value
    else:
        db.add(
            PolicyValue(
                policy_id=policy.id,
                region_code=None,
                parameter_key=KEY_MODE,
                parameter_value=new_value,
                is_editable=True,
                notes="ملاک انتخاب افراد حقوق",
            )
        )
    db.add(
        PolicyAuditLog(
            entity_type="policy_value",
            entity_id=f"{PAYROLL_AUDIENCE_CATEGORY}.{KEY_MODE}",
            action="UPDATE" if row is not None else "CREATE",
            old_value=old_value,
            new_value=new_value,
            changed_by=changed_by,
            reason="تغییر ملاک انتخاب افراد حقوق از پنل سیاست حضور و غیاب",
        )
    )
    db.commit()
    return normalized
