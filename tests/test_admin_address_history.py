"""
Focused tests for the read-only address history card on the admin profile.

Covers:
- history shown with snapshots and Jalali timestamp
- newest-first ordering
- CREATE/UPDATE/DELETE labels and previous-snapshot labeling
- actor display incl. NULL => سیستم
- empty state
- /profile contains no history
- non-admin blocked; admin without edit_profile sees no rows
- latest-50 limit with truncation note
"""
from web.services.address_service import (
    create_address, update_address, delete_address,
)

from .conftest import login_as

HTML_ACCEPT = {"Accept": "text/html"}


def _make_addr(db, user_id, **overrides):
    defaults = dict(
        address_type="HOME",
        residence_status="owner",
        province="Tehran",
        city="Tehran",
        postal_code="1234567890",
        address_text="خیابان آزادی، تهران",
        is_primary=False,
    )
    defaults.update(overrides)
    return create_address(db, user_id=user_id, **defaults)


def _login(client, creds):
    return login_as(client, creds["national_code"])


def _admin_page(client, target_user_id):
    resp = client.get(f"/admin/profile/{target_user_id}",
                      headers=HTML_ACCEPT)
    assert resp.status_code == 200, resp.status_code
    return resp.text


def test_admin_profile_shows_history(client, db, make_user):
    """History card lists the created snapshot with timestamp."""
    super_u = make_user(role="super_admin")
    _login(client, super_u)
    target = make_user(role="user", balance_al=None)
    _make_addr(db, target["user_id"], postal_code="7777777701",
               changed_by=super_u["user_id"])

    body = _admin_page(client, target["user_id"])
    assert "تاریخچه تغییرات آدرس" in body
    assert "7777777701" in body
    assert "اسنپ‌شات ایجادشده" in body
    assert super_u["user_id"] in body


def test_history_newest_first(client, db, make_user):
    """Newest UPDATE appears before the CREATE row."""
    super_u = make_user(role="super_admin")
    _login(client, super_u)
    target = make_user(role="user", balance_al=None)
    addr = _make_addr(db, target["user_id"], postal_code="7777777702")
    update_address(db, target["user_id"], addr.id, province="Fars")
    update_address(db, target["user_id"], addr.id, province="Gilan")

    body = _admin_page(client, target["user_id"])
    assert body.index("وضعیت قبل از تغییر") < body.index(
        "اسنپ‌شات ایجادشده")
    # newest UPDATE snapshot (Fars) precedes the CREATE block
    assert body.index("Fars") < body.index("اسنپ‌شات ایجادشده")


def test_history_action_labels(client, db, make_user):
    """CREATE/UPDATE/DELETE badges and snapshot labels render."""
    super_u = make_user(role="super_admin")
    _login(client, super_u)
    target = make_user(role="user", balance_al=None)
    addr = _make_addr(db, target["user_id"], postal_code="7777777703")
    update_address(db, target["user_id"], addr.id, province="Fars")
    delete_address(db, target["user_id"], addr.id)

    body = _admin_page(client, target["user_id"])
    assert '<span class="badge bg-success">ایجاد</span>' in body
    assert '<span class="badge bg-warning text-dark">ویرایش</span>' in body
    assert '<span class="badge bg-danger">حذف</span>' in body
    assert body.count("وضعیت قبل از تغییر") == 2
    assert body.count("اسنپ‌شات ایجادشده") == 1
    # no edit/delete affordances inside the history card
    assert "فقط خواندنی" in body


def test_history_actor_and_system(client, db, make_user):
    """changed_by shown; NULL renders as سیستم."""
    super_u = make_user(role="super_admin")
    _login(client, super_u)
    target = make_user(role="user", balance_al=None)
    addr = _make_addr(db, target["user_id"], postal_code="7777777704")
    update_address(db, target["user_id"], addr.id, province="Fars",
                   changed_by="ADMIN-X")

    body = _admin_page(client, target["user_id"])
    assert "ADMIN-X" in body
    assert "سیستم" in body


def test_history_empty_state(client, db, make_user):
    """No history => clean empty message with card title."""
    super_u = make_user(role="super_admin")
    _login(client, super_u)
    target = make_user(role="user", balance_al=None)

    body = _admin_page(client, target["user_id"])
    assert "تاریخچه تغییرات آدرس" in body
    assert "تاریخچه‌ای برای آدرس‌ها ثبت نشده است" in body


def test_profile_has_no_history(client, db, make_user):
    """Normal /profile never receives address history data."""
    me = make_user(role="user", balance_al=None)
    _login(client, me)
    _make_addr(db, me["user_id"], postal_code="7777777705")

    resp = client.get("/profile", headers=HTML_ACCEPT)
    assert resp.status_code == 200
    assert "تاریخچه تغییرات آدرس" not in resp.text
    assert "وضعیت قبل از تغییر" not in resp.text


def test_non_admin_blocked_from_admin_profile(client, db, make_user):
    """Plain users get 403 on the admin profile (no history leak)."""
    me = make_user(role="user", balance_al=None)
    other = make_user(role="user", balance_al=None)
    _login(client, me)

    resp = client.get(f"/admin/profile/{other['user_id']}",
                      headers=HTML_ACCEPT)
    assert resp.status_code == 403


def test_admin_without_edit_profile_sees_no_rows(client, db, make_user):
    """Admins lacking edit_profile get the empty history state."""
    adm = make_user(role="admin")
    _login(client, adm)
    target = make_user(role="user", balance_al=None)
    _make_addr(db, target["user_id"], postal_code="7777777706")

    body = _admin_page(client, target["user_id"])
    # address card still shows the address ...
    assert "7777777706" in body
    # ... but the history section stays empty
    assert "تاریخچه‌ای برای آدرس‌ها ثبت نشده است" in body


def test_history_limit_50(client, db, make_user):
    """Beyond 50 rows only the newest 50 show with a truncation note."""
    super_u = make_user(role="super_admin")
    _login(client, super_u)
    target = make_user(role="user", balance_al=None)
    addr = _make_addr(db, target["user_id"], postal_code="7777777707")
    for i in range(54):
        update_address(db, target["user_id"], addr.id, notes=f"note-{i}")

    body = _admin_page(client, target["user_id"])
    assert "فقط ۵۰ مورد اخیر نمایش داده می‌شود" in body
