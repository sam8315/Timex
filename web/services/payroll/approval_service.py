"""گردش تأیید چندمرحله‌ای لیست حقوق.

تنظیمات مراحل (PayrollApprovalStepSetting) فقط الگو است. با شروع گردش هر لیست،
نسخهٔ ثابتی از مراحل در PayrollRunApprovalStep ذخیره می‌شود و تغییر بعدی تنظیمات
روی آن اثر نمی‌گذارد.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, Iterable, List, Optional, Sequence

from sqlalchemy.orm import Session

from models.employee import Employee
from models.payroll import PayrollApprovalStepSetting, PayrollRun, PayrollRunApprovalStep
from models.user import User
from models.user_permission import UserPermission
from web.permissions import get_role_permission_map, has_permission

APPROVE_PERMISSION = "approve_payroll"

DEFAULT_STEP_TITLES = ("نیروی انسانی", "حسابدار", "مدیر مالی", "مدیر درمانگاه")
LEGACY_STEP_TITLE = "تأیید"
MAX_TITLE_LENGTH = 120


class PayrollApprovalError(Exception):
    pass


# ---------------------------------------------------------------- settings

def ensure_default_settings(db: Session) -> None:
    """اگر هیچ مرحله‌ای تنظیم نشده، مراحل پیش‌فرض ساخته می‌شود."""
    if db.query(PayrollApprovalStepSetting.id).first() is not None:
        return
    for order, title in enumerate(DEFAULT_STEP_TITLES, start=1):
        db.add(PayrollApprovalStepSetting(step_order=order, title=title))
    db.commit()


def list_settings(db: Session, *, ensure_defaults: bool = True) -> List[PayrollApprovalStepSetting]:
    if ensure_defaults:
        ensure_default_settings(db)
    return (
        db.query(PayrollApprovalStepSetting)
        .order_by(PayrollApprovalStepSetting.step_order)
        .all()
    )


def _clean_title(title: str) -> str:
    title = " ".join((title or "").split())
    if not title:
        raise PayrollApprovalError("عنوان مرحله الزامی است")
    if len(title) > MAX_TITLE_LENGTH:
        raise PayrollApprovalError("عنوان مرحله بیش از حد طولانی است")
    return title


def _holders_of_permission(db: Session, users: Sequence[User]) -> set[str]:
    """کاربرانی که مجوز approve_payroll مؤثر دارند، با حداقل کوئری."""
    overrides = {
        row.user_id: bool(row.granted)
        for row in db.query(UserPermission)
        .filter(UserPermission.permission == APPROVE_PERMISSION)
        .all()
    }
    role_cache: Dict[str, bool] = {}
    out: set[str] = set()
    for user in users:
        role = user.role or "user"
        if role not in role_cache:
            role_cache[role] = bool(get_role_permission_map(db, role).get(APPROVE_PERMISSION))
        granted = overrides.get(user.user_id, role_cache[role])
        if granted:
            out.add(user.user_id)
    return out


def display_names(db: Session, user_ids: Iterable[Optional[str]]) -> Dict[str, str]:
    ids = list(dict.fromkeys(uid for uid in user_ids if uid))
    if not ids:
        return {}
    employees = {
        row.user_id: row for row in db.query(Employee).filter(Employee.user_id.in_(ids)).all()
    }
    users = {row.user_id: row for row in db.query(User).filter(User.user_id.in_(ids)).all()}
    names: Dict[str, str] = {}
    for uid in ids:
        emp = employees.get(uid)
        full = ""
        if emp:
            full = f"{(emp.first_name or '').strip()} {(emp.last_name or '').strip()}".strip()
        if not full and uid in users:
            full = (users[uid].name or "").strip()
        names[uid] = full or uid
    return names


def list_eligible_approvers(db: Session) -> List[dict]:
    """همهٔ کاربران ثبت‌شده با ورود وب و مجوز تأیید حقوق؛ مستقل از فهرست کارکنان و حقوق."""
    users = (
        db.query(User)
        .filter(User.web_enabled.is_(True))
        .order_by(User.name, User.user_id)
        .all()
    )
    holders = _holders_of_permission(db, users)
    chosen = [u for u in users if u.user_id in holders]
    names = display_names(db, [u.user_id for u in chosen])
    return [{"user_id": u.user_id, "name": names.get(u.user_id, u.user_id)} for u in chosen]


def _validate_approver(db: Session, approver_user_id: Optional[str]) -> Optional[str]:
    approver_user_id = (approver_user_id or "").strip() or None
    if approver_user_id is None:
        return None
    user = db.query(User).filter(User.user_id == approver_user_id).first()
    if user is None:
        raise PayrollApprovalError("تأییدکننده باید کاربر ثبت‌شده در Timex باشد")
    if not user.web_enabled:
        raise PayrollApprovalError("ورود وب این کاربر غیرفعال است")
    if not has_permission(db, user, APPROVE_PERMISSION):
        raise PayrollApprovalError("این کاربر مجوز «تأیید حقوق» ندارد")
    return approver_user_id


def add_step(db: Session, *, title: str, approver_user_id: Optional[str]) -> PayrollApprovalStepSetting:
    ensure_default_settings(db)
    title = _clean_title(title)
    approver = _validate_approver(db, approver_user_id)
    last = (
        db.query(PayrollApprovalStepSetting.step_order)
        .order_by(PayrollApprovalStepSetting.step_order.desc())
        .first()
    )
    row = PayrollApprovalStepSetting(
        step_order=(last[0] if last else 0) + 1, title=title, approver_user_id=approver
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _get_setting(db: Session, step_id: int) -> PayrollApprovalStepSetting:
    row = db.query(PayrollApprovalStepSetting).filter(PayrollApprovalStepSetting.id == step_id).first()
    if row is None:
        raise PayrollApprovalError("مرحله یافت نشد")
    return row


def update_step(
    db: Session, step_id: int, *, title: str, approver_user_id: Optional[str]
) -> PayrollApprovalStepSetting:
    row = _get_setting(db, step_id)
    row.title = _clean_title(title)
    row.approver_user_id = _validate_approver(db, approver_user_id)
    db.commit()
    db.refresh(row)
    return row


def delete_step(db: Session, step_id: int) -> None:
    rows = list_settings(db)
    target = next((r for r in rows if r.id == step_id), None)
    if target is None:
        raise PayrollApprovalError("مرحله یافت نشد")
    if len(rows) <= 1:
        raise PayrollApprovalError("حداقل یک مرحله باید باقی بماند")
    db.delete(target)
    db.flush()
    for order, row in enumerate([r for r in rows if r.id != step_id], start=1):
        row.step_order = order
    db.commit()


def move_step(db: Session, step_id: int, direction: str) -> None:
    if direction not in ("up", "down"):
        raise PayrollApprovalError("جهت جابه‌جایی نامعتبر است")
    rows = list_settings(db)
    idx = next((i for i, r in enumerate(rows) if r.id == step_id), None)
    if idx is None:
        raise PayrollApprovalError("مرحله یافت نشد")
    other = idx - 1 if direction == "up" else idx + 1
    if other < 0 or other >= len(rows):
        return
    rows[idx], rows[other] = rows[other], rows[idx]
    for order, row in enumerate(rows, start=1):
        row.step_order = order
    db.commit()


# ---------------------------------------------------------------- run snapshot

def has_started(run: PayrollRun) -> bool:
    return any(step.approved_at is not None for step in run.approval_steps)


def snapshot_run(db: Session, run: PayrollRun, *, refresh: bool = False) -> List[PayrollRunApprovalStep]:
    """مراحل را برای این لیست ثبت می‌کند. بدون refresh، نسخهٔ موجود دست‌نخورده می‌ماند.

    با refresh فقط وقتی هنوز هیچ تأییدی ثبت نشده مراحل از تنظیمات فعلی دوباره ساخته می‌شود.
    """
    existing = list(run.approval_steps)
    if existing and not refresh:
        return existing
    if existing and has_started(run):
        return existing
    settings = list_settings(db)
    if existing:
        db.query(PayrollRunApprovalStep).filter(PayrollRunApprovalStep.run_id == run.id).delete(
            synchronize_session=False
        )
        db.flush()
        db.expire(run, ["approval_steps"])
    for row in settings:
        db.add(
            PayrollRunApprovalStep(
                run_id=run.id,
                step_order=row.step_order,
                title=row.title,
                approver_user_id=row.approver_user_id,
            )
        )
    db.flush()
    db.expire(run, ["approval_steps"])
    return list(run.approval_steps)


def is_complete(run: PayrollRun) -> bool:
    """بدون مرحله (اجرای قدیمی) همان وضعیت run ملاک است."""
    steps = run.approval_steps
    if not steps:
        return True
    return all(step.approved_at is not None for step in steps)


# ---------------------------------------------------------------- views

def _legacy_step(run: PayrollRun) -> dict:
    return {
        "order": 1,
        "title": LEGACY_STEP_TITLE,
        "approver_id": run.approved_by,
        "approver_name": "",
        "approved": True,
        "approved_by": run.approved_by,
        "approved_by_name": "",
        "approved_at": run.approved_at,
    }


def build_workflows(db: Session, runs: Sequence[PayrollRun]) -> Dict[int, dict]:
    """نمای گردش هر لیست برای جدول و صفحهٔ جزئیات.

    کلیدها: steps، total، done، started، snapshot (آیا مراحل برای همین لیست ثابت شده‌اند).
    لیست قدیمی تأییدشده بدون مرحله، یک مرحلهٔ مجازی از approved_by/approved_at می‌گیرد.
    لیست محاسبه‌شدهٔ بدون مرحله، پیش‌نمایش از تنظیمات فعلی است و ذخیره نمی‌شود.
    """
    settings = None
    id_pool: List[Optional[str]] = []
    for run in runs:
        for step in run.approval_steps:
            id_pool.extend([step.approver_user_id, step.approved_by])
        if not run.approval_steps:
            id_pool.append(run.approved_by)
    needs_settings = any(not r.approval_steps and r.status == "calculated" for r in runs)
    if needs_settings:
        settings = list_settings(db)
        id_pool.extend(row.approver_user_id for row in settings)
    names = display_names(db, id_pool)

    def name_of(uid: Optional[str]) -> str:
        return names.get(uid, uid or "") if uid else ""

    out: Dict[int, dict] = {}
    for run in runs:
        steps: List[dict] = []
        snapshot = bool(run.approval_steps)
        if run.approval_steps:
            for step in run.approval_steps:
                steps.append(
                    {
                        "order": step.step_order,
                        "title": step.title,
                        "approver_id": step.approver_user_id,
                        "approver_name": name_of(step.approver_user_id),
                        "approved": step.approved_at is not None,
                        "approved_by": step.approved_by,
                        "approved_by_name": name_of(step.approved_by),
                        "approved_at": step.approved_at,
                    }
                )
        elif run.status in ("approved", "published"):
            legacy = _legacy_step(run)
            legacy["approver_name"] = name_of(run.approved_by)
            legacy["approved_by_name"] = name_of(run.approved_by)
            steps.append(legacy)
        elif run.status == "calculated" and settings is not None:
            for row in settings:
                steps.append(
                    {
                        "order": row.step_order,
                        "title": row.title,
                        "approver_id": row.approver_user_id,
                        "approver_name": name_of(row.approver_user_id),
                        "approved": False,
                        "approved_by": None,
                        "approved_by_name": "",
                        "approved_at": None,
                    }
                )
        done = sum(1 for s in steps if s["approved"])
        out[run.id] = {
            "steps": steps,
            "total": len(steps),
            "done": done,
            "started": done > 0,
            "snapshot": snapshot,
        }
    return out


def signature_boxes(workflow: dict, format_time) -> List[dict]:
    """کادرهای چاپ/PDF از همان نمای گردش، به ترتیب مراحل.

    name بالا، role عنوان مرحله زیر آن (وقتی نام شخص مشخص است)، time فقط برای مرحلهٔ تأییدشده.
    """
    boxes: List[dict] = []
    for step in workflow.get("steps") or []:
        person = step["approved_by_name"] or step["approver_name"]
        boxes.append(
            {
                "name": person or step["title"],
                "role": step["title"] if person else "",
                "time": format_time(step["approved_at"]) if step["approved"] and step["approved_at"] else "",
                "approved": bool(step["approved"]),
            }
        )
    return boxes


# ---------------------------------------------------------------- approving

def _next_pending(steps: Sequence[PayrollRunApprovalStep]) -> Optional[PayrollRunApprovalStep]:
    for step in sorted(steps, key=lambda s: s.step_order):
        if step.approved_at is None:
            return step
    return None


def check_can_approve(
    steps: Sequence[PayrollRunApprovalStep], user_id: str, *, has_approve_permission: bool
) -> tuple[Optional[PayrollRunApprovalStep], Optional[str]]:
    """(مرحلهٔ مجاز، None) یا (None، دلیل رد). منطق خالص و بدون دیتابیس."""
    if not has_approve_permission:
        return None, "مجوز تأیید حقوق را ندارید"
    pending = _next_pending(steps)
    if pending is None:
        return None, "همهٔ مراحل این لیست تأیید شده است"
    if pending.approver_user_id is None or pending.approver_user_id == user_id:
        return pending, None
    mine = [s for s in steps if s.approver_user_id == user_id]
    if any(s.approved_at is None for s in mine):
        return None, f"هنوز نوبت شما نیست؛ ابتدا باید مرحله «{pending.title}» تأیید شود"
    if mine:
        return None, "شما مرحلهٔ خود را قبلاً تأیید کرده‌اید"
    return None, f"مرحلهٔ جاری «{pending.title}» به شما اختصاص ندارد"


def approval_state_for(db: Session, run: PayrollRun, user: User) -> tuple[bool, Optional[str]]:
    """برای نمایش دکمه: آیا این کاربر الان می‌تواند تأیید کند؟"""
    if run.status != "calculated":
        return False, None
    steps = list(run.approval_steps)
    if not steps:
        steps_for_check = [
            PayrollRunApprovalStep(step_order=row.step_order, title=row.title,
                                   approver_user_id=row.approver_user_id)
            for row in list_settings(db)
        ]
    else:
        steps_for_check = steps
    step, reason = check_can_approve(
        steps_for_check, user.user_id,
        has_approve_permission=has_permission(db, user, APPROVE_PERMISSION),
    )
    return step is not None, reason


def approve_next_step(db: Session, run_id: int, user_id: str) -> PayrollRun:
    """مرحلهٔ جاری را برای این کاربر تأیید می‌کند. پس از آخرین مرحله لیست تأییدشده می‌شود."""
    run = db.query(PayrollRun).filter(PayrollRun.id == run_id).with_for_update().first()
    if run is None:
        raise PayrollApprovalError("اجرای حقوق یافت نشد")
    if run.calculating_by:
        raise PayrollApprovalError("این لیست در حال محاسبه است")
    if run.status != "calculated":
        raise PayrollApprovalError("فقط اجرای محاسبه‌شده قابل تأیید است")
    user = db.query(User).filter(User.user_id == user_id).first()
    if user is None:
        raise PayrollApprovalError("کاربر یافت نشد")
    steps = snapshot_run(db, run)
    step, reason = check_can_approve(
        steps, user_id, has_approve_permission=has_permission(db, user, APPROVE_PERMISSION)
    )
    if step is None:
        db.rollback()
        raise PayrollApprovalError(reason or "تأیید مجاز نیست")
    now = datetime.now(timezone.utc)
    step.approved_by = user_id
    step.approved_at = now
    if _next_pending(steps) is None:
        run.status = "approved"
        run.approved_at = now
        run.approved_by = user_id
    db.commit()
    return run


def reset_for_reopen(db: Session, run: PayrollRun) -> str:
    """بازگشایی لیست: تأییدها صفر و مراحل از تنظیمات فعلی دوباره ثبت می‌شود.

    متن سابقهٔ تأییدهای قبلی را برمی‌گرداند تا در یادداشت لیست بماند.
    """
    names = display_names(
        db, [s.approved_by for s in run.approval_steps if s.approved_by]
    )
    lines = []
    for step in run.approval_steps:
        if step.approved_at is None:
            continue
        who = names.get(step.approved_by, step.approved_by or "")
        lines.append(f"{step.title}: {who} @ {step.approved_at.isoformat(timespec='seconds')}")
    if not run.approval_steps and run.approved_by:
        lines.append(f"{LEGACY_STEP_TITLE}: {run.approved_by}"
                     + (f" @ {run.approved_at.isoformat(timespec='seconds')}" if run.approved_at else ""))
    # تأییدهای قبلی (کامل یا ناقص) کنار می‌روند؛ نسخهٔ قبلی بی‌شرط جایگزین می‌شود.
    db.query(PayrollRunApprovalStep).filter(PayrollRunApprovalStep.run_id == run.id).delete(
        synchronize_session=False
    )
    db.flush()
    db.expire(run, ["approval_steps"])
    snapshot_run(db, run)
    run.approved_at = None
    run.approved_by = None
    return "; ".join(lines)
