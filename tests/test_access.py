"""Access-control matrix for every web-panel area.

Anonymous  -> 307 redirect to /login (or 200 for /login itself)
Plain user -> 403 on admin pages, 200 on user pages
Admin      -> 200 on admin pages, 403 on super-admin pages
Super-admin-> 200 everywhere
"""
import pytest

from .conftest import login_as

USER_PAGES = [
    "/dashboard",
    "/leave",
    "/profile",
    "/contract",
    "/attendance",
    "/education",
]

ADMIN_PAGES = [
    "/admin",
    "/admin/users",
    "/admin/attendance",
    "/admin/contracts",
    "/admin/leave-balances",
    "/admin/leave-transactions",
    "/admin/leave-requests",
    "/admin/holidays",
    "/admin/daily-status",
    "/admin/carry-forward-requests",
    "/admin/education",
    "/admin/import-previous-leave",
    "/admin/leave-requests/register",
    "/reports",
]

SUPER_PAGES = [
    "/admin/permissions",
    "/admin/policies",
    "/admin/policies/leave",
    "/admin/policies/regions",
]


def _logged_client(client, make_user, role):
    creds = make_user(role=role)
    resp = login_as(client, creds["national_code"])
    assert resp.status_code == 302
    return creds


@pytest.mark.parametrize("path", USER_PAGES)
def test_user_pages_require_login(client, path):
    resp = client.get(path, follow_redirects=False)
    assert resp.status_code in (302, 307)
    assert "/login" in resp.headers["location"]


@pytest.mark.parametrize("path", USER_PAGES)
def test_user_pages_load_for_all_roles(client, make_user, path):
    for role in ("user", "admin", "super_admin"):
        _logged_client(client, make_user, role)
        resp = client.get(path)
        assert resp.status_code == 200, f"{path} as {role}"
        client.get("/logout", follow_redirects=False)


@pytest.mark.parametrize("path", ADMIN_PAGES)
def test_admin_pages_require_login(client, path):
    resp = client.get(path, follow_redirects=False)
    assert resp.status_code in (302, 307)
    assert "/login" in resp.headers["location"]


@pytest.mark.parametrize("path", ADMIN_PAGES)
def test_admin_pages_forbidden_for_plain_user(client, make_user, path):
    _logged_client(client, make_user, "user")
    resp = client.get(path, follow_redirects=False)
    assert resp.status_code == 403, path


@pytest.mark.parametrize("path", ADMIN_PAGES)
def test_admin_pages_load_for_admin_and_super(client, make_user, path):
    for role in ("admin", "super_admin"):
        _logged_client(client, make_user, role)
        resp = client.get(path)
        assert resp.status_code == 200, f"{path} as {role}"
        client.get("/logout", follow_redirects=False)


@pytest.mark.parametrize("path", SUPER_PAGES)
def test_super_pages_require_login(client, path):
    resp = client.get(path, follow_redirects=False)
    assert resp.status_code in (302, 307)
    assert "/login" in resp.headers["location"]


@pytest.mark.parametrize("path", SUPER_PAGES)
def test_super_pages_forbidden_for_user_and_admin(client, make_user, path):
    for role in ("user", "admin"):
        _logged_client(client, make_user, role)
        resp = client.get(path, follow_redirects=False)
        assert resp.status_code == 403, f"{path} as {role}"
        client.get("/logout", follow_redirects=False)


@pytest.mark.parametrize("path", SUPER_PAGES)
def test_super_pages_load_for_super_admin(client, make_user, path):
    _logged_client(client, make_user, "super_admin")
    resp = client.get(path)
    assert resp.status_code == 200, path


def test_parameterized_admin_pages(client, make_user):
    """Routes that need an existing target user id."""
    target = make_user(role="user")
    paths_admin = [
        f"/admin/profile/{target['user_id']}",
        f"/admin/attendance/user/{target['user_id']}",
    ]
    paths_super = [f"/admin/profile/{target['user_id']}/edit"]

    _logged_client(client, make_user, "user")
    for path in paths_admin + paths_super:
        assert client.get(path, follow_redirects=False).status_code == 403
    client.get("/logout", follow_redirects=False)

    _logged_client(client, make_user, "admin")
    for path in paths_admin:
        assert client.get(path).status_code == 200, path
    for path in paths_super:
        assert client.get(path, follow_redirects=False).status_code == 403
    client.get("/logout", follow_redirects=False)

    _logged_client(client, make_user, "super_admin")
    for path in paths_admin + paths_super:
        assert client.get(path).status_code == 200, path
