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
- `tests/test_monthly_v1_central_engine.py` — Phase 7 گزارش کنسولی v1 (7)
- `tests/test_attendance_analyzer_central_engine.py` — Phase 7 ثبت یافته‌ی
  تحلیلگر و پین قرارداد فعلی آن (3)

Pre-existing failures unrelated to this work:
`tests/test_attendance_policy_service.py` (19) and
`tests/test_admin_travel_leave_preview_route.py` (1) — plus the known
time-flaky `tests/test_session_security.py::test_session_token_rejects_tampering`

---

# Phase 7 — Repository-wide attendance source audit

هدف: پاسخ به این پرسش که آیا **همه‌ی** مسیرهای فعال attendance از داده‌ی
مرکزی استفاده می‌کنند یا نه. این Phase یک audit تمام‌مخزن بود، به‌علاوه‌ی
انتقال هر مصرف‌کننده‌ی فعالی که خودش Actual Attendance را حساب می‌کرد.

## 10. طبقه‌بندی یافته‌ها

| فایل | نقش | دسته |
|---|---|---|
| `core/attendance_calculator.py` | موتور مرکزی | A |
| `web/routes/attendance.py` | `/attendance` | A |
| `web/routes/admin.py` (`:1211`) | `/admin/attendance/user/{id}` | A |
| `core/detailed_monthly_report_v2.py` | `/reports/monthly-full` | A |
| `core/detailed_monthly_report.py` | گزارش کنسولی (v1) | **E → منتقل شد** |
| `core/attendance_analyzer.py` | تحلیلگر تردد کنسولی | **E → ثبت‌شده** |
| `core/daily_status_manager.py` | گزارش وضعیت روزانه/ماهانه | **E → ثبت‌شده** |
| `core/time_calculator.py` | تفکیک صبح/عصر/شب | C (breakdown، نه Actual Work) |
| `core/excel_detailed_export_v2.py` | قالب‌بندی Excel | C |
| `core/pdf_detailed_export_v2.py` | قالب‌بندی PDF | C |
| `core/analytical_report.py` | گزارش تحلیلی | B/C (فقط `calculate_shift_hours`) |
| `web/routes/admin.py` (`/admin/incomplete`) | اسکن bulk ناهنجاری | D (feature متفاوت، بدون محاسبه ساعت) |
| `web/services/attendance_policy_service.py` | Policy | B |

## 11. انتقال انجام‌شده: `core/detailed_monthly_report.py`

این ماژول یک **موتور دومِ فعال** بود. مسیر مصرف:

    main.py → ui.console.ConsoleUI → _show_detailed_monthly_report
           → core.detailed_monthly_report.DetailedMonthlyReportGenerator
           → core/excel_detailed_export_v2.py / core/pdf_detailed_export_v2.py

منطق حذف‌شده: `_calculate_day_work_hours`،
`_calculate_total_work_hours` (pairing مستقل)، و `get_attendance_status`
(وضعیت مستقل).

جایگزین: `_compute_day_actual` که فقط
`compute_day_attendance(...)` را صدا می‌زند، به‌علاوه‌ی `_display_status`
که نگاشت **نمایشی** وضعیت فنی موتور به labelهای قبلی همین گزارش است.
گرد کردن ساعت (`round(..., 2)`) در لایه‌ی گزارش باقی ماند؛ خودِ موتور هرگز
گرد نمی‌کند. Query رکوردها حاشیه‌ی `-1 / +2` روز گرفت (context شیفت شب) و
روزهای بیرون از ماه فقط context موتور ماندند.

### تفاوت رفتار (Before/After) — ۴ روز، و موتور دوم در هر چهار مورد اشتباه می‌کرد

| تاریخ | v1 قدیمی | موتور مرکزی | چرا قدیمی اشتباه بود |
|---|---|---|---|
| 2024-03-20 | `0.0` «بدون تردد» | `6.0` `night_shift` | پیش از «حالت ۳» بی‌دلیل `exits[1:]` می‌کرد |
| 2024-03-26 | `17.0` «کامل(ورود سیستمی)» | `0.0` `missing_enter` | شرط سست «روز قبل ورودی داشته» کافی بود |
| 2024-04-03 | `0.0` «بدون تردد» | `6.0` `night_shift` | همان باگ `exits[1:]` |
| 2024-04-07 | `0.0` «بدون تردد» | `8.0` `night_shift` | شرط `last_exit > first_enter` شبِ «خروج صبح + ورود شب» را از دست می‌داد |

هر چهار مورد با `EXPECTED_STATUS` تثبیت‌شده در
`tests/test_attendance_route_regression.py` (نتیجه‌ی Phase 3) هم‌خوان‌اند.
یعنی این انتقال صرفاً بازچینش نبود؛ یک موتور دومِ واقعاً نادرست کنار گذاشته شد.

## 12. یافته‌های ثبت‌شده (عمداً منتقل نشدند)

### 12.1 `core/attendance_analyzer.py` — مانع ساختاری

`get_user_attendance_range` ساعت کارکرد را مستقل حساب می‌کند
(`:322`). **اما** «روز» در آن تابع روز تقویمی نیست: هر شیفت با
`'date': pending_in.timestamp.date()` کلید می‌خورد، یعنی **روزِ ورود**، و
کل ساعت شیفت به همان روز نسبت داده می‌شود.

