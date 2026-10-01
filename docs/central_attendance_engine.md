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
  `calculate_work_hours` for backwards compatibility (**KEEP** — see §21).
  `web.services.attendance_policy_service.calculate_daily_attendance` also uses
  them, but since **Phase 8** it imports them from `core.attendance_calculator`
  directly (no longer via `web.routes`); the re-export objects are identical, so
  behaviour is unchanged. Its only caller is
  `tests/test_attendance_policy_service.py` (no production route/template).
- `core/detailed_monthly_report.py` (console monthly report v1) is a fourth
  consumer, migrated in Phase 7 (see §11).
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

**Central Engine / shared day contract (all consumers):**
- Day-level `work_hours` from the engine is always **raw**
  (`seconds / 3600.0`, no day-level round).

**Monthly-full v2** (`core/detailed_monthly_report_v2.py` — `/reports/monthly-full`):
- Day rows keep that raw engine value (no `round(..., 2)`).
- Monthly summary (`total_work_hours`, …) aggregates exact daily values, then
  quantizes **once** to the nearest minute via
  `_minutes_to_hours(_hours_to_minutes(sum(...)))`.
  Example: `109.5075 h → 6570.45 min → 6570 min → 109.5 h → 109:30`.
- v2 display formatters (`H:MM` / PDF / Excel for monthly-full) use the same
  minute rule. This is **not** `round(total, 2)`.

**Console monthly report v1 / legacy** (`core/detailed_monthly_report.py`):
- Still applies `round(..., 2)` in the report layer (day `work_hours` and
  summary totals). That legacy behavior is intentional and separate from
  monthly-full v2; do not conflate the two contracts.

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
- `tests/test_monthly_full_exports.py` — Phase 9 خروجی‌های monthly-full:
  Print / PDF / Excel (22)

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
در همین گزارش **کنسولی v1 / legacy**، گرد کردن ساعت با `round(..., 2)` در
لایه‌ی گزارش باقی ماند (روز و summary)؛ خودِ موتور هرگز گرد نمی‌کند.
این با قرارداد monthly-full v2 (nearest-minute روی summary) یکی نیست.
Query رکوردها حاشیه‌ی `-1 / +2` روز گرفت (context شیفت شب) و روزهای بیرون
از ماه فقط context موتور ماندند.

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

از Phase 9، هر دو exporter یک آرگومان اختیاری `output` می‌پذیرند: اگر داده
شود، خروجی در همان stream نوشته می‌شود (مسیر وب)؛ در غیر این صورت مثل قبل
در `output_dir` ذخیره می‌شود (مسیر کنسول). ساخت پوشهٔ خروجی فقط هنگام
ذخیرهٔ واقعی فایل انجام می‌شود، بنابراین درخواست‌های وب هیچ فایلی روی دیسک
نمی‌نویسند.

## 14. مسیرهای export در وب

**Phase 9 وضعیت جدید:** تمپلیت `admin/report_monthly_full.html` از پیش لینک
`دانلود اکسل` و `دانلود PDF` را به
`/reports/monthly-full/export-excel` و `/reports/monthly-full/export-pdf`
می‌داد، ولی هیچ‌کدام از این دو مسیر در `web/routes/reports.py` وجود نداشت؛
یعنی هر دو دکمهٔ دانلود ۴۰۴ می‌دادند. این یک نقص واقعیِ لایهٔ خروجی بود
(قابل اثبات از خود مخزن) و در این Phase رفع شد.

هر دو مسیر اکنون وجود دارند و دقیقاً همان سطح دسترسی گزارش پایه را دارند:

    require_admin + enforce_permission('view_reports')

جریان دادهٔ هر چهار خروجی — یکسان:

    DetailedMonthlyReportGeneratorV2.generate_detailed_report(...)
        →  Central Attendance Engine (Actual Work)
        →  Policy/Schedule Engine (Required Work)
        →  report dict
              ├── Screen / Print   : admin/report_monthly_full.html
              ├── PDF               : core/pdf_detailed_export_v2.py
              └── Excel             : core/excel_detailed_export_v2.py

`web/routes/reports.py::_monthly_full_report_data` تنها نقطهٔ ورود مشترک
است: هر درخواست export دقیقاً **یک بار** گزارش می‌سازد (تست
`test_exports_use_single_report_generation`) و exporterها فقط قالب‌بندی
می‌کنند. **هیچ خروجی‌ای attendance را دوباره محاسبه نمی‌کند.**

دو نکتهٔ صحت که در این Phase در لایهٔ export اصلاح شد:

