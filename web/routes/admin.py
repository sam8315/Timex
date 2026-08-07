"""پنل مدیریت"""
from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path
from sqlalchemy.orm import Session
import jdatetime

from web.dependencies import get_db, require_admin
from models.user import User
from models.employee import Employee
from models.leave_request import LeaveRequest
from core.leave_request_manager import LeaveRequestManager

router = APIRouter(prefix="/admin", tags=["Admin"])
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))


@router.get("/", response_class=HTMLResponse)
async def admin_dashboard(
    request: Request,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    total_employees = db.query(Employee).filter(Employee.is_active == True).count()
    total_web_users = db.query(User).filter(User.web_enabled == True).count()
    pending_requests = db.query(LeaveRequest).filter(LeaveRequest.status == 'P').count()

    pending_list = db.query(LeaveRequest).filter(
        LeaveRequest.status == 'P'
    ).order_by(LeaveRequest.created_at.asc()).limit(10).all()

    return templates.TemplateResponse(request, "admin/dashboard.html", {
        "user": user,
        "total_employees": total_employees,
        "total_web_users": total_web_users,
        "pending_requests": pending_requests,
        "pending_list": pending_list,
        "is_admin": True,
    })


@router.get("/users", response_class=HTMLResponse)
async def admin_users(
    request: Request,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    users = db.query(User).order_by(User.user_id).all()

    user_details = []
    for u in users:
        emp = db.query(Employee).filter(Employee.user_id == u.user_id).first()
        user_details.append({'web_user': u, 'employee': emp})

    return templates.TemplateResponse(request, "admin/users.html", {
        "user": user,
        "users": user_details,
        "is_admin": True,
    })