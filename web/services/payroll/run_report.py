"""گزارش لیست حقوق از فیش‌های ذخیره‌شده. محاسبهٔ جدید انجام نمی‌شود."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Optional, Sequence

from sqlalchemy.orm import Session, joinedload

from core.payroll.money import D
from core.payroll.payslip_present import payslip_sort_key

NO_DEPARTMENT = "بدون دپارتمان"
GROSS = "__GROSS__"
DEDUCTIONS = "__DEDUCTIONS__"
NET = "__NET__"
MEMBERSHIP = "membership"
DEPARTMENT = "department"
POSITION = "position"
WORK_DAYS = "__WORK_DAYS__"

_TEXT_EXTRAS = (
    (MEMBERSHIP, "عضویت"),
    (DEPARTMENT, "دپارتمان"),
    (POSITION, "سمت"),
)
_TOTALS = (
    (GROSS, "ناخالص", 10000),
    (DEDUCTIONS, "کسورات", 10001),
    (NET, "خالص", 10002),
)


@dataclass(frozen=True)
class ReportLine:
    component_code: str
    component_name: str
    kind: str
    sort_order: int
    amount: Decimal


@dataclass(frozen=True)
class ReportPerson:
    user_id: str
    name: str
    membership_code: str
    membership_name: str
    department_id: Optional[int]
    department_name: str
    department_sort: int
    position_id: Optional[int]
    position_name: str
    gross: Decimal
    deductions: Decimal
    net: Decimal
    lines: tuple[ReportLine, ...]
    covered_days: int = 0


def catalog_columns(people: Sequence[ReportPerson]) -> list[ReportLine]:
    """قلم‌های موجود در نتایج، سپس ناخالص و کسورات و خالص."""
    found: dict[str, ReportLine] = {}
    for person in people:
        for line in person.lines:
            found.setdefault(line.component_code, line)
    columns = sorted(found.values(), key=payslip_sort_key)
    columns.extend(
        ReportLine(code, name, "total", order, D(0))
        for code, name, order in _TOTALS
    )
    return columns


def person_amount(person: ReportPerson, code: str) -> Decimal:
    if code == GROSS:
        return D(person.gross)
    if code == DEDUCTIONS:
        return D(person.deductions)
    if code == NET:
        return D(person.net)
    if code == WORK_DAYS:
        return D(person.covered_days)
    total = D(0)
    for line in person.lines:
        if line.component_code == code:
            total += D(line.amount)
    return total


def _as_set(values: Optional[Sequence], *, empty_means_all: bool):
    if values is None:
        return None
    cleaned = [item for item in values if item is not None and item != ""]
    if not cleaned and empty_means_all:
        return None
    return set(cleaned)


def _kept(
    people: Sequence[ReportPerson],
    *,
    membership_codes: Optional[Sequence[str]],
    department_ids: Optional[Sequence[int]],
    position_ids: Optional[Sequence[int]],
    user_ids: Optional[Sequence[str]],
) -> list[ReportPerson]:
    memberships = _as_set(membership_codes, empty_means_all=True)
    departments = _as_set(department_ids, empty_means_all=True)
    positions = _as_set(position_ids, empty_means_all=True)
    chosen_people = _as_set(user_ids, empty_means_all=True)
    rows = []
    for person in people:
        if memberships is not None and person.membership_code not in memberships:
            continue
        if departments is not None and person.department_id not in departments:
            continue
        if positions is not None and person.position_id not in positions:
            continue
        if chosen_people is not None and person.user_id not in chosen_people:
            continue
        rows.append(person)
    return rows


def _amounts(person: ReportPerson, columns: Sequence[ReportLine]) -> dict[str, Decimal]:
    return {column.component_code: person_amount(person, column.component_code) for column in columns}


def _sum_amounts(rows: Sequence[dict], columns: Sequence[ReportLine]) -> dict[str, Decimal]:
    totals = {column.component_code: D(0) for column in columns}
    for row in rows:
        for code in totals:
            totals[code] += D(row["amounts"].get(code, 0))
    return totals


def _person_row(person: ReportPerson, columns: Sequence[ReportLine]) -> dict:
    return {
        "user_id": person.user_id,
        "name": person.name,
        "membership": person.membership_name or person.membership_code or "—",
        "department": person.department_name or "—",
        "position": person.position_name or "—",
        "amounts": _amounts(person, columns),
    }


def _department_label(person: ReportPerson) -> str:
    return person.department_name or NO_DEPARTMENT


def build_run_report(
    people: Sequence[ReportPerson],
    *,
    membership_codes: Optional[Sequence[str]] = None,
    department_ids: Optional[Sequence[int]] = None,
    position_ids: Optional[Sequence[int]] = None,
    user_ids: Optional[Sequence[str]] = None,
    column_codes: Optional[Sequence[str]] = None,
    extra_columns: Optional[Sequence[str]] = None,
    department_totals: bool = True,
) -> dict:
    """فیلتر نفرها و ساخت ردیف‌ها.

    column_codes تهی یعنی هیچ قلم صفحه‌ای نیست؛ None یعنی همهٔ قلم‌ها.
    extra_columns تهی یعنی ستون‌های اضافی پنهان‌اند؛ None یعنی همان انتخاب قلم‌ها، و اگر قلمی نباشد همه روشن‌اند.
    """
    chosen = _kept(
        people,
        membership_codes=membership_codes,
        department_ids=department_ids,
        position_ids=position_ids,
        user_ids=user_ids,
    )
    available = [column for column in catalog_columns(people) if column.kind != "total"]
    selected_codes = _as_set(column_codes, empty_means_all=False)
    if selected_codes is None and column_codes is None:
        components = available
    else:
        components = [column for column in available if column.component_code in (selected_codes or set())]
    shown_extra = None if extra_columns is None else set(extra_columns)

    def shown(code: str) -> bool:
        if shown_extra is None:
            return selected_codes is None or code in selected_codes
        return code in shown_extra

    fields = [{"code": "user_id", "name": "کد"}, {"code": "name", "name": "نام"}]
    fields.extend(
        {"code": code, "name": label}
        for code, label in _TEXT_EXTRAS
        if shown_extra is None or code in shown_extra
    )
    columns: list[ReportLine] = []
    if shown(WORK_DAYS):
        columns.append(ReportLine(WORK_DAYS, "روزهای کارکرد", "days", 0, D(0)))
    columns.extend(components)
    columns.extend(
        ReportLine(code, name, "total", order, D(0))
        for code, name, order in _TOTALS
        if shown(code)
    )
    column_view = [
        {"code": column.component_code, "name": column.component_name}
        for column in columns
    ]
    if not chosen:
        return {"fields": fields, "columns": column_view, "sections": [], "grand_total": None}
    sections = []
    flat_rows = []
    if department_totals:
        ordered = sorted(
            chosen,
            key=lambda person: (
                1 if not person.department_name else 0,
                person.department_sort,
                person.department_name,
                person.name,
                person.user_id,
            ),
        )
        current_label = None
        bucket: list[dict] = []
        for person in ordered:
            label = _department_label(person)
            if current_label is None:
                current_label = label
            elif label != current_label:
                sections.append(_section(current_label, bucket, columns, with_subtotal=True))
                flat_rows.extend(bucket)
                bucket = []
                current_label = label
            bucket.append(_person_row(person, columns))
        if current_label is not None:
            sections.append(_section(current_label, bucket, columns, with_subtotal=True))
            flat_rows.extend(bucket)
        grand = {
            "label": "جمع کل",
            "amounts": _sum_amounts(flat_rows, columns),
        } if flat_rows else None
    else:
        ordered = sorted(chosen, key=lambda person: (person.name, person.user_id))
        rows = [_person_row(person, columns) for person in ordered]
        sections.append({"title": None, "rows": rows, "subtotal": None})
        grand = None
    return {
        "fields": fields,
        "columns": column_view,
        "sections": sections,
        "grand_total": grand,
    }


def _section(title: str, rows: list[dict], columns: Sequence[ReportLine], *, with_subtotal: bool) -> dict:
    return {
        "title": title,
        "rows": rows,
        "subtotal": {
            "label": f"جمع {title}",
            "amounts": _sum_amounts(rows, columns),
        } if with_subtotal else None,
    }


def report_choices(people: Sequence[ReportPerson]) -> dict:
    memberships: dict[str, str] = {}
    departments: dict[int, tuple[str, int]] = {}
    positions: dict[int, tuple[str, int]] = {}
    for person in people:
        if person.membership_code:
            memberships.setdefault(person.membership_code, person.membership_name or person.membership_code)
        if person.department_id is not None and person.department_name:
            departments.setdefault(person.department_id, (person.department_name, person.department_sort))
        if person.position_id is not None and person.position_name:
            positions.setdefault(person.position_id, (person.position_name, 0))
    return {
        "memberships": [
            {"code": code, "name": memberships[code]}
            for code in sorted(memberships, key=lambda code: (memberships[code], code))
        ],
        "departments": [
            {"id": dep_id, "name": departments[dep_id][0]}
            for dep_id in sorted(departments, key=lambda dep_id: (departments[dep_id][1], departments[dep_id][0]))
        ],
        "positions": [
            {"id": pos_id, "name": positions[pos_id][0]}
            for pos_id in sorted(positions, key=lambda pos_id: positions[pos_id][0])
        ],
        "columns": [
            {"code": column.component_code, "name": column.component_name}
            for column in catalog_columns(people)
        ],
        "people": [
            {"user_id": person.user_id, "name": person.name}
            for person in sorted(people, key=lambda person: (person.name, person.user_id))
        ],
    }


def load_report_people(db: Session, run) -> list[ReportPerson]:
    """فقط کسانی که برای این لیست فیش دارند."""
    from models.employee import Employee
    from models.membership_type import MembershipType

    results = list(run.results or [])
    if not results:
        return []
    user_ids = [row.user_id for row in results]
    employees = {
        row.user_id: row
        for row in db.query(Employee)
        .options(joinedload(Employee.department_rel), joinedload(Employee.position_rel))
        .filter(Employee.user_id.in_(user_ids))
        .all()
    }
    names = {
        row.code: row.name
        for row in db.query(MembershipType).all()
    }
    people = []
    for result in results:
        emp = employees.get(result.user_id)
        department = emp.department_rel if emp is not None else None
        position = emp.position_rel if emp is not None else None
        lines = tuple(
            ReportLine(
                component_code=item.component_code,
                component_name=item.component_name,
                kind=item.kind,
                sort_order=int(item.sort_order or 100),
                amount=D(item.amount),
            )
            for item in (result.items or [])
        )
        code = result.membership_type_code or ""
        people.append(
            ReportPerson(
                user_id=result.user_id,
                name=(emp.full_name if emp is not None and emp.full_name else result.employee_name) or result.user_id,
                membership_code=code,
                membership_name=names.get(code, code),
                department_id=department.id if department is not None else None,
                department_name=department.name if department is not None else "",
                department_sort=int(department.sort_order or 0) if department is not None else 0,
                position_id=position.id if position is not None else None,
                position_name=position.name if position is not None else "",
                gross=D(result.gross_earnings),
                deductions=D(result.total_deductions),
                net=D(result.net_pay),
                covered_days=int(result.covered_days or 0),
                lines=lines,
            )
        )
    return people


def parse_report_form(form) -> dict:
    def texts(name: str) -> list[str]:
        return [str(item).strip() for item in form.getlist(name) if str(item).strip()]

    def numbers(name: str) -> list[int]:
        parsed = []
        for item in form.getlist(name):
            try:
                parsed.append(int(item))
            except (TypeError, ValueError):
                continue
        return parsed

    column_codes = texts("column_codes") if form.get("columns_from_page") == "1" else None
    extra_columns = texts("extra_columns") if form.get("extras_from_page") == "1" else None
    return {
        "membership_codes": texts("membership_codes"),
        "department_ids": numbers("department_ids"),
        "position_ids": numbers("position_ids"),
        "user_ids": texts("user_ids"),
        "column_codes": column_codes,
        "extra_columns": extra_columns,
        "department_totals": form.get("department_totals") == "1",
        "monochrome": form.get("monochrome") == "1",
    }
