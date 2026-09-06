"""Tests for the role-centric access view (Phase 6).

`?tab=roles&role=<code>` — «این نقش به‌صورت پیش‌فرض کدام دسترسی‌ها را دارد؟»

اصول اینجا:
- نما کاملاً فقط‌خواندنی است: هیچ اعطا/سلب/بازنشانی/تغییر نقشی انجام نمی‌شود.
- نقش‌ها از منبع واقعی پروژه (WebConfig.ROLE_*) خوانده می‌شوند — نه از سمت کلاینت.
- پیش‌فرض هر نقش از `ALL_PERMISSIONS[code].get(role, False)` می‌آید
  (دقیقاً قدم اولِ `get_effective_permissions`) — Backend = منبع حقیقت؛ هیچ عددی حدس نمی‌شود.
- آمار (کل/فعال/غیرفعال) از ALL_PERMISSIONS محاسبه می‌شود، نه از ردیف‌های صفحه.
- درب: فقط سوپرادمین (`require_super_admin`)؛ CSRF/دسترسی بدون تغییر.
"""
import re

from .conftest import login_as

from web.permissions import ALL_PERMISSIONS

HTML_ACCEPT = {"Accept": "text/html"}


# ---------------------------------------------------------------------------
# ابزارهای کمکی
# ---------------------------------------------------------------------------
def _page(client, url):
    resp = client.get(url, headers=HTML_ACCEPT)
    assert resp.status_code == 200, resp.status_code
    return resp.text


def _tile(body, label):
    """عدد داخل کاشی آمار که برچسبِ مشخص دارد."""
    m = re.search(
        r'<div class="fs-4 fw-bold lh-1">(\d+)</div>\s*'
        r'<small class="text-muted">' + re.escape(label) + r"</small>",
        body,
        re.S,
    )
    assert m, f"کاشی آمار با برچسب «{label}» یافت نشد"
    return int(m.group(1))


def _n(body, marker):
    """تعداد رخدادِ ترکیب کامل کلاس (مثل `state-badge badge-allowed`)."""
    return body.count(marker)


def _role_flags(role):
    """تعداد فعال/غیرفعال برای یک نقش، مستقیماً از ALL_PERMISSIONS (منبع حقیقت)."""
    granted = sum(1 for info in ALL_PERMISSIONS.values() if info.get(role, False))
    return granted, len(ALL_PERMISSIONS) - granted


# ---------------------------------------------------------------------------
# نمایش پایه: تب نقش‌ها بدون انتخاب
# ---------------------------------------------------------------------------
def test_roles_tab_renders_selector_only(client, db, make_user):
    super_u = make_user(role="super_admin")
    login_as(client, super_u["national_code"])

    body = _page(client, "/admin/permissions?tab=roles")
    assert "— انتخاب نقش —" in body
    # گزینه‌ها از منبع واقعی می‌آیند (WebConfig.ROLE_*)
    for code in ("user", "admin", "super_admin"):
        assert f'value="{code}"' in body
    # بدون نقش انتخاب‌شده → هیچ جدول/کاشی‌ای رندر نمی‌شود
    assert "کل دسترسی‌ها" not in body
    assert "وضعیت</th>" not in body
    assert "این نما فقط‌خواندنی است" in body


def test_roles_tab_active_tab_and_tablink(client, db, make_user):
    super_u = make_user(role="super_admin")
    login_as(client, super_u["national_code"])

    body = _page(client, "/admin/permissions?tab=roles")
    assert 'id="tab-roles"' in body
    assert 'class="nav-link active"' in body
    assert 'aria-selected="true"' in body
    assert 'href="/admin/permissions?tab=roles"' in body


# ---------------------------------------------------------------------------
# نقش معتبر: آمار + جدول از ALL_PERMISSIONS
# ---------------------------------------------------------------------------
def test_valid_role_admin_matches_all_permissions(client, db, make_user):
    super_u = make_user(role="super_admin")
    login_as(client, super_u["national_code"])

    granted, not_granted = _role_flags("admin")
    body = _page(client, "/admin/permissions?tab=roles&role=admin")

    assert "مدیر" in body            # role_label
    assert 'value="admin" selected' in body   # انتخاب در dropdown
    assert _tile(body, "کل دسترسی‌ها") == len(ALL_PERMISSIONS)
    assert _tile(body, "فعال از نقش") == granted
    assert _tile(body, "غیرفعال") == not_granted
    # نشان‌های جدول: دقیقاً همان تعداد فعال/غیرفعال
    assert _n(body, "state-badge badge-allowed") == granted
    assert _n(body, "state-badge badge-denied") == not_granted


def test_admin_role_known_permission_flags(client, db, make_user):
    """برای admin: view_reports فعال، manage_users (فقط سوپر) غیرفعال."""
    super_u = make_user(role="super_admin")
    login_as(client, super_u["national_code"])

    body = _page(client, "/admin/permissions?tab=roles&role=admin")
    # هر دو دسترسی در جدول حضور دارند
    assert "view_reports" in body and "manage_users" in body
    # view_reports → فعال، manage_users → غیرفعال (وضعیت در همان ردیف)
    assert _row_state(body, "view_reports") == "active"
    assert _row_state(body, "manage_users") == "inactive"


