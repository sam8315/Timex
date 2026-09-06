"""Tests for the permission-centric access view (Phase 5).

`?tab=perms&permission=<code>` — «این دسترسی را چه کسانی مؤثراً دارند؟»

اصول اینجا:
- مؤثر = نقش + override — دقیقاً معادل منطق `get_effective_permissions`؛
  هرگز در قالب/JS بازمحاسبه نمی‌شود (Backend = منبع حقیقت).
- آمار سراسری (کل/مؤثر/بدون/override) قبل از pagination محاسبه می‌شود —
  هرگز از تعداد ردیف‌های صفحهٔ جاری حدس زده نمی‌شود.
- فیلترها (role/state/only_override) روی کل مجموعه اعمال می‌شوند.
- درب: فقط سوپرادمین (`require_super_admin`)؛ بدون تغییر در منطق CSRF/دسترسی.
- سناریوهای §22: A) نقش مجاز، بدون override → مجاز  B) نقش مجاز + سلب → غیرمجاز
  C) نقش غیرمجاز + اعطا → مجاز  D) بازنشانی → بازگشت به پیش‌فرض نقش.
"""
import re

from .conftest import login_as

from web.permissions import (
    set_user_permission,
    remove_user_permission,
)

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
    """تعداد ردیف‌هایی که این نشانِ وضعیت/منبع را دارند (محدود به جدول).

    «marker» کل ترکیب کلاس‌هاست (مثل `state-badge badge-allowed`) تا با CSS
    اشتباه نشود.
    """
    return body.count(marker)


def _grant(db, uid, perm):
    set_user_permission(db, uid, perm, True, reason="test", created_by="SYS")
    db.commit()


def _revoke(db, uid, perm):
    set_user_permission(db, uid, perm, False, reason="test", created_by="SYS")
    db.commit()


def _reset(db, uid, perm):
    remove_user_permission(db, uid, perm, reason="test", created_by="SYS")
    db.commit()


# ---------------------------------------------------------------------------
# سناریوهای §22 (A تا D) — «view_reports» برای role=admin پیش‌فرض مجاز است.
# ---------------------------------------------------------------------------
def test_scenario_a_role_allowed_no_override(client, db, make_user):
    """A) مدیر، بدون override → وضعیت مؤثر «مجاز» با منبع «نقش»."""
    super_u = make_user(role="super_admin")
    login_as(client, super_u["national_code"])
    make_user(role="admin")

    body = _page(client, "/admin/permissions?tab=perms&permission=view_reports")
    assert _tile(body, "کاربران (مطابق فیلترها)") == 2      # سوپرادمین + مدیر
    assert _tile(body, "دارای دسترسی مؤثر") == 2
    assert _tile(body, "بدون دسترسی مؤثر") == 0
    assert _tile(body, "دارای Override (این دسترسی)") == 0
    # هر دو ردیف: وضعیت «مجاز» + منبع «نقش» (و هیچ منبع override نیست)
    assert _n(body, "state-badge badge-allowed") == 2
    assert _n(body, "source-tag role-only") == 2
    assert _n(body, "source-tag override-grant") == 0
    assert _n(body, "source-tag override-revoke") == 0


def test_scenario_b_role_allowed_revoked(client, db, make_user):
    """B) مدیر که view_reports از او سلب شده → «غیرمجاز» و منبع «Override (سلب)»."""
    super_u = make_user(role="super_admin")
    login_as(client, super_u["national_code"])
    adm = make_user(role="admin")
    _revoke(db, adm["user_id"], "view_reports")

    body = _page(client, "/admin/permissions?tab=perms&permission=view_reports")
    assert _tile(body, "کاربران (مطابق فیلترها)") == 2
    assert _tile(body, "دارای دسترسی مؤثر") == 1          # فقط سوپرادمین
    assert _tile(body, "بدون دسترسی مؤثر") == 1           # مدیرِ سلب‌شده
    assert _tile(body, "دارای Override (این دسترسی)") == 1
    assert _n(body, "state-badge badge-allowed") == 1
    assert _n(body, "state-badge badge-denied") == 1
    assert _n(body, "source-tag role-only") == 1
    assert _n(body, "source-tag override-revoke") == 1


