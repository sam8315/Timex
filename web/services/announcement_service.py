"""سرویس اعلان‌ها."""
from datetime import datetime
from typing import List
from sqlalchemy import func
from sqlalchemy.orm import Session
from models.system_announcement import SystemAnnouncement
from models.user_announcement import UserAnnouncement


def list_unread(db: Session, user_id: str) -> List[SystemAnnouncement]:
    now = datetime.now()
    from sqlalchemy import select
    return (db.query(SystemAnnouncement)
        .filter(SystemAnnouncement.is_active == True)
        .filter((SystemAnnouncement.published_at == None) | (SystemAnnouncement.published_at <= now))
        .filter((SystemAnnouncement.expires_at == None) | (SystemAnnouncement.expires_at >= now))
        .filter(~SystemAnnouncement.id.in_(select(UserAnnouncement.announcement_id).where(UserAnnouncement.user_id == user_id)))
        .order_by(SystemAnnouncement.published_at.desc()).all())


def get_unread_count(db: Session, user_id: str) -> int:
    now = datetime.now()
    from sqlalchemy import select
    return db.query(func.count(SystemAnnouncement.id)).filter(SystemAnnouncement.is_active == True).filter(
        (SystemAnnouncement.published_at == None) | (SystemAnnouncement.published_at <= now)
    ).filter((SystemAnnouncement.expires_at == None) | (SystemAnnouncement.expires_at >= now)).filter(
        ~SystemAnnouncement.id.in_(select(UserAnnouncement.announcement_id).where(UserAnnouncement.user_id == user_id))
    ).scalar() or 0


def list_history(db: Session, user_id: str, limit: int = 20) -> List[dict]:
    rows = (db.query(UserAnnouncement, SystemAnnouncement)
        .join(SystemAnnouncement, UserAnnouncement.announcement_id == SystemAnnouncement.id)
        .filter(UserAnnouncement.user_id == user_id).order_by(UserAnnouncement.seen_at.desc()).limit(limit).all())
    return [{"announcement_id": sa.id, "title": sa.title, "summary": sa.summary,
             "content": sa.content, "seen_at": ua.seen_at, "is_active": sa.is_active}
            for ua, sa in rows]


def mark_as_seen(db: Session, user_id: str, announcement_id: int) -> bool:
    from sqlalchemy.exc import IntegrityError
    db.add(UserAnnouncement(user_id=user_id, announcement_id=announcement_id, seen_at=datetime.now()))
    try:
        db.commit(); return True
    except IntegrityError:
        db.rollback()
        return db.query(UserAnnouncement).filter(
            UserAnnouncement.user_id == user_id, UserAnnouncement.announcement_id == announcement_id
        ).first() is not None