def _row_state(body, code):
    """وضعیت ردیفِ دارای این کد دسترسی: 'active' یا 'inactive'."""
    # ردیف را بردار؛ سپس وضعیت badge داخلش را بخوان
    m = re.search(
        r"<tr>\s*<td[^>]*><code dir=\"ltr\">" + re.escape(code) + r"</code></td>.*?</tr>",
        body,
        re.S,
    )
    assert m, f"ردیف دسترسی «{code}» در جدول یافت نشد"
    row = m.group(0)
    if "state-badge badge-allowed" in row:
        return "active"
    if "state-badge badge-denied" in row:
        return "inactive"
    raise AssertionError(f"وضعیت ردیف «{code}» شناخته نشد")


def test_super_admin_role_grants_all(client, db, make_user):
    super_u = make_user(role="super_admin")
    login_as(client, super_u["national_code"])

    granted, not_granted = _role_flags("super_admin")
    assert granted == len(ALL_PERMISSIONS)
    body = _page(client, "/admin/permissions?tab=roles&role=super_admin")
    assert "مدیر ارشد" in body
    assert _tile(body, "فعال از نقش") == granted
    assert _tile(body, "غیرفعال") == 0
    assert _n(body, "state-badge badge-allowed") == granted
    assert _n(body, "state-badge badge-denied") == 0


def test_user_role_has_no_defaults(client, db, make_user):
    super_u = make_user(role="super_admin")
    login_as(client, super_u["national_code"])

    body = _page(client, "/admin/permissions?tab=roles&role=user")
    assert "کاربر" in body
    assert _tile(body, "فعال از نقش") == 0
    assert _tile(body, "غیرفعال") == len(ALL_PERMISSIONS)
    assert _n(body, "state-badge badge-allowed") == 0
    assert _n(body, "state-badge badge-denied") == len(ALL_PERMISSIONS)


# ---------------------------------------------------------------------------
# نقش نامعتبر
# ---------------------------------------------------------------------------
def test_invalid_role_warns_and_no_table(client, db, make_user):
    super_u = make_user(role="super_admin")
    login_as(client, super_u["national_code"])

    body = _page(client, "/admin/permissions?tab=roles&role=manager")
    assert "نقش انتخاب‌شده معتبر نیست" in body
    # هیچ جدول/آماری رندر نمی‌شود (نقش معتبری انتخاب نشده)
    assert "کل دسترسی‌ها" not in body
    assert "وضعیت</th>" not in body


# ---------------------------------------------------------------------------
# URL-State: پیش‌فرض تب کاربران + حفظ انتخاب
# ---------------------------------------------------------------------------
def test_url_state_defaults_to_users_tab(client, db, make_user):
    super_u = make_user(role="super_admin")
    login_as(client, super_u["national_code"])

    body = _page(client, "/admin/permissions")
    assert 'id="tab-users"' in body and 'class="nav-link active"' in body
    assert 'aria-selected="true"' in body


def test_roles_url_state_keeps_selection_and_tab(client, db, make_user):
    super_u = make_user(role="super_admin")
    login_as(client, super_u["national_code"])

    body = _page(client, "/admin/permissions?tab=roles&role=admin")
    assert 'value="admin" selected' in body
    # تب فعال نقش‌ها؛ پیوندش نقش انتخاب‌شده را حفظ می‌کند
    assert 'id="tab-roles"' in body and 'class="nav-link active"' in body
    assert 'href="/admin/permissions?tab=roles&amp;role=admin"' in body


# ---------------------------------------------------------------------------
# امنیت: فقط سوپرادمین
# ---------------------------------------------------------------------------
def test_roles_tab_requires_super_admin(client, db, make_user):
    adm = make_user(role="admin")
    login_as(client, adm["national_code"])

    resp = client.get("/admin/permissions?tab=roles&role=admin", headers=HTML_ACCEPT)
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Regression فازهای قبل
# ---------------------------------------------------------------------------
def test_regression_users_tab(client, db, make_user):
    super_u = make_user(role="super_admin")
    login_as(client, super_u["national_code"])
    make_user(role="admin")
    body = _page(client, "/admin/permissions?tab=users")
    assert "کاربران" in body
    assert "مجموع:" in body
    assert "مدیریت" in body


def test_regression_perms_tab_selector(client, db, make_user):
    super_u = make_user(role="super_admin")
    login_as(client, super_u["national_code"])
    body = _page(client, "/admin/permissions?tab=perms")
    assert "— انتخاب دسترسی —" in body
    for code in list(ALL_PERMISSIONS)[:5]:
        assert f'value="{code}"' in body


def test_regression_perms_tab_with_permission(client, db, make_user):
    super_u = make_user(role="super_admin")
    login_as(client, super_u["national_code"])

    body = _page(client, "/admin/permissions?tab=perms&permission=view_dashboard")
    assert "مشاهده داشبورد" in body
    assert "وضعیت مؤثر</th>" in body
    assert _tile(body, "کاربران (مطابق فیلترها)") == 1   # فقط سوپرادمین
    assert _n(body, "state-badge badge-allowed") == 1