- برچسب‌های «اضافه کاری روزانه (مبنای 7:20)» / «کسری کار (مبنای 7:20)»
  در Excel و «اضافی (7:20)» در PDF حذف شد؛ مبنای اضافه/کسری، موظفی هر
  روز از Policy/Schedule است و مقدار ثابت نیست.
- شیت خلاصهٔ اکسل و خلاصهٔ PDF اکنون `مأموریت` و `تعطیل کاری (ساعت)` را
  هم گزارش می‌کنند؛ پیش‌تر این دو مقدارِ موجود در صفحه در خروجی‌ها نبود.

نام فایل دانلود: بخش `filename="..."` فقط ASCII است (هدر HTTP|latin-1)، و
نام فارسی کامل از راه `filename*=UTF-8''` منتقل می‌شود.

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

---

# Phase 8 — Architecture Hardening, Contract & Regression

هدف: جلوگیری از اینکه در آینده دوباره موتور دومی ساخته شود یا لایه‌ها دوباره
به هم وابسته شوند. این Phase عمدتاً **نگهبان** اضافه می‌کند، نه رفتار تازه.

## 17. قرارداد داده (تثبیت‌شده)

`DayAttendanceResult` — قرارداد پایدار:

| گروه | فیلدها |
|---|---|
| وضعیت | `main_status` / `status`، `main_label`، `main_color` |
| شیفت شب | `is_night_shift` |
| ناهنجاری | `has_sequence_error`، `sequence_error_detail`، `warnings` / `warning_codes` |
| کارکرد واقعی | `work_hours`، `first_enter`، `last_exit`، `pairs` |
| شمارش | `enter_count`، `exit_count` |
| پرچم | `is_friday`، `is_holiday`، `holiday_title` |
| context | `schedule_context` (فقط برگردانده می‌شود) |
| سازگاری | `attendance_status_dict` (۷ کلید `analyze_day_status` قدیمی) |

API اصلی: `compute_day_attendance(day, day_records, prev_day_records,
next_day_records, is_friday, holiday_title, schedule_context)`.

**این Phase هیچ تغییری در API نداد** — نیازی نبود.

## 18. قاعده‌ی دقیق درب‌های ضمنی شیفت شب

این قاعده ظریف است و اکنون صریحاً قفل شده
(`tests/test_central_engine_contracts.py`):

| وضعیت | ورود واقعی | خروج واقعی | نتیجه |
|---|---|---|---|
| state 1 | هر دو | هر دو | هر دو **واقعی** می‌مانند؛ درب ضمنی فقط داخل `pairs` است |
| state 2 | فقط ورود | ندارد | خروج ضمنی `23:59:59` |
| state 3 | ندارد | فقط خروج | ورود ضمنی `00:00:00` |

روز غیرشیفت شب **هیچ** درب ضمنی نمی‌گیرد (`missing_exit` → `last_exit is None`).

## 19. جداسازی Pairs از Actual Work

`MAX_PAIRS = 3` یک سقف **نمایشی** در لایه‌ی گزارش است و فقط روی
`attendance_pairs` اثر دارد. `work_hours` همیشه از *همه* pairها می‌آید و:

    sum(pair['hours']) == work_hours        (در هر وضعیتی)

**باگی که در Phase 8 پیدا و رفع شد:** در
`core/detailed_monthly_report_v2.py` تفکیک صبح/عصر/شب از
`attendance_pairs[-1]['exit']` گرفته می‌شد — یعنی از لیستِ **سقف‌خورده**.
برای روزی با ۵ بازه، تفکیک تا `13:00` محاسبه می‌شد نه تا `17:00`.
حالا تفکیک از مرزهای کامل موتور می‌آید و `attendance_pairs` همچنان
سقف‌خورده می‌ماند (بدون تغییر UI). Regression test دارد که با بازگرداندن
باگ، قطعاً می‌شکند (به‌صورت تجربی تأیید شد).

## 20. دقت خام

موتور ثانیه‌ی خام را نگه می‌دارد. مثال قفل‌شده: `۳۰ ثانیه → 30/3600
= 0.008333…` و **نه** `0.01`. گرد کردن فقط در لایه‌ی گزارش/نمایش است و
بسته به مصرف‌کننده فرق دارد:

- **monthly-full v2:** روز = raw؛ summary = nearest-minute quantization
  (`_hours_to_minutes` / `_minutes_to_hours`)؛ نمایش `H:MM` همان قاعده.
- **مسیرهای `/attendance` و admin:** روز = raw؛ نمایش با `format_hours_hhmm`
  (دقیقه‌ای).