def test_scenario_c_role_denied_granted(client, db, make_user):
    """C) کاربر عادی (بدون نقش پایه) که دسترسی اعطا شده → «مجاز» و «Override (اعطا)»."""
    super_u = make_user(role="super_admin")
    login_as(client, super_u["national_code"])
    usr = make_user(role="user")
    _grant(db, usr["user_id"], "view_reports")

    body = _page(client, "/admin/permissions?tab=perms&permission=view_reports")
    assert _tile(body, "کاربران (مطابق فیلترها)") == 2
    assert _tile(body, "دارای دسترسی مؤثر") == 2
    assert _tile(body, "دارای Override (این دسترسی)") == 1
    assert _n(body, "state-badge badge-allowed") == 2
    assert _n(body, "source-tag override-grant") == 1
    assert _n(body, "source-tag role-only") == 1


def test_scenario_d_reset_returns_to_role_default(client, db, make_user):
    """D) بعد از سلب و سپس بازنشانی → پیش‌فرض نقش دوباره برقرار و override حذف می‌شود."""
    super_u = make_user(role="super_admin")
    login_as(client, super_u["national_code"])
    adm = make_user(role="admin")
    _revoke(db, adm["user_id"], "view_reports")
    _reset(db, adm["user_id"], "view_reports")

    body = _page(client, "/admin/permissions?tab=perms&permission=view_reports")
    assert _tile(body, "دارای دسترسی مؤثر") == 2
    assert _tile(body, "دارای Override (این دسترسی)") == 0
    assert _n(body, "source-tag role-only") == 2
    assert _n(body, "source-tag override-grant") == 0
    assert _n(body, "source-tag override-revoke") == 0


# ---------------------------------------------------------------------------
# صداقت آمار سراسری (مرتبط با pagination)
# ---------------------------------------------------------------------------
def test_global_counts_not_page_scoped(client, db, make_user):
    """آمار سراسری با per_page کوچک باید کل مجموعه را نشان دهد، نه صفحهٔ جاری را."""
    super_u = make_user(role="super_admin")
    login_as(client, super_u["national_code"])
    for _ in range(6):
        make_user(role="admin")      # view_reports: مجاز
    make_user(role="user")           # view_reports: بدون

    body = _page(client, "/admin/permissions?tab=perms&permission=view_reports&per_page=5")
    # 7 مؤثر (سوپرادمین + ۶ مدیر) + 1 بدون = 8 کل
    assert _tile(body, "کاربران (مطابق فیلترها)") == 8
    assert _tile(body, "دارای دسترسی مؤثر") == 7
    assert _tile(body, "بدون دسترسی مؤثر") == 1
    # در حالی که فقط ۵ ردیف در صفحه ۱ دیده می‌شود (۱ سرصفحه + ۵ بدنه)
    assert body.count("<tr>") == 6


# ---------------------------------------------------------------------------
# فیلترها (روی کل مجموعه)
# ---------------------------------------------------------------------------
def test_filters_role_state_only_override(client, db, make_user):
    super_u = make_user(role="super_admin")
    login_as(client, super_u["national_code"])
    make_user(role="admin")                              # مجاز/نقش
    usr = make_user(role="user")
    _grant(db, usr["user_id"], "view_reports")           # مجاز/override
    other = make_user(role="admin")
    _revoke(db, other["user_id"], "view_reports")        # غیرمجاز/override

    # فیلتر نقش = user → فقط کاربرِ دارای grant
    body = _page(client, "/admin/permissions?tab=perms&permission=view_reports&role=user")
    assert _tile(body, "کاربران (مطابق فیلترها)") == 1
    assert _n(body, "source-tag override-grant") == 1

    # فیلتر وضعیت = denied → فقط مدیرِ سلب‌شده
    body = _page(client, "/admin/permissions?tab=perms&permission=view_reports&state=denied")
    assert _tile(body, "کاربران (مطابق فیلترها)") == 1
    assert _n(body, "source-tag override-revoke") == 1

    # فقط override → دو کاربر دارای override (grant + revoke)
    body = _page(client, "/admin/permissions?tab=perms&permission=view_reports&only_override=true")
    assert _tile(body, "کاربران (مطابق فیلترها)") == 2
    assert _n(body, "source-tag override-grant") == 1
    assert _n(body, "source-tag override-revoke") == 1


