"""Tests for login / logout / change-password (web panel auth)."""
from .conftest import USER_PASSWORD, login_as


def test_login_page_loads(client):
    resp = client.get("/login")
    assert resp.status_code == 200
    assert 'name="national_code"' in resp.text


def test_login_unknown_national_code_shows_error(client):
    resp = client.post(
        "/login",
        data={"national_code": "0000000000", "password": "whatever"},
        follow_redirects=False,
    )
    assert resp.status_code == 200
    assert "اشتباه است" in resp.text


def test_login_wrong_password_shows_error(client, make_user):
    creds = make_user(role="user")
    resp = client.post(
        "/login",
        data={"national_code": creds["national_code"], "password": "WrongPass1"},
        follow_redirects=False,
    )
    assert resp.status_code == 200
    assert "اشتباه است" in resp.text


def test_login_disabled_web_account(client, make_user):
    creds = make_user(role="user", web_enabled=False)
    resp = login_as(client, creds["national_code"])
    assert resp.status_code == 200
    assert "غیرفعال" in resp.text


def test_login_success_redirects_to_dashboard(client, make_user):
    creds = make_user(role="user")
    resp = login_as(client, creds["national_code"])
    assert resp.status_code == 302
    assert resp.headers["location"].endswith("/dashboard")


def test_session_persists_after_login(client, make_user):
    creds = make_user(role="user")
    login_as(client, creds["national_code"])
    resp = client.get("/dashboard")
    assert resp.status_code == 200


def test_unauthenticated_dashboard_redirects_to_login(client):
    resp = client.get("/dashboard", follow_redirects=False)
    assert resp.status_code in (302, 307)
    assert "/login" in resp.headers["location"]


def test_logout_clears_session(client, make_user):
    creds = make_user(role="user")
    login_as(client, creds["national_code"])
    assert client.get("/dashboard").status_code == 200
    resp = client.get("/logout", follow_redirects=False)
    assert resp.status_code == 302
    after = client.get("/dashboard", follow_redirects=False)
    assert after.status_code in (302, 307)
    assert "/login" in after.headers["location"]


def test_change_password_page_requires_login(client):
    resp = client.get("/change-password", follow_redirects=False)
    assert resp.status_code == 302
    assert "/login" in resp.headers["location"]


def test_change_password_mismatch_is_rejected(client, make_user):
    creds = make_user(role="user")
    login_as(client, creds["national_code"])
    resp = client.post(
        "/change-password",
        data={
            "current_password": USER_PASSWORD,
            "new_password": "NewPass123",
            "confirm_password": "OtherPass123",
        },
    )
    assert resp.status_code == 200
    assert "یکسان نیست" in resp.text


def test_change_password_too_short_is_rejected(client, make_user):
    creds = make_user(role="user")
    login_as(client, creds["national_code"])
    resp = client.post(
        "/change-password",
        data={
            "current_password": USER_PASSWORD,
            "new_password": "123",
            "confirm_password": "123",
        },
    )
    assert resp.status_code == 200
    assert "۶ کاراکتر" in resp.text


def test_change_password_success_and_relogin(client, make_user):
    creds = make_user(role="user")
    login_as(client, creds["national_code"])
    resp = client.post(
        "/change-password",
        data={
            "current_password": USER_PASSWORD,
            "new_password": "BrandNew99",
            "confirm_password": "BrandNew99",
        },
    )
    assert resp.status_code == 200
    assert "تغییر کرد" in resp.text

    client.get("/logout", follow_redirects=False)
    relogin = login_as(client, creds["national_code"], password="BrandNew99")
    assert relogin.status_code == 302
    assert relogin.headers["location"].endswith("/dashboard")
