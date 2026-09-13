"""Admin API and UI for announcements (create/edit/publish/deactivate)."""
from fastapi import APIRouter, Request, Depends, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path
from sqlalchemy.orm import Session
from sqlalchemy import desc
from web.dependencies import get_db, require_admin
from web.session import make_csrf_token, check_csrf_token
from models.user import User
from models.system_announcement import SystemAnnouncement
import jdatetime

router = APIRouter(tags=["Admin Announcements"])
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))


@router.get("/announcements", response_class=HTMLResponse)
async def admin_ann_list(request: Request, db: Session = Depends(get_db), user: User = Depends(require_admin)):
    rows = db.query(SystemAnnouncement).order_by(desc(SystemAnnouncement.created_at)).all()
    return templates.TemplateResponse(request, "admin/announcements.html", {
        "items": rows,
        "user": user,
        "csrf_token": make_csrf_token(user.user_id),
    })


@router.get("/announcements/new", response_class=HTMLResponse)
async def admin_ann_new(request: Request, db: Session = Depends(get_db), user: User = Depends(require_admin)):
    return templates.TemplateResponse(request, "admin/announcement_form.html", {
        "item": None,
        "user": user,
        "csrf_token": make_csrf_token(user.user_id),
    })


@router.post("/announcements/create")
async def admin_ann_create(
    request: Request,
    title: str = Form(""),
    summary: str = Form(""),
    content: str = Form(""),
    announcement_type: str = Form("general"),
    is_active: bool = Form(True),
    published_at: str = Form(""),
    expires_at: str = Form(""),
    csrf_token: str = Form(""),
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    if not check_csrf_token(csrf_token, user.user_id):
        raise HTTPException(status_code=403, detail="توکن امنیتی نامعتبر")
    ann = SystemAnnouncement(
        title=title,
        summary=summary or None,
        content=content or None,
        announcement_type=announcement_type,
        is_active=is_active,
        created_by=user.user_id,
    )
    if published_at:
        try:
            ann.published_at = jdatetime.date.fromgregorian(date=jdatetime.datetime.strptime(published_at, "%Y/%m/%d").date()).togregorian()
        except Exception:
            pass
    db.add(ann)
    db.commit()
    return RedirectResponse(url="/admin/announcements", status_code=303)


@router.get("/announcements/{ann_id}/edit", response_class=HTMLResponse)
async def admin_ann_edit(request: Request, ann_id: int, db: Session = Depends(get_db), user: User = Depends(require_admin)):
    ann = db.query(SystemAnnouncement).filter(SystemAnnouncement.id == ann_id).first()
    if not ann:
        raise HTTPException(status_code=404, detail="یافت نشد")
    return templates.TemplateResponse(request, "admin/announcement_form.html", {
        "item": ann,
        "user": user,
        "csrf_token": make_csrf_token(user.user_id),
    })


@router.post("/announcements/{ann_id}/update")
async def admin_ann_update(
    request: Request,
    ann_id: int,
    title: str = Form(""),
    summary: str = Form(""),
    content: str = Form(""),
    announcement_type: str = Form("general"),
    is_active: bool = Form(True),
    csrf_token: str = Form(""),
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    if not check_csrf_token(csrf_token, user.user_id):
        raise HTTPException(status_code=403, detail="توکن امنیتی نامعتبر")
    ann = db.query(SystemAnnouncement).filter(SystemAnnouncement.id == ann_id).first()
    if not ann:
        raise HTTPException(status_code=404, detail="یافت نشد")
    ann.title = title
    ann.summary = summary or None
    ann.content = content or None
    ann.announcement_type = announcement_type
    ann.is_active = is_active
    db.commit()
    return RedirectResponse(url="/admin/announcements", status_code=303)
