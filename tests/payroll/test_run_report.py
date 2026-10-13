"""گزارش لیست: فیلتر، ستون، جمع دپارتمان و جمع کل."""
from pathlib import Path

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


ROOT = Path(__file__).resolve().parents[2]


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
    shown = build_run_report(
        _people(),
        column_codes=["DAILY_WAGE"],
        extra_columns=["user_id", "membership", GROSS],
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
    assert [field["code"] for field in hidden["fields"]] == ["name"]
    assert [column["code"] for column in hidden["columns"]] == ["DAILY_WAGE"]


def test_row_column_default_off_and_code_default_on():
    default = build_run_report(_people(), department_totals=False)
    assert [field["code"] for field in default["fields"]][:2] == ["user_id", "name"]
    assert "row" not in [field["code"] for field in default["fields"]]

    with_row = build_run_report(_people(), extra_columns=["row", "user_id"], department_totals=False)
    assert [field["code"] for field in with_row["fields"]] == ["row", "user_id", "name"]
    assert with_row["fields"][0]["name"] == "ردیف"

    no_code = build_run_report(_people(), extra_columns=["row"], department_totals=False)
    assert [field["code"] for field in no_code["fields"]] == ["row", "name"]


def test_row_numbers_are_continuous_for_filtered_people_and_totals_have_none():
    report = build_run_report(_people(), user_ids=["1", "3"], extra_columns=["row"])
    numbers = [row["row"] for section in report["sections"] for row in section["rows"]]
    assert numbers == [1, 2]
    for section in report["sections"]:
        assert "row" not in section["subtotal"]
    assert "row" not in report["grand_total"]

    flat = build_run_report(_people(), extra_columns=["row"], department_totals=False)
    assert [row["row"] for row in flat["sections"][0]["rows"]] == [1, 2, 3]


def test_titles_work_days_and_monthly_wage():
    from web.services.payroll.run_report import WORK_DAYS, report_choices

    report = build_run_report(_people(), column_codes=["DAILY_WAGE"], extra_columns=[WORK_DAYS])
    names = {column["code"]: column["name"] for column in report["columns"]}
    assert names[WORK_DAYS] == "کارکرد"
    assert names["DAILY_WAGE"] == "حقوق ماهیانه"
    choices = {item["code"]: item["name"] for item in report_choices(_people())["columns"]}
    assert choices["DAILY_WAGE"] == "حقوق ماهیانه"
    # فقط عنوان نمایشی عوض می‌شود؛ مبلغ و کد دست‌نخورده‌اند.
    assert report["sections"][0]["rows"][0]["amounts"]["DAILY_WAGE"] == D(40)
    assert _people()[0].lines[0].component_name == "حقوق"


def test_form_templates_use_new_labels_and_options():
    detail = (ROOT / "web/templates/admin/payroll_run_detail.html").read_text(encoding="utf-8")
    assert 'value="row" id="rxRow"' in detail
    assert 'id="rxRow" checked' not in detail
    assert 'value="user_id" id="rxUserId" checked' in detail
    assert "روزهای کارکرد" not in detail
    assert 'for="rxWorkDays">کارکرد<' in detail
    assert "حقوق ماهیانه" in detail


def test_form_parsing_keeps_row_and_code_options():
    from web.services.payroll.run_report import parse_report_form

    class Form(dict):
        def getlist(self, name):
            value = self.get(name, [])
            return value if isinstance(value, list) else [value]

    parsed = parse_report_form(Form(extras_from_page="1", extra_columns=["row", "user_id"]))
    assert parsed["extra_columns"] == ["row", "user_id"]
    assert parse_report_form(Form())["extra_columns"] is None


def test_report_template_black_white_and_no_number_breaking():
    html = (ROOT / "web/templates/admin/payroll_run_report.html").read_text(encoding="utf-8")
    assert "overflow-wrap: anywhere" not in html
    assert "word-break: break-word" not in html
    assert "0.35mm" in html
    for selector in ("thead > tr > th", "tr.report-subtotal > td", "tr.report-grand > td"):
        assert selector in html
    assert "td.num" in html and "nowrap" in html
    assert "size: A4 landscape" in html
    assert "table-layout: fixed" in html


def test_html_layout_fits_a4_width_for_many_columns():
    lines = tuple(ReportLine(f"C{i}", f"قلم {i}", "earning", i, D(123456789.5)) for i in range(14))
    people = [_person("123456", "نام بسیار طولانی کارمند نمونه", 123456789.5, lines=lines)]
    report = build_run_report(
        people,
        extra_columns=["row", "user_id", "membership", "department", "position", "__WORK_DAYS__", GROSS, NET],
    )
    layout = report["layout"]
    assert len(layout["widths_pct"]) == len(report["fields"]) + len(report["columns"])
    assert abs(sum(layout["widths_pct"]) - 100) < 0.05
    assert 4 <= layout["font_pt"] <= 9
    few = build_run_report(_people(), column_codes=["DAILY_WAGE"], extra_columns=["row", "user_id"])
    assert few["layout"]["font_pt"] >= layout["font_pt"]


def test_pdf_column_widths_fit_one_landscape_page_and_numbers_stay_whole():
    from core.payroll.pdf_run_report import (
        RunReportPDF,
        _make_measure,
        _wrap,
        plan_layout,
        report_fields,
        report_specs,
    )

    pdf = RunReportPDF(monochrome=True, page_numbers=False)
    usable = pdf.w - pdf.l_margin - pdf.r_margin
    assert pdf.w > pdf.h
    measure = _make_measure(pdf)
    lines = tuple(ReportLine(f"C{i}", f"قلم {i}", "earning", i, D(1234567890.5)) for i in range(16))
    people = [_person("12345678", "نام کارمند بسیار طولانی تست", 1234567890.5, lines=lines)]
    for count in (0, 3, 12, 16):
        report = build_run_report(
            people,
            column_codes=[f"C{i}" for i in range(count)],
            extra_columns=["row", "user_id", GROSS, NET],
        )
        fields = report_fields(report)
        specs = report_specs(report, fields, report["columns"])
        plan = plan_layout(specs, usable, measure)
        assert abs(sum(plan["widths"]) - usable) < 0.05
        assert all(width > 0 for width in plan["widths"])
        pdf.set_font(pdf.font_family_name, "", plan["font_pt"])
        for spec, width in zip(specs, plan["widths"]):
            if spec["wrap"]:
                continue
            for value in spec["values"]:
                assert _wrap(pdf, value, width) == [value]
                assert pdf.get_string_width(pdf._rtl(value)) <= width - 2 * pdf.c_margin + 0.01
    full = build_run_report(people, extra_columns=["row", "user_id", GROSS])
    assert build_run_report_pdf(full, title="گزارش", period_label="1405/01", monochrome=True).startswith(b"%PDF")
    color = build_run_report(_people())
    assert build_run_report_pdf(color, title="گزارش", period_label="1405/01", monochrome=False).startswith(b"%PDF")


def test_pdf_many_rows_paginate_vertically():
    people = [_person(str(1000 + i), f"کارمند {i}", 1000 + i) for i in range(120)]
    report = build_run_report(people, extra_columns=["row", "user_id"], department_totals=False)
    data = build_run_report_pdf(report, title="گزارش", period_label="1405/01", monochrome=True)
    assert data.startswith(b"%PDF")
    assert data.count(b"/Type /Page\n") + data.count(b"/Type /Page ") + data.count(b"/Type /Page/") >= 2
