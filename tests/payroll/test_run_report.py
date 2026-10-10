"""گزارش لیست: فیلتر، ستون، جمع دپارتمان و جمع کل."""
from core.payroll.money import D
from core.payroll.pdf_run_report import build_run_report_pdf
from web.services.payroll.run_report import (
    GROSS,
    NET,
    NO_DEPARTMENT,
    ReportLine,
    ReportPerson,
    build_run_report,
)


def _line(amount):
    return ReportLine("DAILY_WAGE", "حقوق", "earning", 10, D(amount))


def _person(user_id, name, amount, **kwargs):
    base = dict(
        user_id=user_id,
        name=name,
        membership_code="4",
        membership_name="قراردادی",
        department_id=1,
        department_name="مالی",
        department_sort=2,
        position_id=8,
        position_name="کارشناس",
        gross=D(amount),
        deductions=D(0),
        net=D(amount),
        lines=(_line(amount),),
    )
    base.update(kwargs)
    return ReportPerson(**base)


def _people():
    return [
        _person("1", "الف", 100),
        _person("2", "ب", 40, department_id=2, department_name="داروخانه", department_sort=1, position_id=3, position_name="مسئول"),
        _person("3", "ج", 25, membership_code="1", membership_name="رسمی", department_id=None, department_name="", position_id=None, position_name=""),
    ]


def test_empty_filters_keep_everyone_and_selected_columns():
    report = build_run_report(_people(), column_codes=None, department_totals=False)
    rows = report["sections"][0]["rows"]
    assert [row["user_id"] for row in rows] == ["1", "2", "3"]
    assert [column["code"] for column in report["columns"]][:2] == ["__WORK_DAYS__", "DAILY_WAGE"]
    assert report["columns"][-3]["code"] == GROSS
    assert report["grand_total"] is None
    assert report["sections"][0]["subtotal"] is None


def test_filters_and_people_intersect():
    by_membership = build_run_report(_people(), membership_codes=["1"], department_totals=False)
    assert [row["user_id"] for row in by_membership["sections"][0]["rows"]] == ["3"]

    by_department = build_run_report(_people(), department_ids=[2], department_totals=False)
    assert [row["user_id"] for row in by_department["sections"][0]["rows"]] == ["2"]

    by_position = build_run_report(_people(), position_ids=[8], department_totals=False)
    assert [row["user_id"] for row in by_position["sections"][0]["rows"]] == ["1"]

    both = build_run_report(
        _people(),
        membership_codes=["4"],
        user_ids=["1", "3"],
        department_totals=False,
    )
    assert [row["user_id"] for row in both["sections"][0]["rows"]] == ["1"]


def test_selected_columns_only():
    report = build_run_report(_people(), column_codes=[NET], department_totals=False)
    assert [column["code"] for column in report["columns"]] == [NET]
    assert report["sections"][0]["rows"][0]["amounts"][NET] == D(100)


def test_department_subtotals_grand_total_and_missing_department():
    report = build_run_report(_people(), column_codes=["DAILY_WAGE"])
    titles = [section["title"] for section in report["sections"]]
    assert titles == ["داروخانه", "مالی", NO_DEPARTMENT]
    pharmacy, finance, none = report["sections"]
    assert pharmacy["subtotal"]["label"] == "جمع داروخانه"
    assert pharmacy["subtotal"]["amounts"]["DAILY_WAGE"] == D(40)
    assert finance["subtotal"]["amounts"]["DAILY_WAGE"] == D(100)
    assert none["subtotal"]["label"] == f"جمع {NO_DEPARTMENT}"
    assert none["subtotal"]["amounts"]["DAILY_WAGE"] == D(25)
    assert report["grand_total"]["label"] == "جمع کل"
    assert report["grand_total"]["amounts"]["DAILY_WAGE"] == D(165)


def test_work_days_come_from_stored_coverage_and_sum():
    people = [
        _person("1", "الف", 100, covered_days=20),
        _person("2", "ب", 40, covered_days=10, department_id=2, department_name="داروخانه", department_sort=1),
    ]
    report = build_run_report(people, column_codes=[], extra_columns=["__WORK_DAYS__"])
    assert [column["code"] for column in report["columns"]] == ["__WORK_DAYS__"]
    pharmacy, finance = report["sections"]
    assert pharmacy["rows"][0]["amounts"]["__WORK_DAYS__"] == D(10)
    assert pharmacy["subtotal"]["amounts"]["__WORK_DAYS__"] == D(10)
    assert finance["subtotal"]["amounts"]["__WORK_DAYS__"] == D(20)
    assert report["grand_total"]["amounts"]["__WORK_DAYS__"] == D(30)


def test_extra_columns_can_be_hidden():
    from web.services.payroll.run_report import GROSS

    shown = build_run_report(
        _people(),
        column_codes=["DAILY_WAGE"],
        extra_columns=["membership", GROSS],
        department_totals=False,
    )
    assert [field["code"] for field in shown["fields"]] == ["user_id", "name", "membership"]
    assert [column["code"] for column in shown["columns"]] == ["DAILY_WAGE", GROSS]

    hidden = build_run_report(
        _people(),
        column_codes=["DAILY_WAGE"],
        extra_columns=[],
        department_totals=False,
    )
    assert [field["code"] for field in hidden["fields"]] == ["user_id", "name"]
    assert [column["code"] for column in hidden["columns"]] == ["DAILY_WAGE"]


def test_pdf_column_widths_fit_one_landscape_page():
    from core.payroll.pdf_run_report import RunReportPDF, _widths

    pdf = RunReportPDF(monochrome=True, page_numbers=False)
    usable = pdf.w - pdf.l_margin - pdf.r_margin
    assert pdf.w > pdf.h
    for count in (0, 3, 12, 20):
        fixed, money = _widths(pdf, count)
        assert len(fixed) == 5
        assert len(money) == count
        assert abs(sum(fixed) + sum(money) - usable) < 0.05
        assert all(width > 0 for width in fixed + money)
    report = build_run_report(_people(), column_codes=["DAILY_WAGE"])
    data = build_run_report_pdf(report, title="گزارش", period_label="1405/01", monochrome=True)
    assert data.startswith(b"%PDF")
