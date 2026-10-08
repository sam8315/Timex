"""درخواست و تأیید تردد فراموش‌شده."""
from datetime import datetime
from urllib.parse import quote

import jdatetime
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from models.attendance import Attendance
from models.employee import Employee
from models.missed_attendance_request import (
    PUNCH_LABELS,
    REASON_LABELS,
    REASON_OPTIONS,
    MissedAttendanceRequest,
)
from models.user import User
from web.dependencies import get_current_user, get_db, require_admin
from web.permissions import enforce_permission

router = APIRouter(tags=["Missed Attendance"])
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))

USER_LIST_PATH = "/attendance/missed"
ADMIN_LIST_PATH = "/admin/missed-attendance"


def build_redirect_url(path: str, key: str, value: str) -> str:
    return f"{path}?{key}={quote(value)}"


def _wall_clock(value: datetime) -> datetime:
    if value.tzinfo is not None:
        value = value.astimezone().replace(tzinfo=None)
    return value


def format_punch_at(value: datetime) -> str:
    wall = _wall_clock(value)
    return jdatetime.datetime.fromgregorian(datetime=wall).strftime("%Y/%m/%d %H:%M")


def parse_submission(date_str: str, time_str: str, punch: str, reason_code: str, reason_text: str):
    """اعتبارسنجی فرم. در صورت خطا ValueError با پیام فارسی."""
    try:
        j_date = jdatetime.datetime.strptime(date_str.strip(), "%Y/%m/%d").date()
        g_date = j_date.togregorian()
    except ValueError:
        raise ValueError("تاریخ شمسی نامعتبر است")

    try:
        hour, minute = map(int, time_str.strip().split(":"))
        if hour < 0 or hour > 23 or minute < 0 or minute > 59:
            raise ValueError
        punch_at = datetime(g_date.year, g_date.month, g_date.day, hour, minute)
    except ValueError:
        raise ValueError("ساعت نامعتبر است")

    if punch_at > datetime.now():
        raise ValueError("زمان تردد نمی‌تواند در آینده باشد")

    try:
        punch_value = int(punch)
    except (TypeError, ValueError):
        punch_value = -1
    if punch_value not in PUNCH_LABELS:
        raise ValueError("نوع تردد نامعتبر است")

    code = (reason_code or "").strip()
    if code not in REASON_LABELS:
        raise ValueError("دلیل نامعتبر است")

    text = (reason_text or "").strip()
    if code == "other":
        if not text:
            raise ValueError("برای گزینه سایر، نوشتن دلیل الزامی است")
        if len(text) > 500:
            raise ValueError("متن دلیل طولانی است")
    else:
        text = ""

    return punch_at, punch_value, code, text or None


def _row_dict(req: MissedAttendanceRequest, employee_name: str | None = None) -> dict:
    return {
        "id": req.id,
        "user_id": req.user_id,
        "employee_name": employee_name or req.user_id,
        "punch_at_j": format_punch_at(req.punch_at),
        "punch_label": req.punch_label,
        "reason_label": req.reason_label,
        "status": req.status,
        "status_name": req.status_name,
        "rejection_reason": req.rejection_reason or "",
        "created_at_j": format_punch_at(req.created_at) if req.created_at else "",
    }


def _clock_label(value) -> str:
    if not isinstance(value, datetime):
        return "—"
    wall = _wall_clock(value)
    return wall.strftime("%H:%M")


def _suggested_punch(item: dict) -> str:
    issue = item.get("issue")
    if issue == "missing_enter" or item.get("exit_count", 0) > item.get("enter_count", 0):
        return "0"
    if issue == "missing_exit" or item.get("enter_count", 0) > item.get("exit_count", 0):
        return "1"
    return ""


def _incomplete_rows(db: Session, user_id: str) -> tuple[str, list[dict]]:
    from web.services.incomplete_attendance_service import (
        default_month_range,
        find_incomplete_attendances,
    )

    month_names = {
        1: "فروردین", 2: "اردیبهشت", 3: "خرداد", 4: "تیر",
        5: "مرداد", 6: "شهریور", 7: "مهر", 8: "آبان",
        9: "آذر", 10: "دی", 11: "بهمن", 12: "اسفند",
    }
    today_j = jdatetime.date.today()
    month_label = f"{month_names.get(today_j.month, '')} {today_j.year}"
    from_date, to_date = default_month_range()
    items = find_incomplete_attendances(
        db, from_date, to_date, user_id=user_id
    )
    rows = []
    for item in items:
        punch = _suggested_punch(item)
        rows.append({
            "date_j": item["date_j"],
            "type": item["type"],
            "enter_count": item["enter_count"],
            "exit_count": item["exit_count"],
            "first_enter": _clock_label(item.get("first_enter")),
            "last_exit": _clock_label(item.get("last_exit")),
            "suggested_punch": punch,
        })
    return month_label, rows


def _employee_names(db: Session, user_ids: list[str]) -> dict[str, str]:
    if not user_ids:
        return {}
    rows = db.query(Employee).filter(Employee.user_id.in_(user_ids)).all()
    return {row.user_id: row.full_name for row in rows}


