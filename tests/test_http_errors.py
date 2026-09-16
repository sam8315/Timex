"""Tests for centralized HTTP error handling (403 HTML page vs JSON API).

رسیدگی به `web.error_handlers.http_exception_handler`:

- کاربر احراز‌هویتشدهٔ بدون مجوز + درخواست صفحه وب (Accept: text/html)
  → صفحهٔ اختصاصی 403.html با قالب پنل (بدون افشای جزئیات حساس)
- همان کاربر + درخواست API/JSON → پاسخ JSON 403 (تبدیل به HTML نمی‌شود)
- Accept پیش‌فرض (*/*) → رفتار قبلی JSON حفظ می‌شود
- کاربر دارای مجوز → صفحه بدون تغییر باز می‌شود (بدون Regression)
- سایر خطاهای HTTP (404، ریدایرکت 307 به /login) سالم می‌مانند
"""
from .conftest import login_as

from web.permissions import set_user_permission

HTML_ACCEPT = {"Accept": "text/html"}
JSON_ACCEPT = {"Accept": "application/json"}


def _revoke_reports(db, user_id):
    set_user_permission(db, user_id, "view_reports", False, created_by="SYS")
    db.commit()


# ---------------------------------------------------------------------------
# 1) درخواست صفحه وب (HTML) بدون مجوز → صفحه اختصاصی 403
# ---------------------------------------------------------------------------
def test_html_403_page_for_web_request(client, db, make_user):
    """admin که view_reports را ندارد، در مرورگر صفحهٔ 403 HTML می‌بیند."""
    creds = make_user(role="admin")
    _revoke_reports(db, creds["user_id"])
    login_as(client, creds["national_code"])

    resp = client.get("/reports", headers=HTML_ACCEPT)
    assert resp.status_code == 403
    body = resp.text
    # قالب پنل (RTL، base.html)
    assert "<html" in body and 'lang="fa"' in body and 'dir="rtl"' in body
    # محتوای اختصاصی
    assert "403" in body
    assert "دسترسی غیرمجاز" in body
    assert "بازگشت به داشبورد" in body
    assert "بازگشت به صفحه قبل" in body


def test_html_403_for_role_gate(client, db, make_user):
    """کاربر عادی که به ناحیهٔ مدیریت دسترسی ندارد نیز صفحهٔ 403 HTML می‌بیند."""
    creds = make_user(role="user")
    login_as(client, creds["national_code"])

    resp = client.get("/admin", headers=HTML_ACCEPT)
    assert resp.status_code == 403
    assert "دسترسی غیرمجاز" in resp.text


# ---------------------------------------------------------------------------
# 2) API/JSON بدون مجوز → پاسخ JSON، نه HTML
# ---------------------------------------------------------------------------
def test_json_403_for_api_request(client, db, make_user):
    """درخواست API بدون مجوز، پاسخ JSON 403 می‌گیرد (نه صفحهٔ HTML)."""
    creds = make_user(role="admin")
    _revoke_reports(db, creds["user_id"])
    login_as(client, creds["national_code"])

    resp = client.get("/reports", headers=JSON_ACCEPT)
    assert resp.status_code == 403
    assert resp.headers["content-type"].startswith("application/json")
    assert resp.json()["detail"] == "دسترسی غیرمجاز"
    assert "text/html" not in resp.headers["content-type"]


def test_default_accept_still_returns_json(client, db, make_user):
    """TestClient/curl معمولاً Accept=*/* ارسال می‌کنند → رفتار قبلی JSON."""
    creds = make_user(role="admin")
    _revoke_reports(db, creds["user_id"])
    login_as(client, creds["national_code"])

    resp = client.get("/reports")  # بدون هدر Accept صریح
    assert resp.status_code == 403
    assert resp.headers["content-type"].startswith("application/json")


# ---------------------------------------------------------------------------
# 3) کاربر دارای مجوز → صفحه بدون تغییر باز می‌شود
# ---------------------------------------------------------------------------
def test_user_with_permission_still_sees_page(client, db, make_user):
    """view_reports پیش‌فرض نقش admin = دارد → صفحهٔ گزارشات 200 است."""
    creds = make_user(role="admin")
    login_as(client, creds["national_code"])

    resp = client.get("/reports", headers=HTML_ACCEPT)
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# 4) سایر خطاهای HTTP حفظ می‌شوند
# ---------------------------------------------------------------------------
def test_404_still_returns_json(client, db, make_user):
    """۴۰۴ حتی با Accept=text/html همچنان JSON باقی می‌ماند (رفتار فعلی)."""
    creds = make_user(role="admin")
    login_as(client, creds["national_code"])

    resp = client.get("/no-such-page", headers=HTML_ACCEPT)
    assert resp.status_code == 404
    assert resp.headers["content-type"].startswith("application/json")
    assert "detail" in resp.json()


def test_unauthenticated_still_redirects_to_login(client):
    """ریدایرکت 307 با Location باید حفظ شود (Regression برای ورود)."""
    resp = client.get("/reports", follow_redirects=False)
    assert resp.status_code == 307
    assert resp.headers["location"] == "/login"


def test_csrf_failure_html_renders_403_page(client, db, make_user):
    """POST بدون CSRF برای مرورگر → صفحهٔ 403 (نه JSON خام)."""
    target = make_user(role="admin")
    super_user = make_user(role="super_admin")
    login_as(client, super_user["national_code"])

    resp = client.post(
        f"/admin/permissions/{target['user_id']}/toggle",
        data={"permission": "view_reports", "action": "revoke", "csrf_token": ""},
        headers=HTML_ACCEPT,
        follow_redirects=False,
    )
    assert resp.status_code == 403
    assert "دسترسی غیرمجاز" in resp.text


# ---------------------------------------------------------------------------
# 5) امنیت: صفحهٔ 403 جزئیات حساس را افشا نمی‌کند
# ---------------------------------------------------------------------------
def test_html_403_does_not_leak_role_gate_detail(client, db, make_user):
    """admin که به بخش سوپرادمین رفته، جزئیات gate («فقط مدیر ارشد») را نمی‌بیند."""
    creds = make_user(role="admin")  # require_super_admin را رد می‌کند
    login_as(client, creds["national_code"])

    resp = client.get("/admin/policies", headers=HTML_ACCEPT)
    assert resp.status_code == 403
    body = resp.text
    assert "دسترسی غیرمجاز" in body
    # پیام داخلی dependency نباید به کاربر نمایش داده شود
    assert "فقط مدیر ارشد" not in body


def test_html_403_does_not_leak_csrf_detail(client, db, make_user):
    """جزئیات «توکن امنیتی نامعتبر» نباید داخل صفحهٔ 403 دیده شود."""
    target = make_user(role="admin")
    super_user = make_user(role="super_admin")
    login_as(client, super_user["national_code"])

    resp = client.post(
        f"/admin/permissions/{target['user_id']}/toggle",
        data={"permission": "view_reports", "action": "revoke", "csrf_token": ""},
        headers=HTML_ACCEPT,
        follow_redirects=False,
    )
    assert resp.status_code == 403
    assert "توکن امنیتی نامعتبر" not in resp.text