- **گزارش کنسولی v1 / legacy:** `round(..., 2)` در لایه‌ی همان گزارش v1.

## 21. مرزبندی لایه‌ها و جهت وابستگی

قاعده: `web → core` مجاز، `core → web` نامطلوب.

**اصلاح‌شده در Phase 8:** `web/services/attendance_policy_service.py` از
`web.routes.attendance` تابع `analyze_day_status` و `calculate_work_hours`
را import می‌کرد (یعنی `services → routes`، و در نتیجه
`core → web → web.routes` که ریسک چرخه داشت). حالا مستقیم از
`core.attendance_calculator` می‌گیرد. چون re-export صرفاً همان شیء تابع
است (هویت با تست اثبات شده)، **هیچ تغییر رفتاری** رخ نداد.

**استثناهای باقی‌مانده (pin شده‌اند تا بی‌سروصدا بزرگ نشوند):**

| فایل | وابستگی |
|---|---|
| `core/detailed_monthly_report_v2.py` | `web.services.{attendance_policy, hourly_leave, hourly_mission}` |
| `core/raw_report.py` | `web.services.{hourly_mission, travel_leave}` |

این‌ها لایه‌ی Policy را از `web/services` می‌گیرند. جابه‌جایی آن‌ها یک
refactor بزرگ است و در این Phase انجام نشد؛ اما با تست
`test_no_core_module_imports_web_except_known_exceptions` قفل شده‌اند.

**re-exportهای legacy حفظ شدند (KEEP):** `web/routes/attendance.py` همچنان
`analyze_day_status` و `calculate_work_hours` را re-export می‌کند و
هویتشان با همان توابع موتور تست می‌شود. حذف‌شان backward compatibility را
می‌شکست.

## 22. استثناهای معماری (بدون تغییر)

### 22.1 `core/attendance_analyzer.py` — استثنای قطعی

`shift-based` است: هر شیفت با `'date': pending_in.timestamp.date()`
(یعنی **روزِ ورود**) کلید می‌خورد و کل ساعت شیفت به آن روز نسبت داده
می‌شود. Central Engine روز-تقویمی است و شیفت شب را بین دو روز تقسیم
می‌کند.

| شیفت مرزی | تحلیلگر | موتور مرکزی |
|---|---|---|
| `2024-03-19 22:00 → 2024-03-20 06:00` | یک ردیف برای `03-19` با `8.0` | `03-19 → 1.99972` و `03-20 → 6.0` |

مهاجرت مستقیم ~۶ ساعت را از `summary.total_work_hours` حذف می‌کند و ردیف‌های
روز را جابه‌جا می‌کند ⇒ **تغییر UI + تغییر semantics**. نیازمند تصمیم
business-level مستقل. تا آن زمان: **DO NOT MIGRATE / DO NOT DELETE**.

قرارداد فعلی با تست‌هایی pin شده که **عمداً** می‌شکنند اگر کسی بی‌سروصدا
مهاجرت دهد.

### 22.2 `core/daily_status_manager.py` — مهاجرت به تعویق افتاد

طبقه‌بندی متدها:

| متد | خط | دسته |
|---|---|---|
| `get_status_name` | 69 | C |
| `detect_status` | 73 | B |
| `set_manual_status` | 150 | B |
| `get_daily_report` | 204 | **A** (ساعت در 315/335/337/355/381/405) + B + C |
| `get_monthly_report` | 447 | **A** (502) + B + C |
| `get_bulk_absent_report` | 518 | B |
| `get_daily_details_for_month` | 523 | **A** (613) + B + C |
| `sort_key` / `_get_day_name` / `_get_jalali_month_name` | 436/686/694 | C |

- **فعال:** بله. `main.py → ui.console.ConsoleUI` (۳ نقطه) و
  `core/report_generator.py → ui/console.py` (۶ نقطه) و `debug_leave_report.py`.
- **وابستگی DB:** `Employee`, `User`, `DailyStatus`, `Attendance`,
  `LeaveRequest`, `Contract`, `HolidayManager`, `LeaveManager`,
  `EmployeeManager`، `SessionLocal`.
- **تست:** صفر تست اختصاصی.
- **تصمیم:** **DEFER.** برخلاف تحلیلگر، این ماژول روز-تقویمی است و از نظر
  semantics با موتور هم‌راستاست، پس مهاجرت *ممکن* است — ولی سه متد
  مستقل با هشت نقطه‌ی محاسبه، بدون پوشش تست و با رندر کنسولی، ریسک
  بالایی دارد. طبق 8.13، در این Phase اعمال نشد و به‌عنوان **کار باز**
  ثبت شد.

