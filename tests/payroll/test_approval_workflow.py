"""گردش تأیید چندمرحله‌ای لیست حقوق."""
from datetime import datetime, timezone

import pytest
from sqlalchemy.exc import IntegrityError

from models.payroll import (
    PayrollApprovalStepSetting,
    PayrollRun,
    PayrollRunApprovalStep,
)
from models.user_permission import UserPermission
from tests.conftest import TestingSessionLocal, login_as
from web.services.payroll import approval_service as svc
from web.services.payroll import run_service
from web.services.payroll.approval_service import PayrollApprovalError
from web.services.payroll.run_service import PayrollRunError


@pytest.fixture(autouse=True)
def _clean_workflow_tables():
    def wipe():
        session = TestingSessionLocal()
        try:
            session.query(PayrollRun).filter(PayrollRun.notes == "approval-test").delete(
                synchronize_session=False
            )
            session.query(PayrollApprovalStepSetting).delete()
            session.commit()
        finally:
            session.close()

    wipe()
    yield
    wipe()


def _settings(db, specs):
    """specs: [(عنوان، شناسهٔ تأییدکننده یا None)] به همین ترتیب."""
    db.query(PayrollApprovalStepSetting).delete()
    db.commit()
    for order, (title, approver) in enumerate(specs, start=1):
        db.add(PayrollApprovalStepSetting(step_order=order, title=title, approver_user_id=approver))
    db.commit()


def _run(db, status="calculated", month=1):
    period = run_service.get_or_create_period(db, 1390, month)
    run = PayrollRun(period_id=period.id, status=status, notes="approval-test")
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def _started(db, specs, status="calculated"):
    _settings(db, specs)
    run = _run(db, status=status)
    svc.snapshot_run(db, run)
    db.commit()
    return run


def _fresh(db, run_id):
    db.expire_all()
    return run_service.get_run(db, run_id, ensure_defaults=False)


def _boss(make_user, **kw):
    return make_user(role="super_admin", **kw)["user_id"]


def test_single_step_workflow_approves_and_completes(db, make_user):
    a = _boss(make_user)
    run = _started(db, [("تأیید نهایی", a)])
    run_service.approve_run(db, run.id, a)
    run = _fresh(db, run.id)
    assert run.status == "approved"
    assert run.approved_by == a and run.approved_at is not None
    assert run.approval_steps[0].approved_by == a
    assert run.approval_steps[0].approved_at is not None
    run_service.publish_run(db, run.id, a)
    assert _fresh(db, run.id).status == "published"


def test_multi_step_in_order_and_duplicate_and_out_of_order(db, make_user):
    hr, acc, fin = _boss(make_user), _boss(make_user), _boss(make_user)
    run = _started(db, [("نیروی انسانی", hr), ("حسابدار", acc), ("مدیر مالی", fin)])

    with pytest.raises(PayrollRunError, match="نوبت"):
        run_service.approve_run(db, run.id, fin)  # خارج از ترتیب
    run_service.approve_run(db, run.id, hr)
    assert _fresh(db, run.id).status == "calculated"

    with pytest.raises(PayrollRunError, match="قبلاً"):
        run_service.approve_run(db, run.id, hr)  # تأیید تکراری
    with pytest.raises(PayrollRunError, match="نوبت"):
        run_service.approve_run(db, run.id, fin)

    run_service.approve_run(db, run.id, acc)
    assert _fresh(db, run.id).status == "calculated"
    run_service.approve_run(db, run.id, fin)
    run = _fresh(db, run.id)
    assert run.status == "approved"
    assert [s.approved_by for s in run.approval_steps] == [hr, acc, fin]
    assert all(s.approved_at for s in run.approval_steps)
    with pytest.raises(PayrollRunError):
        run_service.approve_run(db, run.id, fin)


def test_unlisted_user_cannot_approve(db, make_user):
    a, stranger = _boss(make_user), _boss(make_user)
    run = _started(db, [("مرحله", a)])
    with pytest.raises(PayrollRunError, match="اختصاص"):
        run_service.approve_run(db, run.id, stranger)
    assert _fresh(db, run.id).status == "calculated"


def test_user_without_permission_cannot_approve_even_if_assigned(db, make_user):
    plain = make_user(role="user")["user_id"]
    run = _started(db, [("مرحله", plain)])
    with pytest.raises(PayrollRunError, match="مجوز"):
        run_service.approve_run(db, run.id, plain)