موتور مرکزی برعکس است: روز تقویمی، و کارکردِ شیفت شبانه بین دو روز تقسیم
می‌شود. روی شیفت مرزی `2024-03-19 22:00 → 2024-03-20 06:00`:

    تحلیلگر (فعلی) : یک ردیف برای 2024-03-19 با 8.0 ساعت
    موتور مرکزی    : 2024-03-19 → 1.99972 ساعت
                     2024-03-20 → 6.0 ساعت

مهاجرت مستقیم باعث می‌شد حدود ۶ ساعت از `summary.total_work_hours` حذف شود
و ردیف‌های روز در خروجی کنسول جابه‌جا شوند — یعنی **تغییر ظاهر گزارش**.
این نیازمند تصمیم محصولی درباره‌ی semantics نسبت‌دادن شیفت به روز است و
خارج از محدوده‌ی یک audit/migration است. طبق قانون «تغییر غیرمنتظره»،
اینجا ثبت و pin شد (`tests/test_attendance_analyzer_central_engine.py`)
تا مهاجرت احتمالی بعدی آگاهانه باشد، نه خاموش.

بخش‌هایی که در همین ماژول «محاسبه تردد» **نیستند** و عمداً دست‌نخورده
ماندند: نمایش رکورد خام، تاکسونومی خطا در سطح رکورد
(`consecutive_in` / `exit_without_in` / `missing_exit`)، و
`calculate_night_hours` که یک breakdown با پنجره‌ی ثابت ۲۲:۰۰–۰۶:۰۰ است
(همان دسته‌ی `core.time_calculator`).

### 12.2 `core/daily_status_manager.py` — هنوز منتقل نشده

موتور چهارم. `get_daily_report` (`:315`، `:335`، `:339`، `:355`، `:381`،
`:405`)، `get_monthly_report` (`:502`) و `get_daily_details_for_month`
(`:613`) هرکدام ساعت کارکرد را مستقل حساب می‌کنند. مسیر مصرف فعال:

    main.py → ui.console.ConsoleUI (۳ نقطه)  → core.daily_status_manager
           → core/report_generator.py → ui.console.py (۶ نقطه)
                                          → debug_leave_report.py

برخلاف تحلیلگر، این ماژول **روز-تقویمی** است و از نظر semantics با موتور
مرکزی هم‌راستاست، پس مهاجرت آن از نظر معماری شدنی است. اما سه متد
مستقل، هشت نقطه‌ی محاسبه، صفر تست موجود، و رندر کنسولی بدون پوشش تست
آن را به یک کار جداگانه تبدیل می‌کند. طبق قانون «توقف در پایان هر Phase» و
«اگر برای ادامه‌ی Phase لازم نیست، دست‌نخورده بگذار»، در این Phase اعمال
نشد و به‌عنوان **کار باز** ثبت شد.

## 13. Exportها

`core/excel_detailed_export_v2.py` و `core/pdf_detailed_export_v2.py`
هیچ محاسبه‌ای انجام نمی‌دهند: هر دو فقط `report: Dict` را می‌گیرند و قالب
می‌سازند (`fmt_time` / `fmt_hours` / `self._fmt_hours`). هیچ `/3600` و هیچ
pairing در آن‌ها نیست. جریان داده:

    Report Generator  →  Central Actual Attendance  →  Excel / PDF

نه برعکس. `ui/console.py:4895/4901/5057/5062/5480/5485/5658/5663` فقط
دیکشنری آماده را به exporter می‌دهد.

## 14. مسیرهای export در وب وجود ندارند

بررسی مجدد `web/routes/reports.py`: تنها `GET /reports/monthly-full` (`:455`)
و `POST /reports/monthly-full` (`:491`) وجود دارد. مسیرهای
`/reports/monthly-full/export-excel` و `/reports/monthly-full/export-pdf`
**وجود ندارند** و طبق دستور این Phase **اضافه نشدند** — یک issue
پیشین و نامرتبط.

## 15. `core/time_calculator.py`

`calculate_shift_hours(first_enter, last_exit)` فقط تفکیک صبح/عصر/شب را
می‌دهد و **مجموع** کارکرد واقعی از آن نمی‌آید. شواهد:

- `core/detailed_monthly_report_v2.py:382` و
  `core/detailed_monthly_report.py` (پس از انتقال) مقدار `work_hours` را
  مستقیماً از `DayAttendanceResult.work_hours` می‌گیرند، و
  `calculate_shift_hours` فقط برای ستون‌های تفکیکی کنارش صدا زده می‌شود.
- `core/analytical_report.py` هم فقط همین را برای breakdown صدا می‌زند.

پس حذف نشد و دست‌نخورده ماند؛ درستی نتیجه این است که *مجموع* کارکرد
همیشه از موتور مرکزی می‌آید.

## 16. وضعیت source-of-truth پس از Phase 7

**Web (سطح محصول):** کامل. هر سه مسیر وب از `compute_day_attendance`
استفاده می‌کنند.

**کنسول دستگاه (`ui/console.py`):** جزئی. گزارش تفصیلی ماهانه‌ی v1 منتقل
شد؛ `core/attendance_analyzer.py` و `core/daily_status_manager.py` هنوز
موتور مستقل دارند (بخش ۱۲).

یعنی معیار «همه‌ی مصرف‌کننده‌های فعال روی موتور مرکزی» برای **وب** برقرار
است ولی برای **کنسول** هنوز کامل نیست. این باقی‌مانده صریح و مستند است و
کار بعدی مشخص دارد.
(itsdangerous timestamp-dependent tamper check, ~1/40 runs).