### 22.3 `core/report_generator.py` — pure orchestration

هیچ `/3600` ندارد؛ فقط `DailyStatusManager` را صدا می‌زند و خلاصه می‌سازد
(`monthly['total_work_hours']`). خودش Actual Attendance را حساب نمی‌کند ⇒
**KEEP**.

## 23. Performance audit (اندازه‌گیری‌شده)

برای یک ماه ۳۱ روزه و یک کارمند، تعداد query واقعی گزارش ماهانه:

| جدول | تعداد query | تفسیر |
|---|---|---|
| `attendances` | **1** | ✅ یک بار برای کل ماه — **N+1 ندارد** |
| `attendance_policies` | 62 | N+1 در لایه‌ی Policy (۲× در روز) |
| `holidays` | 31 | N+1 در لایه‌ی Policy (۱× در روز) |
| `leave_requests` | 2 | OK |
| `hourly_missions` | 2 | OK |
| `employee` / `daily_statuses` | 1 / 1 | OK |
| **مجموع** | **100** | |

**نتیجه:** centralization هیچ N+1 در خودِ تردد ایجاد نکرده است. موتور
مرکزی **صفر query** دارد (اثبات‌شده با شمارنده‌ی `before_cursor_execute`)،
بنابراین فراخوانی per-day آن هزینه‌ی DB ندارد. N+1 باقی‌مانده کاملاً در
لایه‌ی **Policy** است که طبق مرزبندی پروژه خارج از Central Engine است و
بهینه‌سازی زودهنگام آن ممنوع. عدد ۱۰۰ pin شده تا تغییر ناخواسته دیده شود.

## 24. تست‌های Phase 8

| فایل | تعداد | موضوع |
|---|---|---|
| `tests/test_central_engine_contracts.py` | 30 | شیفت شب (۳ state)، pairs، دقت خام، مرز ماه |
| `tests/test_central_engine_architecture.py` | 20 | actual-only، بدون موظفی، جهت وابستگی، re-export، export |
| `tests/test_cross_consumer_phase8_contracts.py` | 5 | سقف نمایشی ≠ Actual Work، برابری سه‌گانه |
| `tests/test_central_engine_performance.py` | 4 | صفر query در موتور، خواندن یک‌باره‌ی تردد |
| `tests/test_central_engine_performance_baseline.py` | 2 | اندازه‌گیری و pin خط پایه‌ی query |

Baseline کل بعد از Phase 8: **۱۳۲۷ passed / ۲۰ pre-existing failed**
(Phase 7: ۱۲۶۶ passed / ۲۰ failed) ⇒ **۶۱ تست جدید، صفر regression**.

Pre-existing (تغییری نکرده): `tests/test_attendance_policy_service.py` (۱۹)
و `tests/test_admin_travel_leave_preview_route.py` (۱).
(itsdangerous timestamp-dependent tamper check, ~1/40 runs).

---

# Phase 9 — Final Audit, Cleanup & PR Readiness

هدف: **ممیزی نهایی** بدون افزودن هیچ رفتار تازه. این Phase هیچ تغییر
محتوایی در موتور، مسیرها یا قالب‌ها ایجاد نکرد.

## 25. ممیزی نهایی source-of-truth

جست‌وجوی تمام‌مخزنی روی `analyze_day_status` / `calculate_work_hours` /
`compute_day_attendance` / `work_hours` / `first_enter` / `last_exit` /
`night_shift` / `pairing`. نتیجه: **موتور دومِ فعال در لایه‌ی محصول وجود ندارد.**

| مصرف‌کننده | ماژول / فراخوان | منبع Actual | منبع وضعیت | منبع ساعت |
|---|---|---|---|---|
| `/attendance` | `web/routes/attendance.py:234` | `compute_day_attendance` | موتور + leave-override مسیر | `result.work_hours` |
| `/admin/attendance/user/{id}` | `web/routes/admin.py:1211` | `compute_day_attendance` | موتور + leave-override مسیر | `result.work_hours` |
| `/reports/monthly-full` (v2) | `core/detailed_monthly_report_v2.py:350` | `compute_day_attendance` | موتور → `_display_status` | روز: `work_hours` خام؛ summary: nearest-minute |
| گزارش کنسولی v1 / legacy | `core/detailed_monthly_report.py:244` | `compute_day_attendance` | موتور → `_display_status` | `round(..., 2)` در لایه‌ی گزارش v1 (روز + summary) |