def test_revoked_permission_blocks_approval(db, make_user):
    a = _boss(make_user)
    run = _started(db, [("مرحله", a)])
    db.add(UserPermission(user_id=a, permission="approve_payroll", granted=False))
    db.commit()
    with pytest.raises(PayrollRunError, match="مجوز"):
        run_service.approve_run(db, run.id, a)


def test_step_without_named_approver_accepts_any_permission_holder(db, make_user):
    a, b = _boss(make_user), _boss(make_user)
    run = _started(db, [("مرحله ۱", None), ("مرحله ۲", None)])
    run_service.approve_run(db, run.id, a)
    run_service.approve_run(db, run.id, b)
    run = _fresh(db, run.id)
    assert run.status == "approved"
    assert [s.approved_by for s in run.approval_steps] == [a, b]


def test_publish_blocked_until_all_steps_done(db, make_user):
    a, b = _boss(make_user), _boss(make_user)
    run = _started(db, [("۱", a), ("۲", b)])
    with pytest.raises(PayrollRunError):
        run_service.publish_run(db, run.id, a)  # هنوز calculated
    run_service.approve_run(db, run.id, a)
    # حتی اگر وضعیت به‌اشتباه approved شود، ناقص بودن گردش مانع انتشار است
    row = db.query(PayrollRun).filter(PayrollRun.id == run.id).one()
    row.status = "approved"
    db.commit()
    with pytest.raises(PayrollRunError, match="مراحل"):
        run_service.publish_run(db, run.id, a)


def test_add_approver_outside_employees_and_validation(db, make_user):
    outsider = make_user(role="super_admin", create_employee=False)["user_id"]
    row = svc.add_step(db, title="ناظر بیرونی", approver_user_id=outsider)
    assert row.approver_user_id == outsider
    assert outsider in {a["user_id"] for a in svc.list_eligible_approvers(db)}

    no_perm = make_user(role="user", create_employee=False)["user_id"]
    with pytest.raises(PayrollApprovalError, match="مجوز"):
        svc.add_step(db, title="x", approver_user_id=no_perm)
    with pytest.raises(PayrollApprovalError, match="ثبت‌شده"):
        svc.add_step(db, title="x", approver_user_id="no-such-user")
    with pytest.raises(PayrollApprovalError):
        svc.add_step(db, title="   ", approver_user_id=None)
    assert no_perm not in {a["user_id"] for a in svc.list_eligible_approvers(db)}


def test_defaults_seeded_and_edit_delete_move(db, make_user):
    db.query(PayrollApprovalStepSetting).delete()
    db.commit()
    rows = svc.list_settings(db)
    assert [r.title for r in rows] == list(svc.DEFAULT_STEP_TITLES)
    assert [r.step_order for r in rows] == [1, 2, 3, 4]

    svc.move_step(db, rows[3].id, "up")
    svc.move_step(db, rows[0].id, "down")
    titles = [r.title for r in svc.list_settings(db)]
    assert titles == ["حسابدار", "نیروی انسانی", "مدیر درمانگاه", "مدیر مالی"]
    svc.move_step(db, svc.list_settings(db)[0].id, "up")  # بالاتر از اول: بدون اثر
    assert [r.title for r in svc.list_settings(db)] == titles

    first = svc.list_settings(db)[0]
    svc.update_step(db, first.id, title="  حسابداری   مرکزی ", approver_user_id="")
    assert svc.list_settings(db)[0].title == "حسابداری مرکزی"

    svc.delete_step(db, first.id)
    after = svc.list_settings(db)
    assert [r.step_order for r in after] == [1, 2, 3]
    for r in after[:-1]:
        svc.delete_step(db, r.id)
    with pytest.raises(PayrollApprovalError, match="حداقل"):
        svc.delete_step(db, svc.list_settings(db)[0].id)