@router.get(USER_LIST_PATH, response_class=HTMLResponse)
async def missed_attendance_page(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    rows = (
        db.query(MissedAttendanceRequest)
        .filter(MissedAttendanceRequest.user_id == user.user_id)
        .order_by(MissedAttendanceRequest.created_at.desc())
        .all()
    )
    month_label, incomplete_rows = _incomplete_rows(db, user.user_id)
    return templates.TemplateResponse(request, "missed_attendance.html", {
        "user": user,
        "is_admin": user.is_admin,
        "reason_options": REASON_OPTIONS,
        "requests": [_row_dict(row) for row in rows],
        "incomplete_rows": incomplete_rows,
        "incomplete_month_label": month_label,
    })


@router.post(USER_LIST_PATH)
async def submit_missed_attendance(
    date_str: str = Form(...),
    time_str: str = Form(...),
    punch: str = Form(...),
    reason_code: str = Form(...),
    reason_text: str = Form(""),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        punch_at, punch_value, code, text = parse_submission(
            date_str, time_str, punch, reason_code, reason_text
        )
        active = db.query(Attendance).filter(
            Attendance.user_id == user.user_id,
            Attendance.timestamp == punch_at,
            Attendance.is_deleted == False,  # noqa: E712
        ).first()
        if active:
            raise ValueError("برای این زمان قبلاً تردد ثبت شده است")

        pending = db.query(MissedAttendanceRequest).filter(
            MissedAttendanceRequest.user_id == user.user_id,
            MissedAttendanceRequest.punch_at == punch_at,
            MissedAttendanceRequest.status == "P",
        ).first()
        if pending:
            raise ValueError("درخواست در انتظار برای این زمان وجود دارد")

        db.add(MissedAttendanceRequest(
            user_id=user.user_id,
            punch_at=punch_at,
            punch=punch_value,
            reason_code=code,
            reason_text=text,
            status="P",
        ))
        db.commit()
        return RedirectResponse(
            url=build_redirect_url(USER_LIST_PATH, "success", "درخواست ثبت شد و پس از تأیید اعمال می‌شود"),
            status_code=302,
        )
    except ValueError as exc:
        db.rollback()
        return RedirectResponse(
            url=build_redirect_url(USER_LIST_PATH, "error", str(exc)),
            status_code=302,
        )


@router.post("/attendance/missed/{request_id}/cancel")
async def cancel_missed_attendance(
    request_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    row = db.query(MissedAttendanceRequest).filter(
        MissedAttendanceRequest.id == request_id,
        MissedAttendanceRequest.user_id == user.user_id,
    ).first()
    if not row:
        return RedirectResponse(
            url=build_redirect_url(USER_LIST_PATH, "error", "درخواست یافت نشد"),
            status_code=302,
        )
    if row.status != "P":
        return RedirectResponse(
            url=build_redirect_url(USER_LIST_PATH, "error", "فقط درخواست در انتظار قابل لغو است"),
            status_code=302,
        )
    row.status = "C"
    db.commit()
    return RedirectResponse(
        url=build_redirect_url(USER_LIST_PATH, "success", "درخواست لغو شد"),
        status_code=302,
    )


@router.get(ADMIN_LIST_PATH, response_class=HTMLResponse)
async def admin_missed_attendance_page(
    request: Request,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    enforce_permission(db, user, "approve_missed_attendance")
    rows = (
        db.query(MissedAttendanceRequest)
        .filter(MissedAttendanceRequest.status == "P")
        .order_by(MissedAttendanceRequest.created_at.asc())
        .all()
    )
    names = _employee_names(db, [row.user_id for row in rows])
    return templates.TemplateResponse(request, "admin/missed_attendance.html", {
        "user": user,
        "is_admin": True,
        "requests": [_row_dict(row, names.get(row.user_id)) for row in rows],
        "pending_count": len(rows),
    })


@router.post("/admin/missed-attendance/{request_id}/approve")
async def approve_missed_attendance(
    request_id: int,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    enforce_permission(db, user, "approve_missed_attendance")
    row = db.query(MissedAttendanceRequest).filter(
        MissedAttendanceRequest.id == request_id
    ).first()
    if not row:
        return RedirectResponse(
            url=build_redirect_url(ADMIN_LIST_PATH, "error", "درخواست یافت نشد"),
            status_code=302,
        )
    if row.status != "P":
        return RedirectResponse(
            url=build_redirect_url(ADMIN_LIST_PATH, "error", "این درخواست قبلاً بررسی شده است"),
            status_code=302,
        )

    record = Attendance(
        user_id=row.user_id,
        timestamp=row.punch_at,
        punch=row.punch,
        status=15,
        source="M",
    )
    db.add(record)
    try:
        db.flush()
        row.status = "A"
        row.attendance_id = record.id
        row.reviewed_by = user.user_id
        row.reviewed_at = datetime.now()
        db.commit()
    except IntegrityError:
        db.rollback()
        return RedirectResponse(
            url=build_redirect_url(
                ADMIN_LIST_PATH,
                "error",
                "ثبت تردد ممکن نشد؛ برای این زمان رکورد تردد وجود دارد",
            ),
            status_code=302,
        )

    return RedirectResponse(
        url=build_redirect_url(ADMIN_LIST_PATH, "success", "تردد ثبت شد"),
        status_code=302,
    )


@router.post("/admin/missed-attendance/{request_id}/reject")
async def reject_missed_attendance(
    request_id: int,
    rejection_reason: str = Form(""),
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    enforce_permission(db, user, "approve_missed_attendance")
    row = db.query(MissedAttendanceRequest).filter(
        MissedAttendanceRequest.id == request_id
    ).first()
    if not row:
        return RedirectResponse(
            url=build_redirect_url(ADMIN_LIST_PATH, "error", "درخواست یافت نشد"),
            status_code=302,
        )
    if row.status != "P":
        return RedirectResponse(
            url=build_redirect_url(ADMIN_LIST_PATH, "error", "این درخواست قبلاً بررسی شده است"),
            status_code=302,
        )
    row.status = "R"
    row.rejection_reason = rejection_reason.strip() or None
    row.reviewed_by = user.user_id
    row.reviewed_at = datetime.now()
    db.commit()
    return RedirectResponse(
        url=build_redirect_url(ADMIN_LIST_PATH, "success", "درخواست رد شد"),
        status_code=302,
    )
