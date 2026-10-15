"""
سرویس سیاست گزارش — registry، اعتبارسنجی، resolve و ثبت نسخهٔ جدید.

هر گزارش `report_key` و تنظیمات مستقل دارد. نبود سیاست = پیش‌فرض‌های کد
(`source='default'`)؛ هیچ داده‌ای خودکار بازنویسی یا بازمحاسبه نمی‌شود.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any, Callable, Dict, Optional

import jdatetime
from sqlalchemy.orm import Session

from models.policy import PolicyAuditLog
from models.report_policy import ReportPolicy

LEGAL_OVERTIME_MONTHLY = "legal_overtime_monthly"

DEFICIT_METHOD_CUMULATIVE = "cumulative_monthly"
DEFICIT_METHOD_LEGACY = "legacy"


class ReportPolicyError(ValueError):
    """خطای اعتبارسنجی سیاست گزارش."""


@dataclass(frozen=True)
class ReportPolicyDefinition:
    key: str
    label: str
    schema_version: int
    defaults: Dict[str, Any]
    # کلیدهایی که UI اجازهٔ ویرایش می‌دهد (بقیه ثابت و فقط خواندنی)
    editable_keys: tuple
    validate: Callable[[Dict[str, Any]], Dict[str, Any]]


# کلیدهای نسخه‌های قبلی؛ در نسخهٔ ذخیره‌شده نادیده گرفته می‌شوند.
# کسر کار (schema ≤ 3) و تفکیک کارکرد (schema ≤ 4؛ اکنون همیشه تفکیک)
_LEGACY_KEYS = (
    "deficit_adjust_friday_work",
    "deficit_adjust_holiday_work",
    "deficit_separate_friday",
    "deficit_separate_holiday",
    "deficit_separate_leave",
    "deficit_separate_rest",
    "deficit_separate_mission",
    "work_separate_friday",
    "work_separate_holiday",
    "work_separate_rest",
    "work_separate_leave",
)


def _validate_legal_ot(raw: Dict[str, Any]) -> Dict[str, Any]:
    defaults = LEGAL_OT_DEFAULTS
    raw = {k: v for k, v in raw.items() if k not in _LEGACY_KEYS}
    # schema ≤ 5 یک کلید «بدون تردد» برای گذشته و آینده داشت
    if "duty_reduce_no_punch_future" not in raw and "duty_reduce_no_punch" in raw:
        raw["duty_reduce_no_punch_future"] = raw["duty_reduce_no_punch"]
    unknown = set(raw) - set(defaults)
    if unknown:
        raise ReportPolicyError(f"کلید ناشناخته: {', '.join(sorted(unknown))}")
    merged = {**defaults, **raw}
    for key, default in defaults.items():
        value = merged[key]
        if isinstance(default, bool):
            if not isinstance(value, bool):
                raise ReportPolicyError(f"مقدار {key} باید بولین باشد")
        elif key == "deficit_method":
            if value not in (DEFICIT_METHOD_CUMULATIVE, DEFICIT_METHOD_LEGACY):
                raise ReportPolicyError("روش کسر کار نامعتبر است")
    for key in (
        "past_no_punch_keeps_duty", "current_day_elapsed_only",
        "exclude_future_days", "late_early_single_count",
    ):
        if merged["deficit_method"] == DEFICIT_METHOD_CUMULATIVE and not merged[key]:
            raise ReportPolicyError(f"{key} در روش تجمیعی باید فعال باشد")
    return merged


# موظفی هفتگی: True = این وضعیت از موظفی کم می‌شود
LEGAL_OT_DUTY_KEYS = (
    "duty_reduce_no_punch",
    "duty_reduce_no_punch_future",
    "duty_reduce_absent",
    "duty_reduce_leave",
    "duty_reduce_hourly_leave",
    "duty_reduce_mission",
    "duty_reduce_hourly_mission",
    "duty_reduce_rest",
)
# کسر کار: deficit_separate_non_working = مبنای کسر کار (True = کارکرد روز کاری، False = کل کارکرد)
LEGAL_OT_DEFICIT_KEYS = (
    "deficit_separate_non_working",
    "deficit_adjust_ordinary_overtime",
)
# برچسب دو گزینهٔ مبنای کسر کار: [False, True]
DEFICIT_BASIS_LABELS = ("کل کارکرد", "کارکرد روز کاری")

LEGAL_OT_DEFAULTS: Dict[str, Any] = {
    "duty_reduce_no_punch": True,
    "duty_reduce_no_punch_future": True,
    "duty_reduce_absent": False,
    "duty_reduce_leave": True,
    "duty_reduce_hourly_leave": True,
    "duty_reduce_mission": True,
    "duty_reduce_hourly_mission": True,
    "duty_reduce_rest": True,
    "deficit_separate_non_working": True,
    "deficit_adjust_ordinary_overtime": False,
    "past_no_punch_keeps_duty": True,
    "current_day_elapsed_only": True,
    "exclude_future_days": True,
    "late_early_single_count": True,
    "deficit_method": DEFICIT_METHOD_CUMULATIVE,
}

# گروه‌بندی فیلدهای قابل‌ویرایش برای UI: (عنوان، راهنما، نوع، ((کلید، برچسب)، …))
# نوع 'flag' = چک‌باکس؛
# 'deficit_basis' = فیلد اول دوگزینه‌ای با DEFICIT_BASIS_LABELS و بقیه چک‌باکس
LEGAL_OT_FIELD_GROUPS = (
    (
        "موظفی هفتگی",
        "تیک‌خورده = این مورد موظفی روز را کم یا صفر می‌کند؛ بدون تیک = موظفی روز حفظ می‌شود.",
        "flag",
        (
            ("duty_reduce_no_punch", "بدون تردد (روزهای گذشته)"),
            ("duty_reduce_no_punch_future", "بدون تردد (امروز و آینده)"),
            ("duty_reduce_absent", "غیبت"),
            ("duty_reduce_leave", "مرخصی روزانه (و استعلاجی)"),
            ("duty_reduce_hourly_leave", "مرخصی ساعتی"),
            ("duty_reduce_mission", "مأموریت روزانه"),
            ("duty_reduce_hourly_mission", "مأموریت ساعتی"),
            ("duty_reduce_rest", "استراحت"),
        ),
    ),
    (
        "کسر کار",
        "کل کارکرد = همهٔ کارکرد کسر کار را پوشش می‌دهد؛ کارکرد روز کاری = فقط کارکرد روزهایی که "
        "وضعیت روز «کاری» است و فرد مرخصی/استراحت/مأموریت نیست. "
        "تهاتر = اضافه‌کار عادی ماه با کسر کار ماه تسویه می‌شود و مقدار کمتر از هر دو کم می‌شود "
        "(جمعه‌کاری، تعطیل‌کاری و کارکرد در روز استراحت/مرخصی تهاتر نمی‌شوند).",
        "deficit_basis",
        (
            ("deficit_separate_non_working", "مبنای محاسبهٔ کسر کار"),
            ("deficit_adjust_ordinary_overtime", "تهاتر اضافه‌کار عادی با کسر کار ماهانه"),
        ),
    ),
)

REPORT_DEFINITIONS: Dict[str, ReportPolicyDefinition] = {
    LEGAL_OVERTIME_MONTHLY: ReportPolicyDefinition(
        key=LEGAL_OVERTIME_MONTHLY,
        label="اضافه‌کار قانونی (ماهانه)",
        schema_version=6,
        defaults=LEGAL_OT_DEFAULTS,
        editable_keys=LEGAL_OT_DUTY_KEYS + LEGAL_OT_DEFICIT_KEYS,
        validate=_validate_legal_ot,
    ),
}


@dataclass(frozen=True)
class ResolvedReportPolicy:
    report_key: str
    settings: Dict[str, Any]
    source: str  # 'db' | 'default'
    policy_id: Optional[int] = None
    effective_from: Optional[date] = None
    version: Optional[int] = None
    extra: Dict[str, Any] = field(default_factory=dict)

    @property
    def label(self) -> str:
        if self.source == "override":
            return "تنظیمات موقت"
        if self.source == "db":
            return f"نسخه {self.policy_id} از {self.effective_from}"
        return "پیش‌فرض سیستم"


def get_definition(report_key: str) -> ReportPolicyDefinition:
    try:
        return REPORT_DEFINITIONS[report_key]
    except KeyError:
        raise ReportPolicyError(f"گزارش ناشناخته: {report_key}")


def default_policy(report_key: str) -> ResolvedReportPolicy:
    definition = get_definition(report_key)
    return ResolvedReportPolicy(
        report_key=report_key,
        settings=dict(definition.defaults),
        source="default",
        version=definition.schema_version,
    )


def validate_settings(report_key: str, settings: Dict[str, Any]) -> Dict[str, Any]:
    return get_definition(report_key).validate(dict(settings or {}))


def resolve_report_policy(db: Session, report_key: str, as_of: date) -> ResolvedReportPolicy:
    """سیاست مؤثر در تاریخ as_of؛ در نبود ردیف، پیش‌فرض کد."""
    definition = get_definition(report_key)
    row = (
        db.query(ReportPolicy)
        .filter(
            ReportPolicy.report_key == report_key,
            ReportPolicy.is_active.is_(True),
            ReportPolicy.effective_from_date <= as_of,
            (ReportPolicy.effective_to_date.is_(None))
            | (ReportPolicy.effective_to_date >= as_of),
        )
        .order_by(ReportPolicy.effective_from_date.desc())
        .first()
    )
    if row is None:
        return default_policy(report_key)
    try:
        settings = definition.validate(dict(row.settings or {}))
    except ReportPolicyError:
        # ردیف خراب نباید گزارش را از کار بیندازد
        return default_policy(report_key)
    return ResolvedReportPolicy(
        report_key=report_key,
        settings=settings,
        source="db",
        policy_id=row.id,
        effective_from=row.effective_from_date,
        version=row.schema_version,
    )


def apply_overrides(
    resolved: ResolvedReportPolicy, overrides: Optional[Dict[str, Any]],
) -> ResolvedReportPolicy:
    """تنظیمات موقت برای یک‌بار تولید گزارش؛ چیزی در DB ذخیره نمی‌شود."""
    if not overrides:
        return resolved
    definition = get_definition(resolved.report_key)
    not_editable = set(overrides) - set(definition.editable_keys)
    if not_editable:
        raise ReportPolicyError(
            f"کلید غیرقابل‌تغییر: {', '.join(sorted(not_editable))}"
        )
    settings = definition.validate({**resolved.settings, **overrides})
    return ResolvedReportPolicy(
        report_key=resolved.report_key,
        settings=settings,
        source="override",
        policy_id=resolved.policy_id,
        effective_from=resolved.effective_from,
        version=resolved.version,
        extra={"base_label": resolved.label},
    )


def month_end(year_j: int, month_j: int) -> date:
    """آخرین روز میلادیِ ماه شمسی (as_of گزارش ماهانه)."""
    if month_j == 12:
        try:
            end = jdatetime.date(year_j, 12, 30)
        except ValueError:
            end = jdatetime.date(year_j, 12, 29)
    else:
        end = jdatetime.date(year_j, month_j + 1, 1) - timedelta(days=1)
    return end.togregorian()


def is_jalali_month_start(d: date) -> bool:
    return jdatetime.date.fromgregorian(date=d).day == 1


def list_versions(db: Session, report_key: str):
    return (
        db.query(ReportPolicy)
        .filter(ReportPolicy.report_key == report_key)
        .order_by(ReportPolicy.effective_from_date.desc(), ReportPolicy.id.desc())
        .all()
    )


def _dump(settings: Optional[Dict[str, Any]]) -> Optional[str]:
    return None if settings is None else json.dumps(settings, ensure_ascii=False, sort_keys=True)


def create_policy_version(
    db: Session,
    report_key: str,
    settings: Dict[str, Any],
    effective_from: date,
    changed_by: Optional[str] = None,
    notes: Optional[str] = None,
) -> ReportPolicy:
    """نسخهٔ جدید؛ نسخهٔ بازِ قبلی یک روز قبل از شروع بسته می‌شود. commit نمی‌کند."""
    definition = get_definition(report_key)
    validated = definition.validate(dict(settings or {}))
    if not is_jalali_month_start(effective_from):
        raise ReportPolicyError("تاریخ شروع باید اول یک ماه شمسی باشد")

    active = (
        db.query(ReportPolicy)
        .filter(ReportPolicy.report_key == report_key, ReportPolicy.is_active.is_(True))
        .all()
    )
    if any(p.effective_from_date >= effective_from for p in active):
        raise ReportPolicyError(
            "نسخه‌ای با تاریخ شروع مساوی یا بعد از این تاریخ وجود دارد"
        )
    previous = resolve_report_policy(db, report_key, effective_from - timedelta(days=1))
    old_dump = _dump(previous.settings)
    for p in active:
        if p.effective_to_date is None or p.effective_to_date >= effective_from:
            p.effective_to_date = effective_from - timedelta(days=1)

    row = ReportPolicy(
        report_key=report_key,
        effective_from_date=effective_from,
        effective_to_date=None,
        is_active=True,
        schema_version=definition.schema_version,
        settings=validated,
        notes=notes,
        created_by=changed_by,
    )
    db.add(row)
    db.flush()
    db.add(PolicyAuditLog(
        entity_type="report_policy",
        entity_id=report_key,
        action="CREATE_VERSION",
        old_value=old_dump,
        new_value=_dump(validated),
        changed_by=changed_by,
        reason=f"نسخهٔ جدید از {effective_from}",
    ))
    return row


def get_active_version(db: Session, report_key: str, policy_id: int) -> ReportPolicy:
    row = (
        db.query(ReportPolicy)
        .filter(
            ReportPolicy.id == policy_id,
            ReportPolicy.report_key == report_key,
            ReportPolicy.is_active.is_(True),
        )
        .first()
    )
    if row is None:
        raise ReportPolicyError("نسخهٔ سیاست یافت نشد")
    return row


def update_policy_version(
    db: Session,
    report_key: str,
    policy_id: int,
    settings: Dict[str, Any],
    changed_by: Optional[str] = None,
    notes: Optional[str] = None,
) -> ReportPolicy:
    """ویرایش تنظیمات/توضیح یک نسخه؛ بازهٔ تاریخ تغییر نمی‌کند. commit نمی‌کند."""
    definition = get_definition(report_key)
    row = get_active_version(db, report_key, policy_id)
    validated = definition.validate(dict(settings or {}))
    old_dump = _dump(row.settings)
    row.settings = validated
    row.schema_version = definition.schema_version
    row.notes = notes
    db.flush()
    db.add(PolicyAuditLog(
        entity_type="report_policy",
        entity_id=report_key,
        action="UPDATE_VERSION",
        old_value=old_dump,
        new_value=_dump(validated),
        changed_by=changed_by,
        reason=f"ویرایش نسخهٔ {row.id} از {row.effective_from_date}",
    ))
    return row


def delete_policy_version(
    db: Session,
    report_key: str,
    policy_id: int,
    changed_by: Optional[str] = None,
) -> None:
    """حذف نرم نسخه؛ نسخهٔ قبلی بازهٔ آن را پوشش می‌دهد. commit نمی‌کند."""
    row = get_active_version(db, report_key, policy_id)
    previous = (
        db.query(ReportPolicy)
        .filter(
            ReportPolicy.report_key == report_key,
            ReportPolicy.is_active.is_(True),
            ReportPolicy.effective_from_date < row.effective_from_date,
        )
        .order_by(ReportPolicy.effective_from_date.desc())
        .first()
    )
    if previous is not None and (
        previous.effective_to_date is None
        or previous.effective_to_date >= row.effective_from_date - timedelta(days=1)
    ):
        previous.effective_to_date = row.effective_to_date
    row.is_active = False
    db.flush()
    db.add(PolicyAuditLog(
        entity_type="report_policy",
        entity_id=report_key,
        action="DELETE_VERSION",
        old_value=_dump(row.settings),
        new_value=None,
        changed_by=changed_by,
        reason=f"حذف نسخهٔ {row.id} از {row.effective_from_date}",
    ))
