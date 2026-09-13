"""User-facing announcement routes."""
from pathlib import Path
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from web.dependencies import get_db, get_current_user, check_password_change
from web.session import make_csrf_token, check_csrf_token
from models.user import User
from web.services.announcement_service import list_unread, list_history, get_unread_count, mark_as_seen

router = APIRouter(tags=["Announcements"])
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))


@router.get("/announcements", response_class=HTMLResponse)
async def announcements_page(request: Request, user: User = Depends(check_password_change), db: Session = Depends(get_db)):
    unread = list_unread(db, user.user_id)
    history = list_history(db, user.user_id)
    return templates.TemplateResponse(request, "announcements.html", {
        "user": user,
        "unread_announcements": unread,
        "history": history,
        "announcement_count": len(unread),
        "csrf_token": make_csrf_token(user.user_id),
    })


@router.get("/api/announcements/unread")
async def unread_api(user: User = Depends(check_password_change), db: Session = Depends(get_db)):
    return {"count": get_unread_count(db, user.user_id), "items": [
        {"id": a.id, "title": a.title, "summary": a.summary, "content": a.content,
         "type": a.announcement_type, "published_at": a.published_at.isoformat() if a.published_at else None}
        for a in list_unread(db, user.user_id)
    ]}


@router.post("/api/announcements/{announcement_id}/seen")
async def seen_api(
    announcement_id: int,
    request: Request,
    csrf_token: str = Form(...),
    user: User = Depends(check_password_change),
    db: Session = Depends(get_db),
):
    if not check_csrf_token(csrf_token, user.user_id):
        raise HTTPException(status_code=403, detail="CSRF token invalid")
    if not mark_as_seen(db, user.user_id, announcement_id):
        raise HTTPException(status_code=404, detail="Announcement not found")
    return {"ok": True, "count": get_unread_count(db, user.user_id)}