دو مسیر وب پس از leave-override، در صورت تغییر پرچم شیفت شب، از
`calculate_work_hours` خودِ موتور برای بازمحاسبه استفاده می‌کنند (همان تابع،
همان شیء — بدون موتور دوم).

### استثناهای فعال (بدون تغییر)

| ماژول | مصرف‌کننده‌ی فعال | وضعیت |
|---|---|---|
| `core/attendance_analyzer.py` | `ui/console.py` (۱۰ نقطه) و `web/routes/admin.py:2278` (`/admin/incomplete`) | **DO NOT MIGRATE / DO NOT DELETE** (§22.1) |
| `core/daily_status_manager.py` | `ui/console.py`، `core/report_generator.py`، `scripts/debug_attendance.py` | **DEFERRED** (§22.2) |

`/admin/incomplete` فقط از `get_incomplete_attendances` و تاکسونومی خطای
رکوردی استفاده می‌کند و **هیچ ساعت کارکردی محاسبه نمی‌کند**.

## 26. معماری — جهت وابستگی

`web → core` برقرار است. این branch **هیچ وابستگی تازه‌ی `core → web`
اضافه نکرد**: تنها import جدید در `core/`، `core.attendance_calculator`
(هم‌لایه) بود. استثناهای پیشین `core/detailed_monthly_report_v2.py` و
`core/raw_report.py` هر دو روی `work` موجود بودند و دست‌نخورده ماندند
(پین‌شده با `test_no_core_module_imports_web_except_known_exceptions`).

سختیِ باقی‌مانده: `web/routes/admin.py` برای `calculate_work_hours` و ثابت‌های
`STATUS_*` هنوز از re-exportِ `web.routes.attendance` می‌گیرد. این
`web → web` است (مجاز) و **عمداً دست‌نخورده ماند**؛ حذف آن صرفاً برای
زیبایی معماری بود و در محدوده‌ی این Phase نیست.

## 27. re-exportهای legacy

`web/routes/attendance.py` همچنان `analyze_day_status` و
`calculate_work_hours` را re-export می‌کند و همان شیء‌های موتور هستند
(هویت با تست اثبات می‌شود). مصرف‌کننده‌ی باقی‌مانده: `web/routes/admin.py`
(خط ۱۲۳۹، fallback مربوط به leave-override) و تست‌ها. **KEEP** — حذف،
backward compatibility را می‌شکست.

## 28. UI

`git diff work...HEAD -- web/templates/` **خالی است**: صفر تغییر در هیچ
قالبی، از جمله `admin/report_monthly_full.html`. ظاهر monthly-full دست‌نخورده
مانده و متن‌های نمایشی از لایه‌ی گزارش (`_display_status`) می‌آیند.

## 29. تست‌ها

| مجموعه | نتیجه |
|---|---|
| تست‌های موتور و معماری و cross-consumer و performance | **۹۵ passed** |
| تست‌های مهاجرت مصرف‌کننده‌ها (route / admin / monthly-full / v1 / analyzer) | **۲۸ passed, 1 skipped** |
| **کل مخزن** | **۱۳۲۷ passed, ۲۰ failed, 1 skipped** |

۲۰ failure همان ۲۰ failure پیشین‌اند (۱۹ در
`tests/test_attendance_policy_service.py` و ۱ در
`tests/test_admin_travel_leave_preview_route.py`) ⇒ **صفر regression**.
خط پایه در دو اجرای مستقل کامل بازتولید شد.

## 30. امنیت

`work` پایه‌ی `0989330` («Fix hard-coded session secrets (#37)») است و
این branch هیچ‌کدام از `web/app.py`، `web/config.py`، `web/session.py`،
`tests/conftest.py`، `tests/test_session_security.py` یا `.env.example` را
لمس نکرده است. بنابراین تغییرات این branch **هیچ سطحی** از authentication،
authorization، session، CSRF، secret یا admin-access را تغییر نداده ⇒
**بدون regression امنیتی**.

## 31. وضعیت نهایی

نتیجه‌ی ممیزی:

    Actual Attendance  →  یک منبع واحد (core/attendance_calculator)
    Required Work      →  یک منبع واحد (Policy: attendance_policy_service)
    Schedule فرد/گروه  →  حفظ شد (Policy؛ موتور فقط WorkScheduleContext را برمی‌گرداند)
    Night Shift / Month Boundary / Raw Precision  →  حفظ و تست‌شده
    UI                 →  بدون تغییر
    work               →  دست‌نخورده
    regression جدید    →  ندارد
    استثناهای legacy   →  صریحاً مستند (§22.1، §22.2)