def test_settings_order_unique_constraint(db):
    _settings(db, [("الف", None), ("ب", None)])
    db.add(PayrollApprovalStepSetting(step_order=1, title="تکراری"))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_run_step_constraints_unique_and_title(db):
    run = _run(db)
    db.add(PayrollRunApprovalStep(run_id=run.id, step_order=1, title="الف"))
    db.commit()
    db.add(PayrollRunApprovalStep(run_id=run.id, step_order=1, title="ب"))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()
    db.add(PayrollRunApprovalStep(run_id=run.id, step_order=2, title="  "))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_snapshot_is_frozen_when_settings_change(db, make_user):
    a, b = _boss(make_user), _boss(make_user)
    run = _started(db, [("نیروی انسانی", a), ("حسابدار", b)])
    run_service.approve_run(db, run.id, a)

    rows = svc.list_settings(db)
    svc.update_step(db, rows[0].id, title="عنوان جدید", approver_user_id=b)
    svc.add_step(db, title="مرحلهٔ تازه", approver_user_id=_boss(make_user))
    svc.delete_step(db, rows[1].id)
    svc.move_step(db, svc.list_settings(db)[0].id, "down")

    run = _fresh(db, run.id)
    assert [(s.step_order, s.title, s.approver_user_id) for s in run.approval_steps] == [
        (1, "نیروی انسانی", a),
        (2, "حسابدار", b),
    ]
    assert run.approval_steps[0].approved_by == a  # تأیید قبلی پاک نشده
    # snapshot دوباره هم چیزی را عوض نمی‌کند
    svc.snapshot_run(db, run)
    assert len(_fresh(db, run.id).approval_steps) == 2
    run_service.approve_run(db, run.id, b)
    assert _fresh(db, run.id).status == "approved"


def test_recalculation_blocked_once_approvals_started(db, make_user):
    a, b = _boss(make_user), _boss(make_user)
    run = _started(db, [("۱", a), ("۲", b)])
    run_service.approve_run(db, run.id, a)
    events = list(run_service.iter_calculate(db, run.id))
    assert events[-1]["done"] and "بازگشایی" in events[-1]["error"]
    assert _fresh(db, run.id).approval_steps[0].approved_at is not None


def test_full_calculation_snapshots_current_settings_and_refreshes_before_approvals(db, make_user):
    a = _boss(make_user)
    _settings(db, [("الف", a)])
    run = _run(db, status="draft")
    list(run_service.iter_calculate(db, run.id))
    run = _fresh(db, run.id)
    assert run.status == "calculated"
    assert [s.title for s in run.approval_steps] == ["الف"]

    _settings(db, [("الف", a), ("ب", None)])
    list(run_service.iter_calculate(db, run.id))  # هنوز تأییدی نیست: مراحل تازه می‌شود
    assert [s.title for s in _fresh(db, run.id).approval_steps] == ["الف", "ب"]


def test_reopen_restarts_workflow_and_keeps_history_in_notes(db, make_user):
    a = _boss(make_user)
    run = _started(db, [("تأیید", a)])
    run_service.approve_run(db, run.id, a)
    run_service.reopen_run(db, run.id, a, "اصلاح")
    run = _fresh(db, run.id)
    assert run.status == "calculated"
    assert all(s.approved_at is None for s in run.approval_steps)
    assert "previous approvals" in run.notes and "تأیید" in run.notes
    run_service.approve_run(db, run.id, a)
    assert _fresh(db, run.id).status == "approved"


def test_workflow_view_progress_preview_and_times(db, make_user):
    a, b = _boss(make_user), _boss(make_user)
    run = _started(db, [("نیروی انسانی", a), ("حسابدار", b), ("مدیر مالی", None)])
    wf = svc.build_workflows(db, [_fresh(db, run.id)])[run.id]
    assert (wf["done"], wf["total"], wf["started"]) == (0, 3, False)

    run_service.approve_run(db, run.id, a)
    wf = svc.build_workflows(db, [_fresh(db, run.id)])[run.id]
    assert (wf["done"], wf["total"], wf["started"]) == (1, 3, True)
    first, second, third = wf["steps"]
    assert first["approved"] and first["approved_at"] is not None and first["approved_by"] == a
    assert first["approver_name"] and first["title"] == "نیروی انسانی"
    assert not second["approved"] and second["approved_at"] is None
    assert third["approver_id"] is None and third["title"] == "مدیر مالی" and not third["approved"]


def test_legacy_approved_run_without_steps_stays_compatible(db, make_user):
    a = _boss(make_user)
    _settings(db, [("الف", None), ("ب", None)])
    run = _run(db, status="approved")
    run.approved_by = a
    run.approved_at = datetime(2026, 1, 1, 8, 30, tzinfo=timezone.utc)
    db.commit()
    wf = svc.build_workflows(db, [_fresh(db, run.id)])[run.id]
    assert (wf["done"], wf["total"]) == (1, 1)
    assert wf["steps"][0]["approved_at"] == run.approved_at
    run_service.publish_run(db, run.id, a)  # بدون مرحله: مثل قبل منتشر می‌شود
    assert _fresh(db, run.id).status == "published"


