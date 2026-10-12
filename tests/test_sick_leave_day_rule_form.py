"""رفتار استعلاجی روی خود قلم است و تب جداگانه وجود ندارد."""
from tests.conftest import login_as


def test_sick_behavior_lives_on_the_component_form(client, db, make_user):
    admin = make_user(role="super_admin")
    login_as(client, admin["national_code"])
    db.commit()
    page = client.get("/admin/policies/payroll")
    assert page.status_code == 200
    assert 'id="tab-sick"' not in page.text
    assert "day-rules" not in page.text
    assert 'name="sick_mode"' in page.text
    assert 'name="absence_mode"' in page.text
    assert 'name="day_basis"' in page.text
    assert "خروج از پرداخت کارفرما" in page.text
    assert "مشمول بیمه" in page.text
    assert "معاف از بیمه سهم کارمند" in page.text
    assert 'action="/admin/policies/payroll/insurance-exemptions"' in page.text
    assert "jalali-date" in page.text
