"""Tests for in-process relative study expiry scheduler."""
from datetime import date, timedelta

import pytest

from web.jobs import relative_study_expiry as job
from web.services.employee_relative_service import create_relative


@pytest.fixture(autouse=True)
def _stop_scheduler_after():
    yield
    job.stop_scheduler(timeout=2.0)


def test_run_once_expires_ended_study(db, make_user):
    user = make_user(role="user", balance_al=None)
    past = create_relative(
        db,
        user_id=user["user_id"],
        first_name="گذشته",
        last_name="تحصیل",
        relationship_type="CHILD",
        is_studying=True,
        study_end_date=date.today() - timedelta(days=1),
        status="VERIFIED",
        created_by="admin1",
    )
    future = create_relative(
        db,
        user_id=user["user_id"],
        first_name="آینده",
        last_name="تحصیل",
        relationship_type="CHILD",
        is_studying=True,
        study_end_date=date.today() + timedelta(days=5),
        status="VERIFIED",
        created_by="admin1",
    )

    updated = job.run_once(db)
    assert updated == 1
    db.refresh(past)
    db.refresh(future)
    assert past.is_studying is False
    assert past.status == "VERIFIED"
    assert future.is_studying is True


def test_start_scheduler_disabled_by_env(monkeypatch):
    monkeypatch.setenv("RELATIVE_STUDY_EXPIRY_ENABLED", "0")
    assert job.start_scheduler() is False
    assert job.is_scheduler_running() is False


def test_start_scheduler_enabled_starts_thread(monkeypatch):
    monkeypatch.setenv("RELATIVE_STUDY_EXPIRY_ENABLED", "1")
    monkeypatch.setenv("RELATIVE_STUDY_EXPIRY_INTERVAL_SECONDS", "3600")
    # Avoid hitting DB from the background thread during the test.
    monkeypatch.setattr(job, "run_once", lambda db=None: 0)

    assert job.start_scheduler() is True
    assert job.is_scheduler_running() is True
    # Second start is a no-op while running.
    assert job.start_scheduler() is False

    job.stop_scheduler(timeout=2.0)
    assert job.is_scheduler_running() is False
