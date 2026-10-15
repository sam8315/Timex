"""
تنظیم سراسری «شیفت پیوسته نیمه‌شب» (مستقل از سیاست حضور و غیاب و برنامه هفتگی).

خروج و ورودِ پشت‌سرهم داخل پنجرهٔ نیمه‌شب برای انواع عضویت انتخاب‌شده
پیوسته حساب می‌شود؛ محاسبه در موتور مرکزی (`MidnightBridgeRule`) انجام می‌شود.
"""
from dataclasses import dataclass, field
from typing import FrozenSet, Iterable, Optional

from sqlalchemy.orm import Session

from core.attendance_calculator import MidnightBridgeRule
from models.policy import Policy, PolicyAuditLog, PolicyValue

MIDNIGHT_BRIDGE_CATEGORY = "attendance_midnight_bridge"
KEY_ENABLED = "enabled"
KEY_BEFORE = "before_minutes"
KEY_AFTER = "after_minutes"
KEY_CODES = "membership_codes"

DEFAULT_WINDOW_MINUTES = 15
MAX_WINDOW_MINUTES = 60


def _clamp_minutes(value) -> int:
    try:
        minutes = int(value)
    except (TypeError, ValueError):
        return DEFAULT_WINDOW_MINUTES
    return max(0, min(MAX_WINDOW_MINUTES, minutes))


@dataclass(frozen=True)
class MidnightBridgeSettings:
    enabled: bool = False
    before_minutes: int = DEFAULT_WINDOW_MINUTES
    after_minutes: int = DEFAULT_WINDOW_MINUTES
    membership_codes: FrozenSet[str] = field(default_factory=frozenset)

    def rule_for(self, membership_code: Optional[str]) -> Optional[MidnightBridgeRule]:
        """قانون برای یک نوع عضویت؛ None اگر خاموش است یا عضویت انتخاب نشده."""
        if not self.enabled or not membership_code:
            return None
        if str(membership_code) not in self.membership_codes:
            return None
        return MidnightBridgeRule(
            before_minutes=self.before_minutes,
            after_minutes=self.after_minutes,
        )


def _find_policy(db: Session) -> Optional[Policy]:
    return db.query(Policy).filter(Policy.category == MIDNIGHT_BRIDGE_CATEGORY).first()


def load_midnight_bridge_settings(db: Session) -> MidnightBridgeSettings:
    policy = _find_policy(db)
    if not policy:
        return MidnightBridgeSettings()
    values = {
        v.parameter_key: v.parameter_value
        for v in db.query(PolicyValue).filter(PolicyValue.policy_id == policy.id).all()
    }
    codes = frozenset(
        c.strip() for c in (values.get(KEY_CODES) or "").split(",") if c.strip()
    )
    return MidnightBridgeSettings(
        enabled=values.get(KEY_ENABLED) == "true",
        before_minutes=_clamp_minutes(values.get(KEY_BEFORE, DEFAULT_WINDOW_MINUTES)),
        after_minutes=_clamp_minutes(values.get(KEY_AFTER, DEFAULT_WINDOW_MINUTES)),
        membership_codes=codes,
    )


def save_midnight_bridge_settings(
    db: Session,
    enabled: bool,
    before_minutes,
    after_minutes,
    membership_codes: Iterable[str],
    changed_by: Optional[str] = None,
) -> MidnightBridgeSettings:
    policy = _find_policy(db)
    if not policy:
        policy = Policy(
            category=MIDNIGHT_BRIDGE_CATEGORY,
            name="شیفت پیوسته نیمه‌شب",
            description="خروج و ورود پشت‌سرهم داخل پنجرهٔ نیمه‌شب پیوسته حساب می‌شود",
            is_active=True,
        )
        db.add(policy)
        db.flush()

    settings = MidnightBridgeSettings(
        enabled=bool(enabled),
        before_minutes=_clamp_minutes(before_minutes),
        after_minutes=_clamp_minutes(after_minutes),
        membership_codes=frozenset(str(c).strip() for c in membership_codes if str(c).strip()),
    )
    new_values = {
        KEY_ENABLED: "true" if settings.enabled else "false",
        KEY_BEFORE: str(settings.before_minutes),
        KEY_AFTER: str(settings.after_minutes),
        KEY_CODES: ",".join(sorted(settings.membership_codes)),
    }
    existing = {
        v.parameter_key: v
        for v in db.query(PolicyValue).filter(PolicyValue.policy_id == policy.id).all()
    }
    for key, new_value in new_values.items():
        row = existing.get(key)
        if row is not None and row.parameter_value == new_value:
            continue
        old_value = row.parameter_value if row is not None else None
        if row is not None:
            row.parameter_value = new_value
        else:
            db.add(PolicyValue(
                policy_id=policy.id,
                region_code=None,
                parameter_key=key,
                parameter_value=new_value,
                is_editable=True,
                notes="شیفت پیوسته نیمه‌شب",
            ))
        db.add(PolicyAuditLog(
            entity_type="policy_value",
            entity_id=f"{MIDNIGHT_BRIDGE_CATEGORY}.{key}",
            action="UPDATE" if row is not None else "CREATE",
            old_value=old_value,
            new_value=new_value,
            changed_by=changed_by,
            reason="تغییر تنظیم شیفت پیوسته نیمه‌شب از پنل سیاست‌ها",
        ))
    db.commit()
    return settings
