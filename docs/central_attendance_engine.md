# Central Attendance Engine — Architecture & Cross-Consumer Contract

> Phase 6 audit output. Describes existing behavior only; it adds no new business rules.

## 1. Purpose & boundary

`core.attendance_calculator` is the **single source of truth for actual attendance
of one day**: punch pairing, work hours, first/last times, status, warnings,
night-shift detection.

It deliberately does **not** compute:

- required duty / surplus / deficit (Policy layer:
  `web.services.attendance_policy_service.compute_required_minutes_for_range`,
  fallback `DEFAULT_REQUIRED_MINUTES = 440`)
- leave / mission / rest / holiday policy effects (consumer layer)
- summary totals and display rounding (report layer)

No hard-coded duty exists in the engine (`7.20`, `7.33`, `7:20`,
`DAILY_DUTY_HOURS`, `440` are absent — enforced by
`tests/test_cross_consumer_consistency.py::test_pairs_guarantee_and_static_source_of_truth`).

## 2. Production consumers

| Consumer | File | Call site |
|---|---|---|
| `/attendance` (self view) | `web/routes/attendance.py` | line ~234 |
| `/admin/attendance/user/{id}` (admin view) | `web/routes/admin.py` | line ~1211 |
| `/reports/monthly-full` | `core/detailed_monthly_report_v2.py` | line ~350 |

All three import `compute_day_attendance` directly from `core.attendance_calculator`
(identity of the imported function is asserted in the Phase 6 test).

Documented observations (not duplicates, no change made):

- `web.routes.attendance` re-exports `analyze_day_status` /
  `calculate_work_hours`; `web.services.attendance_policy_service.calculate_daily_attendance`
  imports them from there. Its only caller is
  `tests/test_attendance_policy_service.py` (no production route/template).
- Other admin endpoints (`GET /admin/attendance`, `/admin/incomplete`, dashboard
  widgets) keep their own punch queries: different features, out of scope (class F).

## 3. Data contract — `DayAttendanceResult`

Fields: `day`, `main_status`, `main_label`, `main_color`, `is_night_shift`,
`has_sequence_error`, `sequence_error_detail`, `warnings`, `is_friday`,
`is_holiday`, `holiday_title`, `work_hours`, `first_enter`, `last_exit`,
`pairs`, `enter_count`, `exit_count`, `schedule_context`;
properties: `status`, `warning_codes`,
`attendance_status_dict` = the 7 legacy keys
(`main_status`, `main_label`, `main_color`, `warnings`, `is_friday`,
`is_holiday`, `holiday_title`) returned by the pre-migration
`analyze_day_status`.

Technical statuses (`night_shift`, `complete`, `missing_enter`, `missing_exit`,
`sequence_error`, `no_attendance`, ...) are never translated back from UI text.

## 4. Schedule & context

- Engine reads schedule only through the optional `WorkScheduleContext`
  passed by consumers (it never resolves policy itself).
- All three consumers fetch records with the same month margin (−1 / +2 days)
  so boundary nights are visible as context only: days outside the month are
  never counted in month lists or totals.
- `is_friday` is `gregorian_date.weekday() == 4` in all three consumers —
  same source, therefore cross-consistent (pre-existing convention).

## 5. Night shift (three states + implicit times)

1. first exit earlier than first enter on the same day (morning exit of a
   night that started before midnight),
2. more enters than exits and the **next** day's first punch is an exit
   (exit moves to implicit `23:59:59`),
3. more exits than enters and the **previous** day's last punch is an enter
   (enter moves to implicit `00:00:00`).

The state machine lives only in the engine; consumers only supply
prev/next-day records.

## 6. Pairs & rounding

- Engine guarantee: `sum(pair['hours']) == work_hours` (hours are raw
  `seconds / 3600.0`, never rounded).
- `MAX_PAIRS = 3` is a **presentation cap** in the report layer only; work
  hours are always computed from all pairs.
- Day-level `work_hours` is never rounded; rounding exists only in report
  summaries (`round(total, 2)`) and display formatters.

## 7. Display mapping (class A)

- Route views show engine labels directly (`main_label`, warnings).
- The monthly report maps technical status to its own legacy labels in
  `DetailedMonthlyReportGeneratorV2._display_status` (e.g. `night_shift`
  becomes `کامل (خروج فردا)` / `کامل (ورود دیروز)`); label text stays in the
  report layer, technical status drives all logic.
- Routes keep the pre-migration **leave override** (status becomes `leave`);
  when the override flips the night flag they recompute hours with the
  engines own `calculate_work_hours(is_night_shift=False)` fallback.

## 8. Known cross-consumer difference (class F + documented Phase 5 class A)

`1403/01/18 (2024-04-07)` — approved leave on a night-pattern day:

- routes: legacy leave override → `work_hours = 0.0`
- monthly report: central engine value → `6 + 7199/3600` hours

This is preserved route behavior (pre-migration) plus the documented Phase 5
display change; it is **not** an engine regression. Everything else on the
shared seed dataset matches exactly
(`tests/test_cross_consumer_consistency.py`, 4 tests).

## 9. Test inventory

- `tests/test_attendance_calculator.py` — engine unit tests (30)
- `tests/test_attendance_route_regression.py` — `/attendance` before/after (3)
- `tests/test_admin_attendance_central_engine.py` — admin before/after (6)
- `tests/test_monthly_full_central_engine.py` — monthly before/after (10)
- `tests/test_cross_consumer_consistency.py` — Phase 6 cross-consumer (4)

Pre-existing failures unrelated to this work:
`tests/test_attendance_policy_service.py` (19) and
`tests/test_admin_travel_leave_preview_route.py` (1) — plus the known
time-flaky `tests/test_session_security.py::test_session_token_rejects_tampering`
(itsdangerous timestamp-dependent tamper check, ~1/40 runs).
