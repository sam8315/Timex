"""مالکیت لیست حقوق، نقش بازیگران، عضویت‌های مجاز."""
from types import SimpleNamespace
from unittest.mock import MagicMock

from web.routes.admin_payroll import _can_mutate_run


def _run(created_by=None):
    return SimpleNamespace(created_by=created_by)


def _user(user_id="u1", role="admin"):
    return SimpleNamespace(user_id=user_id, role=role)


def test_mutate_run_creator_allowed():
    assert _can_mutate_run(_user("alice"), _run("alice")) is True


def test_mutate_run_other_user_denied():
    assert _can_mutate_run(_user("bob"), _run("alice")) is False


def test_mutate_run_super_admin_bypass():
    assert _can_mutate_run(_user("bob", role="super_admin"), _run("alice")) is True


def test_mutate_run_legacy_null_created_by():
    assert _can_mutate_run(_user("bob"), _run(None)) is True


def test_actor_names_appends_role_label():
    from web.routes.admin_payroll import _actor_names

    db = MagicMock()
    emp_query = MagicMock()
    emp_query.filter.return_value.all.return_value = []
    user_row = SimpleNamespace(user_id="10", name="کاربر", role="accountant")
    user_query = MagicMock()
    user_query.filter.return_value.all.return_value = [user_row]

    def query_side(model):
        if model.__name__ == "Employee":
            return emp_query
        if model.__name__ == "User":
            return user_query
        return MagicMock()

    db.query.side_effect = query_side

    import web.routes.admin_payroll as mod

    original = mod.role_label_map
    mod.role_label_map = lambda _db: {"accountant": "حسابدار"}
    try:
        labels = _actor_names(db, ["10"])
    finally:
        mod.role_label_map = original

    assert labels["10"] == "کاربر — حسابدار"


def test_is_payroll_membership_allowed(monkeypatch):
    from web.services.payroll import policy_service as ps

    monkeypatch.setattr(
        ps,
        "list_enabled_payroll_memberships",
        lambda _db: [SimpleNamespace(code="4")],
    )
    assert ps.is_payroll_membership_allowed(MagicMock(), "") is True
    assert ps.is_payroll_membership_allowed(MagicMock(), "4") is True
    assert ps.is_payroll_membership_allowed(MagicMock(), "1") is False