def test_empty_state_when_filters_exclude_everyone(client, db, make_user):
    """manage_users فقط برای super_admin است؛ فیلتر role=user → نتیجهٔ صادقانهٔ خالی."""
    super_u = make_user(role="super_admin")
    login_as(client, super_u["national_code"])

    body = _page(client, "/admin/permissions?tab=perms&permission=manage_users&role=user")
    assert "کاربری با این دسترسی مؤثر یافت نشد" in body
    assert _tile(body, "کاربران (مطابق فیلترها)") == 0


# ---------------------------------------------------------------------------
# URL-State و دسترسی نامعتبر
# ---------------------------------------------------------------------------
def test_permission_param_in_dropdown_from_catalog(client, db, make_user):
    """گزینه‌های انتخاب دسترسی از ALL_PERMISSIONS واقعی می‌آیند (هیچ کدی دستی نیست)."""
    from web.permissions import ALL_PERMISSIONS

    super_u = make_user(role="super_admin")
    login_as(client, super_u["national_code"])
    body = _page(client, "/admin/permissions?tab=perms")
    for code in list(ALL_PERMISSIONS)[:5]:
        assert f'value="{code}"' in body
    assert "— انتخاب دسترسی —" in body


def test_invalid_permission_param_warns_and_no_table(client, db, make_user):
    super_u = make_user(role="super_admin")
    login_as(client, super_u["national_code"])

    body = _page(client, "/admin/permissions?tab=perms&permission=not_a_real_perm")
    assert "دسترسی انتخاب‌شده معتبر نیست" in body
    assert "کاربری با این دسترسی مؤثر یافت نشد" not in body
    # هیچ جدولی از کاربران رندر نمی‌شود (بدون permission معتبر) — سرصفحهٔ جدول حضور ندارد
    assert "وضعیت مؤثر</th>" not in body


def test_url_state_refresh_defaults_to_users_tab(client, db, make_user):
    """بدون پارامتر، تب پیش‌فرض «کاربران» و نشانِ active روی آن است (رفتار فاز ۴)."""
    super_u = make_user(role="super_admin")
    login_as(client, super_u["national_code"])
    body = _page(client, "/admin/permissions")
    assert 'id="tab-users"' in body and 'class="nav-link active"' in body
    assert 'id="tab-perms"' in body
    assert 'aria-selected="true"' in body


# ---------------------------------------------------------------------------
# امنیت: فقط سوپرادمین
# ---------------------------------------------------------------------------
def test_perms_tab_requires_super_admin(client, db, make_user):
    adm = make_user(role="admin")
    login_as(client, adm["national_code"])
    resp = client.get(
        "/admin/permissions?tab=perms&permission=view_reports", headers=HTML_ACCEPT
    )
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# §23 Regression: صفحهٔ per-user + عملیات Grant/Revoke/Reset با CSRF واقعی
# ---------------------------------------------------------------------------
def test_users_tab_regression(client, db, make_user):
    super_u = make_user(role="super_admin")
    login_as(client, super_u["national_code"])
    make_user(role="admin")
    body = _page(client, "/admin/permissions?tab=users")
    assert "کاربران" in body
    assert "مجموع:" in body
    assert "مدیریت" in body


def test_per_user_page_and_csrf_toggle_regression(client, db, make_user):
    target = make_user(role="admin")
    super_u = make_user(role="super_admin")
    login_as(client, super_u["national_code"])

    page = client.get(f"/admin/permissions/{target['user_id']}", headers=HTML_ACCEPT)
    assert page.status_code == 200

    csrf = re.search(r'name="csrf_token" value="([^"]+)"', page.text)
    assert csrf, "توکن CSRF در صفحهٔ per-user یافت نشد"
    token = csrf.group(1)

    # Revoke با CSRF معتبر از طریق فرم واقعی → ریدایرکت 302
    resp = client.post(
        f"/admin/permissions/{target['user_id']}/toggle",
        data={
            "permission": "view_reports",
            "action": "revoke",
            "reason": "تست فاز ۵",
            "csrf_token": token,
        },
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert "msg" in resp.headers["location"]