def test_legacy_calculated_run_gets_snapshot_on_first_approval(db, make_user):
    a = _boss(make_user)
    _settings(db, [("الف", a)])
    run = _run(db, status="calculated")
    pre = svc.build_workflows(db, [_fresh(db, run.id)])[run.id]
    assert (pre["done"], pre["total"], pre["snapshot"]) == (0, 1, False)
    run_service.approve_run(db, run.id, a)
    run = _fresh(db, run.id)
    assert run.status == "approved" and len(run.approval_steps) == 1


def test_draft_run_has_no_workflow_display(db):
    _settings(db, [("الف", None)])
    run = _run(db, status="draft")
    wf = svc.build_workflows(db, [_fresh(db, run.id)])[run.id]
    assert wf["total"] == 0


# ---------------------------------------------------------------- UI / routes

def _release(db, run):
    """جلسهٔ تست را می‌بندد تا ensure_payroll_defaults در درخواست روی قفل جدول گیر نکند."""
    rid = run.id if run is not None else None
    db.rollback()
    return rid


def _ui_login(client, make_user):
    admin = make_user(role="super_admin")
    resp = login_as(client, admin["national_code"], admin["password"])
    assert resp.status_code in (302, 303)
    return admin


def test_list_page_shows_dynamic_progress_and_preview(client, db, make_user):
    admin = _ui_login(client, make_user)
    run = _started(db, [("الف", admin["user_id"]), ("ب", None), ("ج", None)])
    run_service.approve_run(db, run.id, admin["user_id"])
    _release(db, None)
    html = client.get("/admin/payroll").text
    assert "گردش تأیید" in html
    assert "<th>تأییدکننده</th>" not in html
    assert "۱ از ۳ مرحله" in html
    assert "تأیید شد" in html and "در انتظار" in html
    assert "در حال تأیید" in html
    assert "wf-pop" in html


def test_detail_page_boxes_in_order_without_signature_assets(client, db, make_user):
    admin = _ui_login(client, make_user)
    run = _started(db, [("نیروی انسانی", admin["user_id"]), ("حسابدار", None)])
    rid = _release(db, run)
    html = client.get(f"/admin/payroll/runs/{rid}").text
    assert html.index("نیروی انسانی", html.index('id="approvalBoxes"')) < html.index(
        "حسابدار", html.index('id="approvalBoxes"')
    )
    assert html.count('class="wf-box ') == 2
    assert "در انتظار تأیید" in html
    assert "wf-box-sign" in html
    assert "<img" not in html[html.index('id="approvalBoxes"'):html.index("payroll-progress-backdrop")]
    assert "type=\"file\"" not in html

    run_service.approve_run(db, rid, admin["user_id"])
    _release(db, None)
    html = client.get(f"/admin/payroll/runs/{rid}").text
    assert "wf-box is-done" in html
    assert "تاریخ:" not in html and "ساعت:" not in html


def test_detail_page_legacy_run_renders(client, db, make_user):
    admin = _ui_login(client, make_user)
    run = _run(db, status="approved")
    run.approved_by = admin["user_id"]
    run.approved_at = datetime(2026, 1, 1, 8, 30, tzinfo=timezone.utc)
    db.commit()
    rid = _release(db, run)
    resp = client.get(f"/admin/payroll/runs/{rid}")
    assert resp.status_code == 200
    assert "۱ از ۱ مرحله" in resp.text


def test_approve_route_enforces_ownership_and_order(client, db, make_user):
    admin = _ui_login(client, make_user)
    other = _boss(make_user)
    run = _started(db, [("اول", other), ("دوم", admin["user_id"])])
    rid = _release(db, run)
    resp = client.post(f"/admin/payroll/runs/{rid}/approve")
    assert resp.status_code == 302 and "error=" in resp.headers["location"]
    assert _fresh(db, rid).approval_steps[0].approved_at is None
    run_service.approve_run(db, rid, other)
    _release(db, None)
    resp = client.post(f"/admin/payroll/runs/{rid}/approve")
    assert "success=" in resp.headers["location"]
    assert _fresh(db, rid).status == "approved"
    _release(db, None)
    resp = client.post(f"/admin/payroll/runs/{rid}/approve")
    assert "error=" in resp.headers["location"]


