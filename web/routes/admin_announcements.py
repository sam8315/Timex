"""Admin CRUD for system announcements."""
from datetime import datetime
from pathlib import Path
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from web.dependencies import get_db, require_admin
from web.session import make_csrf_token, check_csrf_token
from models.user import User
from models.system_announcement import SystemAnnouncement

router = APIRouter(tags=["Admin Announcements"])
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))


def _csrf(request: Request, user: User):
    return make_csrf_token(user.user_id)


@router.get("/announcements", response_class=HTMLResponse)
async def admin_list(request: Request, db: Session = Depends(get_db), user: User = Depends(require_admin)):
    rows = db.query(SystemAnnouncement).order_by(SystemAnnouncement.created_at.desc()).all()
    return templates.TemplateResponse(request, "admin/announcements.html", {"user": user, "rows": rows, "csrf_token": _csrf(request, user)})


@router.get("/announcements/new", response_class=HTMLResponse)
async def admin_new(request: Request, user: User = Depends(require_admin)):
    return templates.TemplateResponse(request, "admin/announcement_form.html", {"user": user, "announcement": None, "csrf_token": _csrf(request, user)})


@router.post("/announcements/create")
async def admin_create(
    request: Request, title: str = Form(...), summary: str = Form(""), content: str = Form(...),
    announcement_type: str = Form("feature"), csrf_token: str = Form(...),
    user: User = Depends(require_admin), db: Session = Depends(get_db),
):
    if not check_csrf_token(csrf_token, user.user_id):
        raise HTTPException(403, "CSRF token invalid")
    ann = SystemAnnouncement(title=title.strip(), summary=summary.strip() or None, content=content.strip(),
                             announcement_type=announcement_type, is_active=True,
                             published_at=datetime.now(), created_by=user.user_id)
    db.add(ann)
    db.commit()
    return RedirectResponse("/admin/announcements", status_code=303)


@router.get("/announcements/{ann_id}/edit", response_class=HTMLResponse)
async def admin_edit(request: Request, ann_id: int, db: Session = Depends(get_db), user: User = Depends(require_admin)):
    ann = db.query(SystemAnnouncement).filter(SystemAnnouncement.id == ann_id).first()
    if not ann:
        raise HTTPException(404, "Announcement not found")
    return templates.TemplateResponse(request, "admin/announcement_form.html", {"user": user, "announcement": ann, "csrf_token": _csrf(request, user)})


@router.post("/announcements/{ann_id}/update")
async def admin_update(
    request: Request, ann_id: int, title: str = Form(...), summary: str = Form(""), content: str = Form(...),
    announcement_type: str = Form("feature"), is_active: bool = Form(False), csrf_token: str = Form(...),
    user: User = Depends(require_admin), db: Session = Depends(get_db),
):
    if not check_csrf_token(csrf_token, user.user_id):
        raise HTTPException(403, "CSRF token invalid")
    ann = db.query(SystemAnnouncement).filter(SystemAnnouncement.id == ann_id).first()
    if not ann:
        raise HTTPException(404, "Announcement not found")
    ann.title, ann.summary, ann.content = title.strip(), summary.strip() or None, content.strip()
    ann.announcement_type, ann.is_active = announcement_type, is_active
    if ann.is_active and ann.published_at is None:
        ann.published_at = datetime.now()
    db.commit()
    return RedirectResponse("/admin/announcements", status_code=303)
