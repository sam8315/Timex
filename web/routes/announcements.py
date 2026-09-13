"""
User announcements UI and API.
- GET /announcements
- POST /announcements/{id}/seen (CSRF protected HTML flow)
- GET /api/announcements/unread
- POST /api/announcements/{id}/seen (CSRF protected)
- GET /api/announcements/count
- GET /api/announcements/history
"""
from pathlib import Path

from fastapi import APIRouter, Request, Depends, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from models.user import User
from web.dependencies import get_db, get_current_user
from web.services.announcement_service import (
    get_unread_count,
    list_history,
    list_unread,
    mark_as_seen,
)
from web.session import check_csrf_token, make_csrf_token

router = APIRouter(tags=["Announcements"])
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))


@router.get("/announcements", response_class=HTMLResponse)
async def announcements_page(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    unread = list_unread(db, user.user_id)
    history = list_history(db, user.user_id, limit=20)
    return templates.TemplateResponse(request, "announcements.html", {
        "unread_announcements": unread,
        "history": history,
        "announcement_count": len(unread),
        "user": user,
        "csrf_token": make_csrf_token(user.user_id),
    })


@router.post("/announcements/{announcement_id}/seen")
async def mark_announcement_seen_page(
    request: Request,
    announcement_id: int,
    csrf_token: str = Form(""),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not check_csrf_token(csrf_token, user.user_id):
        raise HTTPException(status_code=403, detail="توکن امنیتی نامعتبر")

    unread_ids = {announcement.id for announcement in list_unread(db, user.user_id)}
    if announcement_id not in unread_ids:
        raise HTTPException(
            status_code=404,
            detail="اعلان موردنظر یافت نشد یا قبلاً مشاهده شده است",
        )

    mark_as_seen(db, user.user_id, announcement_id)
    return RedirectResponse(url="/announcements", status_code=303)


@router.get("/api/announcements/unread")
async def api_unread(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    announcements = list_unread(db, user.user_id)
    return {
        "count": len(announcements),
        "items": [a.to_dict() for a in announcements],
    }


@router.get("/api/announcements/count")
async def api_unread_count(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return {"count": get_unread_count(db, user.user_id)}


@router.post("/api/announcements/{announcement_id}/seen")
async def api_mark_seen(
    request: Request,
    announcement_id: int,
    csrf_token: str = Form(""),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not check_csrf_token(csrf_token, user.user_id):
        raise HTTPException(status_code=403, detail="توکن امنیتی نامعتبر")
    ok = mark_as_seen(db, user.user_id, announcement_id)
    return {"success": ok, "announcement_id": announcement_id}


@router.get("/api/announcements/history")
async def api_history(
    request: Request,
    limit: int = 20,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    items = list_history(db, user.user_id, limit=limit)
    return {"items": items}
