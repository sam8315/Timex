"""محاسبهٔ مجدد چند نفر: فیلتر، حفظ نتیجهٔ بقیه، و وضعیت پیش‌نویس."""
from types import SimpleNamespace

from web.services.payroll.run_service import (
    filter_recalc_employees,
    result_ids_to_replace,
    status_after_calculate,
)


def _emp(user_id):
    return (SimpleNamespace(user_id=user_id), None, 30)


def test_missing_selection_keeps_everyone():
    rows = [_emp("a"), _emp("b")]
    assert filter_recalc_employees(rows, None) == rows
    assert result_ids_to_replace(["a", "b"], None) == ["a", "b"]


def test_selection_keeps_only_those_people():
    rows = [_emp("a"), _emp("b"), _emp("c")]
    picked = filter_recalc_employees(rows, ["b", "c", "missing"])
    assert [row[0].user_id for row in picked] == ["b", "c"]


def test_result_outside_selection_is_kept():
    assert result_ids_to_replace(["a", "b", "c"], ["b"]) == ["b"]


def test_partial_calculate_does_not_promote_draft():
    assert status_after_calculate("draft", partial=True) == "draft"
    assert status_after_calculate("calculated", partial=True) == "calculated"
    assert status_after_calculate("draft", partial=False) == "calculated"
