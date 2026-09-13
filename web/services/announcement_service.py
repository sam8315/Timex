"""
سرویس اعلان‌ها (Announcements)
- لیست پیام‌های فعال برای کاربر
- وضعیت دیده/ندیده با ذخیره سمت سرور
- فیلتر غیر فعال، آینده، منقضی
- idempotent / race-resistant mark_as_seen
"""
from datetime import datetime
from typing import List, Optional
from sqlalchemy.orm import Session
from sqlalchemy import and_, func

from models.system_announcement import SystemAnnouncement
from models.user_announcement import UserAnnouncement


def _is_visible(ann: SystemAnnouncement) -> bool:
    now = datetime.now(ann.published_at.tzinfo if ann.published_at else None)
    if not ann.is_active:
        return False
    if ann.published_at and ann.published_at > now:
        return False
    if ann.expires_at and ann.expires_at < now:
        return False
    return True


def list_unread(db: Session, user_id: str) -> List[SystemAnnouncement]:
    # Only announcements that are active, published, not expired
    # and for which no UserAnnouncement row exists
    now = datetime.now()
    from sqlalchemy import select
    rows = (
        db.query(SystemAnnouncement)
        .filter(SystemAnnouncement.is_active == True)
        .filter(
            (SystemAnnouncement.published_at == None)
            | (SystemAnnouncement.published_at <= now)
        )
        .filter(
            (SystemAnnouncement.expires_at == None)
            | (SystemAnnouncement.expires_at >= now)
        )
        .filter(~SystemAnnouncement.id.in_(select(UserAnnouncement.announcement_id).where(UserAnnouncement.user_id == user_id)))
        .order_by(SystemAnnouncement.published_at.desc())
        .all()
    )
    return rows


def get_unread_count(db: Session, user_id: str) -> int:
    now = datetime.now()
    from sqlalchemy import select
    count = (
        db.query(func.count(SystemAnnouncement.id))
        .filter(SystemAnnouncement.is_active == True)
        .filter(
            (SystemAnnouncement.published_at == None)
            | (SystemAnnouncement.published_at <= now)
        )
        .filter(
            (SystemAnnouncement.expires_at == None)
            | (SystemAnnouncement.expires_at >= now)
        )
        .filter(~SystemAnnouncement.id.in_(select(UserAnnouncement.announcement_id).where(UserAnnouncement.user_id == user_id)))
        .scalar()
    )
    return count or 0


def list_history(db: Session, user_id: str, limit: int = 20) -> List[dict]:
    # Announcements the user has marked seen
    rows = (
        db.query(UserAnnouncement, SystemAnnouncement)
        .join(
            SystemAnnouncement,
            UserAnnouncement.announcement_id == SystemAnnouncement.id
        )
        .filter(UserAnnouncement.user_id == user_id)
        .order_by(UserAnnouncement.seen_at.desc())
        .limit(limit)
        .all()
    )
    result = []
    for ua, sa in rows:
        result.append({
            "announcement_id": sa.id,
            "title": sa.title,
            "summary": sa.summary,
            "content": sa.content,
            "seen_at": ua.seen_at,
            "is_active": sa.is_active,
        })
    return result


def mark_as_seen(db: Session, user_id: str, announcement_id: int) -> bool:
    """Idempotent, race-resistant."""
    # Try insert; if unique violation, ignore (already seen)
    from sqlalchemy.exc import IntegrityError
    new_row = UserAnnouncement(
        user_id=user_id,
        announcement_id=announcement_id,
        seen_at=datetime.now(),
    )
    db.add(new_row)
    try:
        db.commit()
        return True
    except IntegrityError:
        db.rollback()
        # Verify existing row is present; do not update seen_at to preserve first-seen
        existing = (
            db.query(UserAnnouncement)
            .filter(
                UserAnnouncement.user_id == user_id,
                UserAnnouncement.announcement_id == announcement_id,
            )
            .first()
        )
        return existing is not None