def test_policy_tab_and_settings_routes(client, db, make_user):
    admin = _ui_login(client, make_user)
    html = client.get("/admin/policies/payroll").text
    assert "#tab-approval" in html and "گردش تأیید" in html
    for title in svc.DEFAULT_STEP_TITLES:
        assert title in html

    resp = client.post(
        "/admin/policies/payroll/approval-steps",
        data={"title": "ناظر", "approver_user_id": admin["user_id"]},
    )
    assert "success=" in resp.headers["location"]
    resp = client.post(
        "/admin/policies/payroll/approval-steps",
        data={"title": "بی‌مجوز", "approver_user_id": "no-such-user"},
    )
    assert "error=" in resp.headers["location"]
    last = svc.list_settings(db)[-1]
    assert last.title == "ناظر" and last.approver_user_id == admin["user_id"]
    resp = client.post(
        f"/admin/policies/payroll/approval-steps/{last.id}/move", data={"direction": "up"}
    )
    assert "success=" in resp.headers["location"]
    resp = client.post(f"/admin/policies/payroll/approval-steps/{last.id}/delete")
    assert "success=" in resp.headers["location"]


def test_settings_routes_denied_without_permission(client, db, make_user):
    user = make_user(role="user")
    login_as(client, user["national_code"], user["password"])
    before = len(svc.list_settings(db))
    resp = client.post(
        "/admin/policies/payroll/approval-steps", data={"title": "x", "approver_user_id": ""}
    )
    assert resp.status_code in (302, 303, 401, 403)
    db.expire_all()
    assert len(svc.list_settings(db)) == before


# ---------------------------------------------------------------- print / PDF approvals

def _ui_login(client, make_user):
    admin = make_user(role="super_admin")
    assert login_as(client, admin["national_code"], admin["password"]).status_code in (302, 303)
    return admin


def _report_run(db, admin_id, specs, approve=0):
    """لیست محاسبه‌شده با یک فیش، تا گزارش قابل ساخت باشد."""
    from core.payroll.money import D
    from models.payroll import PayrollResult

    _settings(db, specs)
    run = _run(db, status="calculated", month=2)
    db.add(PayrollResult(run_id=run.id, user_id=admin_id, employee_name="کارمند", gross_earnings=D(10),
                         total_deductions=D(0), net_pay=D(10), covered_days=30, month_days=30))
    db.commit()
    svc.snapshot_run(db, run)
    db.commit()
    rid = run.id
    for _ in range(approve):
        run_service.approve_run(db, rid, admin_id)
    db.rollback()
    return rid


def _report_html(client, rid):
    resp = client.post(f"/admin/payroll/runs/{rid}/report", data={})
    assert resp.status_code == 200
    return resp.text


def test_print_html_shows_boxes_in_order_with_times_only_for_approved(client, db, make_user):
    admin = _ui_login(client, make_user)
    rid = _report_run(
        db, admin["user_id"], [("الف", admin["user_id"]), ("ب", None), ("ج", None)], approve=1
    )
    html = _report_html(client, rid)
    block = html[html.index('id="reportApprovals"'):]
    assert block.index("الف") < block.index("ب") < block.index("ج")
    assert block.count('class="report-approval-box') == 3
    assert block.count('data-approved="1"') == 1
    assert block.count("report-approval-time") == 1 + 0  # فقط مرحلهٔ تأییدشده (به‌علاوه تعریف CSS در بالا)
    assert "break-inside: avoid" in html and "height: 28mm" in html
    assert "<img" not in block and 'type="file"' not in block
    assert "تاریخ:" not in block and "ساعت:" not in block


def test_print_html_legacy_and_draft_runs(client, db, make_user):
    admin = _ui_login(client, make_user)
    from core.payroll.money import D
    from models.payroll import PayrollResult

    _settings(db, [("الف", None)])
    run = _run(db, status="approved", month=3)
    run.approved_by = admin["user_id"]
    run.approved_at = datetime(2026, 1, 1, 8, 30, tzinfo=timezone.utc)
    db.add(PayrollResult(run_id=run.id, user_id=admin["user_id"], employee_name="ک", gross_earnings=D(1),
                         total_deductions=D(0), net_pay=D(1), covered_days=30, month_days=30))
    db.commit()
    rid = run.id
    db.rollback()
    html = _report_html(client, rid)
    block = html[html.index('id="reportApprovals"'):]
    assert block.count('class="report-approval-box') == 1 and 'data-approved="1"' in block

    draft = _run(db, status="draft", month=4)
    db.add(PayrollResult(run_id=draft.id, user_id=admin["user_id"], employee_name="ک", gross_earnings=D(1),
                         total_deductions=D(0), net_pay=D(1), covered_days=30, month_days=30))
    db.commit()
    did = draft.id
    db.rollback()
    assert 'id="reportApprovals"' not in _report_html(client, did)


