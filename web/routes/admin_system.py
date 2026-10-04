"""
Admin Service Monitoring: JSON API + HTML page (Phases 5C / 6).

Reads only through core.service_health_status — no direct SQL / SCM / logs.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from core.service_health_status import (
    ServiceHealthStatus,
    get_service_health_status,
    list_service_health_statuses,
)
from models.service_health import SERVICE_NAMES
from models.user import User
from web.dependencies import get_db, require_admin
from web.permissions import enforce_permission, has_permission

router = APIRouter(tags=["Admin System Monitoring"])
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))


def _serialize_dt(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat()


def _status_to_dict(status: ServiceHealthStatus) -> dict[str, Any]:
    return {
        "service_name": status.service_name,
        "process_state": status.process_state,
        "health_state": status.health_state,
        "started_at": _serialize_dt(status.started_at),
        "last_heartbeat_at": _serialize_dt(status.last_heartbeat_at),
        "last_success_at": _serialize_dt(status.last_success_at),
        "last_error_at": _serialize_dt(status.last_error_at),
        "last_error_code": status.last_error_code,
        "last_error_summary": status.last_error_summary,
        "metrics": status.metrics,
        "checked_at": _serialize_dt(status.checked_at),
    }


@router.get("/system", response_class=HTMLResponse)
async def admin_system_services_page(
    request: Request,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Operator page shell — data is loaded from the JSON API in the browser."""
    enforce_permission(db, user, "view_system_monitoring")
    return templates.TemplateResponse(
        request,
        "admin/system_services.html",
        {
            "user": user,
            "is_admin": True,
            "can_view_system_monitoring": has_permission(
                db, user, "view_system_monitoring"
            ),
        },
    )


@router.get("/system/services")
def admin_list_services(
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Return aggregated health for web / adms / bale."""
    enforce_permission(db, user, "view_system_monitoring")
    try:
        statuses = list_service_health_statuses()
    except Exception:
        raise HTTPException(
            status_code=500,
            detail="خواندن وضعیت سرویس‌ها ممکن نشد",
        ) from None
    return {"services": [_status_to_dict(item) for item in statuses]}


@router.get("/system/services/{service_name}")
def admin_get_service(
    service_name: str,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Return aggregated health for one service."""
    enforce_permission(db, user, "view_system_monitoring")
    if service_name not in SERVICE_NAMES:
        raise HTTPException(status_code=404, detail="سرویس یافت نشد")
    try:
        status = get_service_health_status(service_name)
    except ValueError:
        raise HTTPException(status_code=404, detail="سرویس یافت نشد") from None
    except Exception:
        raise HTTPException(
            status_code=500,
            detail="خواندن وضعیت سرویس ممکن نشد",
        ) from None
    return _status_to_dict(status)
