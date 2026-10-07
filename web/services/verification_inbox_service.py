"""
صف یکپارچه تأیید: مدارک پرسنلی + بستگان + مدارک تحصیلی.

فقط خواندن/تجمیع؛ mutate از سرویس‌های دامنهٔ موجود انجام می‌شود.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Iterable, Optional, Sequence

from sqlalchemy import or_
from sqlalchemy.orm import Session, joinedload

from models.education import Education
from models.employee import Employee
from models.employee_document import EmployeeDocument
from models.employee_relative import EmployeeRelative

KIND_DOCUMENT = "document"
KIND_RELATIVE = "relative"
KIND_EDUCATION = "education"

ALL_KINDS = (KIND_DOCUMENT, KIND_RELATIVE, KIND_EDUCATION)

KIND_LABELS = {
    KIND_DOCUMENT: "مدرک پرسنلی",
    KIND_RELATIVE: "بستگان",
    KIND_EDUCATION: "مدرک تحصیلی",
}


@dataclass(frozen=True)
class VerificationItem:
    kind: str
    item_id: int
    user_id: str
    employee_name: str
    title: str
    subtitle: str
    status_label: str
    created_at: Optional[datetime]
    detail_url: str
    file_url: Optional[str]
    verify_url: str
    reject_url: str

    @property
    def kind_label(self) -> str:
        return KIND_LABELS.get(self.kind, self.kind)


def _employee_name(emp: Optional[Employee], user_id: str) -> str:
    if emp:
        return emp.full_name
    return user_id


def _search_filter(query, search: Optional[str]):
    if not search or not str(search).strip():
        return query
    term = f"%{str(search).strip()}%"
    return query.filter(
        or_(
            Employee.first_name.ilike(term),
            Employee.last_name.ilike(term),
            Employee.user_id.ilike(term),
        )
    )


def _document_items(db: Session, search: Optional[str]) -> list[VerificationItem]:
    q = (
        db.query(EmployeeDocument, Employee)
        .outerjoin(Employee, Employee.user_id == EmployeeDocument.user_id)
        .options(joinedload(EmployeeDocument.document_type))
        .filter(
            EmployeeDocument.deleted_at.is_(None),
            EmployeeDocument.status == "PENDING",
        )
    )
    q = _search_filter(q, search)
    rows = q.order_by(EmployeeDocument.uploaded_at.desc(), EmployeeDocument.id.desc()).all()
    items: list[VerificationItem] = []
    for doc, emp in rows:
        items.append(
            VerificationItem(
                kind=KIND_DOCUMENT,
                item_id=doc.id,
                user_id=doc.user_id,
                employee_name=_employee_name(emp, doc.user_id),
                title=doc.document_type_name or doc.title,
                subtitle=doc.title,
                status_label="در انتظار تأیید",
                created_at=doc.uploaded_at or doc.created_at,
                detail_url=f"/admin/profile/{doc.user_id}",
                file_url=f"/employee-documents/{doc.id}/file",
                verify_url=f"/admin/verifications/documents/{doc.id}/verify",
                reject_url=f"/admin/verifications/documents/{doc.id}/reject",
            )
        )
    return items


def _relative_items(db: Session, search: Optional[str]) -> list[VerificationItem]:
    q = (
        db.query(EmployeeRelative, Employee)
        .outerjoin(Employee, Employee.user_id == EmployeeRelative.user_id)
        .filter(
            EmployeeRelative.deleted_at.is_(None),
            EmployeeRelative.status == "PENDING",
        )
    )
    q = _search_filter(q, search)
    rows = q.order_by(EmployeeRelative.created_at.desc(), EmployeeRelative.id.desc()).all()
    items: list[VerificationItem] = []
    for rel, emp in rows:
        items.append(
            VerificationItem(
                kind=KIND_RELATIVE,
                item_id=rel.id,
                user_id=rel.user_id,
                employee_name=_employee_name(emp, rel.user_id),
                title=rel.relationship_type_name,
                subtitle=rel.full_name,
                status_label="در انتظار تأیید",
                created_at=rel.created_at,
                detail_url=f"/admin/profile/{rel.user_id}",
                file_url=None,
                verify_url=f"/admin/verifications/relatives/{rel.id}/verify",
                reject_url=f"/admin/verifications/relatives/{rel.id}/reject",
            )
        )
    return items


def _education_items(db: Session, search: Optional[str]) -> list[VerificationItem]:
    q = (
        db.query(Education, Employee)
        .outerjoin(Employee, Employee.user_id == Education.user_id)
        .filter(Education.verified.is_(False))
    )
    q = _search_filter(q, search)
    rows = q.order_by(Education.created_at.desc(), Education.id.desc()).all()
    items: list[VerificationItem] = []
    for edu, emp in rows:
        items.append(
            VerificationItem(
                kind=KIND_EDUCATION,
                item_id=edu.id,
                user_id=edu.user_id,
                employee_name=_employee_name(emp, edu.user_id),
                title=edu.degree_level_name,
                subtitle=edu.major,
                status_label="در انتظار تأیید",
                created_at=edu.created_at,
                detail_url=f"/admin/profile/{edu.user_id}",
                file_url=(
                    f"/education/{edu.id}/file" if edu.certificate_path else None
                ),
                verify_url=f"/admin/verifications/education/{edu.id}/verify",
                reject_url=f"/admin/verifications/education/{edu.id}/reject",
            )
        )
    return items


def normalize_kinds(kinds: Optional[Sequence[str]]) -> tuple[str, ...]:
    if not kinds:
        return ALL_KINDS
    allowed = []
    for k in kinds:
        key = (k or "").strip().lower()
        if key in ALL_KINDS and key not in allowed:
            allowed.append(key)
    return tuple(allowed) if allowed else ALL_KINDS


def list_pending_items(
    db: Session,
    *,
    kinds: Optional[Sequence[str]] = None,
    search: Optional[str] = None,
    limit: int = 200,
) -> list[VerificationItem]:
    """لیست آیتم‌های در انتظار برای kinds داده‌شده."""
    selected = normalize_kinds(kinds)
    items: list[VerificationItem] = []
    if KIND_DOCUMENT in selected:
        items.extend(_document_items(db, search))
    if KIND_RELATIVE in selected:
        items.extend(_relative_items(db, search))
    if KIND_EDUCATION in selected:
        items.extend(_education_items(db, search))

    items.sort(
        key=lambda it: (
            it.created_at is not None,
            it.created_at or datetime.min,
            it.item_id,
        ),
        reverse=True,
    )
    if limit and limit > 0:
        return items[:limit]
    return items


def count_pending_by_kind(
    db: Session,
    kinds: Optional[Iterable[str]] = None,
) -> dict[str, int]:
    selected = set(normalize_kinds(tuple(kinds) if kinds is not None else None))
    counts = {k: 0 for k in ALL_KINDS}
    if KIND_DOCUMENT in selected:
        counts[KIND_DOCUMENT] = (
            db.query(EmployeeDocument)
            .filter(
                EmployeeDocument.deleted_at.is_(None),
                EmployeeDocument.status == "PENDING",
            )
            .count()
        )
    if KIND_RELATIVE in selected:
        counts[KIND_RELATIVE] = (
            db.query(EmployeeRelative)
            .filter(
                EmployeeRelative.deleted_at.is_(None),
                EmployeeRelative.status == "PENDING",
            )
            .count()
        )
    if KIND_EDUCATION in selected:
        counts[KIND_EDUCATION] = (
            db.query(Education).filter(Education.verified.is_(False)).count()
        )
    return counts


def count_pending_verifications(
    db: Session,
    kinds: Optional[Iterable[str]] = None,
) -> int:
    return sum(count_pending_by_kind(db, kinds).values())