def test_signature_boxes_content():
    wf = {"steps": [
        {"title": "حسابدار", "approver_name": "علی", "approved_by_name": "علی", "approved": True,
         "approved_at": datetime(2026, 1, 1, 8, 30, tzinfo=timezone.utc)},
        {"title": "مدیر مالی", "approver_name": "", "approved_by_name": "", "approved": False,
         "approved_at": None},
    ]}
    boxes = svc.signature_boxes(wf, lambda v: "T")
    assert boxes == [
        {"name": "علی", "role": "حسابدار", "time": "T", "approved": True},
        {"name": "مدیر مالی", "role": "", "time": "", "approved": False},
    ]


def _pdf_text_calls(monkeypatch):
    from core.payroll import pdf_run_report as mod

    texts = []
    original = mod.RunReportPDF.cell_rtl

    def spy(self, w, h, text, *a, **k):
        texts.append(str(text))
        return original(self, w, h, text, *a, **k)

    monkeypatch.setattr(mod.RunReportPDF, "cell_rtl", spy)
    return texts


def _pdf_report():
    from core.payroll.money import D
    from web.services.payroll.run_report import ReportLine, ReportPerson, build_run_report

    person = ReportPerson(
        user_id="1", name="الف", membership_code="4", membership_name="ق", department_id=1,
        department_name="مالی", department_sort=1, position_id=1, position_name="ک", gross=D(5),
        deductions=D(0), net=D(5), lines=(ReportLine("DAILY_WAGE", "حقوق", "earning", 10, D(5)),),
    )
    return build_run_report([person], department_totals=False)


def test_pdf_includes_approval_boxes_only_with_real_data(monkeypatch):
    from core.payroll.pdf_run_report import build_run_report_pdf

    texts = _pdf_text_calls(monkeypatch)
    boxes = [
        {"name": "علی رضایی", "role": "حسابدار", "time": "۱۴۰۵/۰۱/۱۱ ۰۸:۳۰", "approved": True},
        {"name": "مدیر مالی", "role": "", "time": "", "approved": False},
    ]
    data = build_run_report_pdf(_pdf_report(), title="گزارش", period_label="1405/01",
                                monochrome=True, approvals=boxes)
    assert data.startswith(b"%PDF")
    assert "تأییدکنندگان" in texts
    assert texts.index("علی رضایی") < texts.index("حسابدار") < texts.index("۱۴۰۵/۰۱/۱۱ ۰۸:۳۰")
    assert texts.index("علی رضایی") < texts.index("مدیر مالی")
    # تنها متن زمان‌دار همان مرحلهٔ تأییدشده است؛ مرحلهٔ تأییدنشده زمانی ندارد
    assert {t for t in texts if ":" in t} == {"۱۴۰۵/۰۱/۱۱ ۰۸:۳۰"}

    texts.clear()
    build_run_report_pdf(_pdf_report(), title="گزارش", period_label="1405/01", monochrome=False)
    assert "تأییدکنندگان" not in texts  # لیست بدون گردش (قدیمی/پیش‌نویس) مثل قبل


def test_pdf_boxes_never_split_and_continue_on_next_page():
    from core.payroll import pdf_run_report as mod

    boxes = [{"name": f"نفر {i}", "role": "مرحله", "time": "", "approved": False} for i in range(40)]
    pdf = mod._render(_pdf_report(), title="گزارش", period_label="1405/01",
                      monochrome=True, page_numbers=False, approvals=boxes)
    assert pdf.page >= 2
    # هر ردیف کامل در صفحه جا شده و از ناحیهٔ قابل چاپ بیرون نزده است
    assert pdf.get_y() <= pdf.page_break_trigger + mod._APPROVAL_GAP + 0.01


def test_pdf_route_returns_pdf_with_workflow(client, db, make_user):
    admin = _ui_login(client, make_user)
    rid = _report_run(db, admin["user_id"], [("الف", admin["user_id"]), ("ب", None)], approve=1)
    resp = client.post(f"/admin/payroll/runs/{rid}/report.pdf", data={})
    assert resp.status_code == 200 and resp.content.startswith(b"%PDF")