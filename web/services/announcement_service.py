"""Business logic for system announcements."""
from datetime import datetime
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy import func, select
from models.system_announcement import SystemAnnouncement
from models.user_announcement import UserAnnouncement


def _active_filter(query, now):
    return query.filter(
        SystemAnnouncement.is_active.is_(True),
        SystemAnnouncement.published_at.is_not(None),
        SystemAnnouncement.published_at <= now,
        (SystemAnnouncement.expires_at.is_(None) | (SystemAnnouncement.expires_at >= now)),
    )


def list_unread(db: Session, user_id: str):
    now = datetime.now()
    seen = select(UserAnnouncement.announcement_id).where(
        UserAnnouncement.user_id == user_id
    )
    return _active_filter(db.query(SystemAnnouncement), now).filter(
        ~SystemAnnouncement.id.in_(seen)
    ).order_by(SystemAnnouncement.published_at.desc()).all()


def get_unread_count(db: Session, user_id: str) -> int:
    now = datetime.now()
    seen = select(UserAnnouncement.announcement_id).where(
        UserAnnouncement.user_id == user_id
    )
    return (_active_filter(db.query(func.count(SystemAnnouncement.id)), now)
            .filter(~SystemAnnouncement.id.in_(seen)).scalar() or 0)


def list_history(db: Session, user_id: str):
    return (db.query(SystemAnnouncement, UserAnnouncement.seen_at)
            .join(UserAnnouncement, UserAnnouncement.announcement_id == SystemAnnouncement.id)
            .filter(UserAnnouncement.user_id == user_id)
            .order_by(UserAnnouncement.seen_at.desc()).all())


def mark_as_seen(db: Session, user_id: str, announcement_id: int) -> bool:
    announcement = db.query(SystemAnnouncement).filter(SystemAnnouncement.id == announcement_id).first()
    if not announcement:
        return False
    existing = db.query(UserAnnouncement).filter(
        UserAnnouncement.user_id == user_id,
        UserAnnouncement.announcement_id == announcement_id,
    ).first()
    if existing:
        return True
    db.add(UserAnnouncement(user_id=user_id, announcement_id=announcement_id))
    try:
        db.commit()
        return True
    except IntegrityError:
        db.rollback()
        return True
