from types import SimpleNamespace

from core.payroll.money import D
from core.payroll.payslip_present import line_detail, money_text


def _item(**kwargs):
    base = dict(component_code="", unit_amount=None, quantity=None, calc_note="", kind="earning", amount=D(0))
    base.update(kwargs)
    return SimpleNamespace(**base)


def test_daily_wage_sentence_and_persian_money():
    text = line_detail(_item(
        component_code="DAILY_WAGE",
        unit_amount=D("1000000"),
        quantity=D("30"),
        amount=D("30000000"),
    ))
    assert text == "هر روز ۱٬۰۰۰٬۰۰۰ ریال، به مدت ۳۰ روز"
    assert money_text(D("30000000.0000")) == "۳۰٬۰۰۰٬۰۰۰"


def test_decimals_stop_at_two_digits():
    assert money_text(D("7.3333")) == "۷٫۳۳"
    assert money_text(D("1.40")) == "۱٫۴"


def test_child_allowance_shows_count_and_per_child():
    text = line_detail(_item(
        component_code="CHILD_ALLOWANCE",
        unit_amount=D("16625550"),
        quantity=D("2"),
        amount=D("33251100"),
    ))
    assert text == "۲ فرزند، هر فرزند ۱۶٬۶۲۵٬۵۵۰ ریال"


def test_deduction_shows_percent_and_base():
    text = line_detail(_item(
        component_code="INSURANCE_EMPLOYEE",
        kind="deduction",
        unit_amount=D("7"),
        quantity=D("10000000"),
        amount=D("700000"),
    ))
    assert text == "۷ درصد از مبنای ۱۰٬۰۰۰٬۰۰۰ ریال"
