"""قفل محاسبه: پیام هم‌زمانی و رد شدن درخواست دوم."""
from unittest.mock import MagicMock

from web.services.payroll.run_service import (
    _ACQUIRE_CALCULATION_SQL,
    calculation_busy_message,
    try_acquire_calculation,
)


def test_creator_hears_that_the_other_user_is_calculating():
    text = calculation_busy_message(
        requester_id="creator",
        creator_id="creator",
        holder_id="other",
        holder_label="کاربر — حسابدار",
    )
    assert text == "لیست در حال محاسبه از طرف کاربر — حسابدار است"


def test_same_user_second_request_says_calculation_is_unfinished():
    text = calculation_busy_message(
        requester_id="creator",
        creator_id="creator",
        holder_id="creator",
        holder_label="سازنده — حسابدار",
    )
    assert text == "محاسبه این لیست هنوز تمام نشده است"


def test_other_user_hears_that_the_creator_is_calculating():
    text = calculation_busy_message(
        requester_id="other",
        creator_id="creator",
        holder_id="creator",
        holder_label="سازنده — مدیر ارشد",
    )
    assert text == "لیست در حال محاسبه از طرف سازنده — مدیر ارشد است"


def test_second_acquire_changes_no_row():
    db = MagicMock()
    result = MagicMock()
    result.first.return_value = None
    db.execute.return_value = result

    assert try_acquire_calculation(db, 7, "bob") is False

    statement, params = db.execute.call_args[0]
    sql = str(statement)
    assert "calculating_by IS NULL" in sql
    assert "status IN ('draft', 'calculated')" in sql
    assert sql.strip() == _ACQUIRE_CALCULATION_SQL.strip()
    assert params == {"uid": "bob", "id": 7}
    db.commit.assert_called_once()


def test_first_acquire_wins_when_update_returns_a_row():
    db = MagicMock()
    result = MagicMock()
    result.first.return_value = (7,)
    db.execute.return_value = result

    assert try_acquire_calculation(db, 7, "alice") is True
    db.commit.assert_called_once()
