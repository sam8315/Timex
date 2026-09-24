# راهنمای پیاده‌سازی مأموریت ساعتی (Hourly Mission)

> این فایل حافظه بلندمدت پروژه است. مدل بعدی باید با خواندن همین فایل + فایل‌های اشاره‌شده بتواند ادامه کار را بدون بررسی کل گفتگو انجام دهد.
> آخرین به‌روزرسانی: پایان اصلاح معماری فاز ۱ (سیاست‌های scoped).

---

## ۱. هدف قابلیت

افزودن قابلیت **مأموریت ساعتی** به سیستم Timex، **کاملاً مستقل** از:

- مرخصی ساعتی (`LeaveRequest` با `leave_type='HL'`)
- مأموریت روزانه (`DailyStatus` با `status_code='M'`)

مأموریت ساعتی فقط **بخشی از یک روز** را پوشش می‌دهد (شروع/پایان ساعتی دارد)، برخلاف مأموریت روزانه که کل موظفی روز را صفر می‌کند.

---

## ۲. معماری کلی

| لایه | تصمیم |
|------|--------|
| ذخیره‌سازی مأموریت | جدول مستقل `hourly_missions` — **نه** داخل `LeaveRequest` و **نه** داخل `DailyStatus` |
| ذخیره‌سازی سیاست | جدول مستقل `hourly_mission_policies` (scoped: گروه/نوع عضویت + employee override) |
| مدل SQLAlchemy | `models/hourly_mission.py` → `HourlyMission` + `HourlyMissionPolicy` |
| مدت مأموریت | **محاسبه‌شده** (property `duration_minutes`) — ذخیره نمی‌شود |
| resolve سیاست | `web/services/hourly_mission_service.py` — اولویت: override → گروه → default |
| UI سیاست | صفحه اختصاصی `/admin/policies/hourly-mission` (لیست + فرم)؛ کارت لینک‌دار در `/admin/policies` |
| validation/service/route ثبت | **فازهای بعد** |

### چرا DailyStatus نیست؟

`DailyStatus` برای وضعیت‌های روزانه است؛ مأموریت روزانه (`M`) کل موظفی روز را صفر می‌کند، در حالی که مأموریت ساعتی فقط بخشی از زمان روز را پوشش می‌دهد. ترکیب این دو مفهوم در یک جدول باعث شاخه‌شدن پیچیده در محاسبات گزارش می‌شود.

### چرا LeaveRequest نیست؟

`LeaveRequest` مفهوم مرخصی است (days_count، LeaveBalance، تراکنش‌ها). مأموریت ساعتی تعادل مرخصی ندارد و منطق کسری متفاوتی (کسر از موظفی، نه از مرخصی) خواهد داشت.

### چرا policy سراسری (PolicyValue) نیست؟

چهار تنظیم مأموریت ساعتی باید **برای گروه/نوع عضویت و employee override قابل تفکیک** باشند. طراحی قبلی (چهار `PolicyValue` با `region_code=NULL` در category `hourly_mission`) یک policy سراسری مشترک برای تمام کارکنان می‌ساخت و امکان تفکیک نداشت. الگوی موجود مرخصی ساعتی (`HourlyLeavePolicy`) عیناً الگوبرداری شد.

---

## ۳. فازهای پروژه

| فاز | محتوا | وضعیت |
|-----|--------|--------|
| **فاز ۱** | مدل داده + migration + معماری سیاست scoped + UI CRUD + resolve + تست‌ها + همین راهنما | ✅ انجام شد (شامل اصلاح معماری) |
| فاز ۲ | Route ثبت مأموریت ساعتی توسط کاربر + فرم + فراخوانی service validation پایه | ⬜ |
| فاز ۳ | Route تأیید/رد توسط مدیر + سرویس validation کامل (overlap، ساعات موظفی، روز تعطیل) | ⬜ |
| فاز ۴ | اتصال به attendance/گزارش‌ها (اعمال `deduct_from_required_minutes` در محاسبه موظفی مؤثر) | ⬜ |
| فاز ۵ | نوتیفیکیشن + بهبود گزارش‌ها در صورت نیاز | ⬜ |

> ترتیب فازها ممکن است با صلاحدید کاربر تغییر کند؛ اما هر فاز فقط در محدوده خودش کار کند.

---

## ۴. وضعیت فاز فعلی

**فاز ۱ — تکمیل شده (با اصلاح معماری سیاست‌ها).**

انجام شده:

1. فایل راهنما (همین فایل)
2. مدل `HourlyMission` + `HourlyMissionPolicy` در `models/hourly_mission.py`
3. Migration: `database/migrations/006_hourly_mission.sql` (ویرایش‌شده در محل — هرگز push نشده)
4. ثبت مدل‌ها در `models/__init__.py`
5. سرویس resolve: `web/services/hourly_mission_service.py`
6. CRUD کامل سیاست در `web/routes/admin_policy.py` + قالب‌های لیست/فرم
7. کارت لینک‌دار در صفحه `/admin/policies` (فرم سراسری قدیمی حذف شد)
8. بازنویسی تست‌های `tests/test_hourly_mission.py` (۱۶ تست)

انجام **نشده** (عمداً — فازهای بعد): بخش ۱۱.

---

## ۵. تصمیم‌های معماری

### ۵.۱ نام‌گذاری (بررسی شده با convention پروژه)

- **نام نهایی:** `models/hourly_mission.py`
- **کلاس‌ها:** `HourlyMission` → جدول `hourly_missions`؛ `HourlyMissionPolicy` → جدول `hourly_mission_policies`
- دلیل: جدول‌های `employee_*` در این پروژه داده‌های اصلی/صفتی کارمند هستند؛ رکوردهای تراکنشی با نام قابلیت نام‌گذاری می‌شوند: `leave_request`، `daily_status`، `attendance`، `hourly_mission`.

### ۵.۲ وضعیت‌ها (Status)

از همان single-character convention مدل `LeaveRequest` استفاده شد:

| کد | معنی | برچسب فارسی |
|----|------|-------------|
| `P` | pending | در انتظار |
| `A` | approved | تایید شده |
| `R` | rejected | رد شده |
| `D` | cancelled | لغو شده |

نکته: در `LeaveRequest` کد `D` معنای «حذف شده» دارد؛ اینجا «لغو شده» (cancel) پوشش داده می‌شود.

### ۵.۳ فیلدهای مدل HourlyMission

| فیلد | نوع | توضیح |
|------|-----|--------|
| `id` | int PK | |
| `user_id` | String(50) FK → `users.user_id` ON DELETE CASCADE, index | کارمند/کاربر |
| `mission_date` | Date, index | تاریخ مأموریت |
| `start_time` | Time NOT NULL | ساعت شروع |
| `end_time` | Time NOT NULL | ساعت پایان |
| `reason` | Text NULL | علت/توضیح |
| `destination` | String(200) NULL | مقصد (متن ساده) |
| `status` | String(1) default `'P'`, index | P/A/R/D |
| `approved_by` | String(50) NULL | تأییدکننده |
| `approved_at` | DateTime(timezone=True) NULL | زمان تأیید |
| `rejection_reason` | Text NULL | دلیل رد |
| `created_at` / `updated_at` | `TimestampMixin` | مطابق convention کل پروژه |

- رابطه: `user = relationship("User", backref="hourly_missions")`
- **مدت مأموریت ذخیره نمی‌شود** → property `duration_minutes`
- Constraintهای DB:
  - `ck_hourly_missions_time_order` → `CHECK (start_time < end_time)`
  - `ck_hourly_missions_status` → `CHECK (status IN ('P','A','R','D'))`

### ۵.۴ سیاست‌های Scoped (چهار تنظیم)

جدول `hourly_mission_policies` — **آینه‌ای از `hourly_leave_policies`**:

| ستون | نوع | توضیح |
|------|-----|--------|
| `employment_type_code` | String(10) NOT NULL, index | کد نوع عضویت: `1`=رسمی، `2`=وظیفه، `3`=خریدخدمت، `4`=قراردادی، `5`=پزشک |
| `user_id` | String(50) NULL FK → users | اگر ست شده → **Override فقط برای این کاربر**؛ اگر NULL → سیاست **گروه** |
| `effective_from_date` | Date NOT NULL | شروع اعتبار |
| `effective_to_date` | Date NULL | پایان اعتبار (NULL = باز) |
| `is_active` | Boolean default True | حذف نرم (soft delete) |
| `enabled` | Boolean default **True** | مأموریت ساعتی فعال است |
| `working_hours_only` | Boolean default **True** | فقط در ساعات موظفی مجاز |
| `allowed_on_holidays` | Boolean default **False** | در روز تعطیل مجاز |
| `deduct_from_required_minutes` | Boolean default **True** | مدت از موظفی کسر می‌شود |

Index مرکب: `(employment_type_code, effective_from_date)` و `(user_id, effective_from_date)`.

**resolve** (`resolve_hourly_mission_policy` در `web/services/hourly_mission_service.py`):

1. اگر `employee.department` خالی بود → `None` (حتی override هم چک نمی‌شود — عین الگوی hourly leave)
2. **Employee Override:** `user_id == employee.user_id` + `is_active` + بازه تاریخ → `order_by(effective_from_date.desc())`
3. **Employment Type (گروه):** `employment_type_code == department` + `user_id IS NULL` + `is_active` + بازه تاریخ
4. اگر هیچ‌کدام → `None` → `get_effective_hourly_mission_settings` مقدار `DEFAULT_HOURLY_MISSION_SETTINGS` را برمی‌گرداند

```python
DEFAULT_HOURLY_MISSION_SETTINGS = {
    'enabled': True,
    'working_hours_only': True,
    'allowed_on_holidays': False,
    'deduct_from_required_minutes': True,
}
```

**⚠️ قاعده اجباری برای مدل بعدی:**

> سیاست مأموریت ساعتی باید برای گروه/نوع استخدام و employee override قابل تفکیک باشد و هرگز به‌عنوان یک policy global مشترک برای تمام کارکنان resolve نشود.

### ۵.۵ تعریف Holiday در پروژه (برای فازهای بعد — مفهوم جدید نسازید)

تعطیل بودن یک روز از **سه منبع** تشکیل شده (طبق `web/services/attendance_policy_service.py` و `core/holiday_manager.py`):

1. **جمعه** — هفته کاری شمسی: `date.weekday() == 4`
2. **جدول `holidays`** (`models/holiday.py`) — `holiday_date` + `group_id` (NULL = ملی/همه، یا کد گروه عضویت `'1'`..`'5'`)
3. **`AttendancePolicyDay.is_working_day`** — روز غیرکاری در برنامه هفتگی سیاست حضور همان کارمند

سرویس موجود: `resolve_attendance_policy()` + `resolve_policy_day()` از `web/services/attendance_policy_service.py`.

---

## ۶. فایل‌های مرتبط

### فاز ۱ (ایجاد/تغییر — شامل اصلاح معماری)

| فایل | عمل |
|------|-----|
| `docs/hourly_mission_implementation.md` | CREATED/MODIFIED (همین فایل) |
| `models/hourly_mission.py` | CREATED — `HourlyMission` + `HourlyMissionPolicy` |
| `models/__init__.py` | MODIFIED — import + `__all__` هر دو مدل |
| `database/migrations/006_hourly_mission.sql` | CREATED then EDITED in place — جدول‌ها + پاک‌سازی policy سراسری |
| `web/services/hourly_mission_service.py` | CREATED — defaults + resolve + get_effective |
| `web/routes/admin_policy.py` | MODIFIED — حذف ثابت‌های `HOURLY_MISSION_*` و فرم سراسری؛ افزودن CRUD کامل `/admin/policies/hourly-mission` |
| `web/templates/admin/policies.html` | MODIFIED — حذف فرم چهار سوییچ؛ افزودن کارت لینک‌دار |
| `web/templates/admin/policy_hourly_mission.html` | CREATED — صفحه لیست (گروه‌ها + Override‌ها) |
| `web/templates/admin/policy_hourly_mission_form.html` | CREATED — فرم create/edit با چهار form-switch |
| `tests/test_hourly_mission.py` | CREATED then REWRITTEN — ۱۶ تست |

### فایل‌های مرجع (نخوانید مگر نیاز — فقط برای الگو)

| فایل | چرا مهم است |
|------|-------------|
| `models/leave_request.py` | الگوی status code های `P/A/R/D`، فیلدهای تأیید، `to_dict` |
| `models/hourly_leave_policy.py` / `models/attendance.py` (`HourlyLeavePolicy`) | الگوی مستقیم سیاست scoped |
| `web/services/hourly_leave_service.py` | الگوی resolve_hourly_leave_policy + validation مرخصی ساعتی — برای فاز ۲/۳ |
| `web/routes/admin_policy.py` (بخش hourly-leave، خطوط ~۱۲۵۷–۱۶۵۳) | الگوی CRUD صفحه‌محور با overlap check |
| `web/services/attendance_policy_service.py` | `resolve_policy` / `resolve_policy_day` / `time_to_minutes` / تعریف holiday |
| `database/migrations/003_hourly_leave.sql` | الگوی SQL migration |
| `tests/conftest.py` | fixture های `db`, `client`, `make_user`, `login_as`؛ **migration SQL در تست اجرا نمی‌شود** — فقط `create_all` |

---

## ۷. Migrationهای مرتبط

- **شماره:** `006` — `database/migrations/006_hourly_mission.sql`
- **وضعیت:** فقط محلی روی `work` (commit `356ad95` push نشده) → ویرایش مستقیم مجاز بود و انجام شد.
- شامل:
  - `CREATE TABLE hourly_missions` + ۲ CHECK + ۳ index
  - `CREATE TABLE hourly_mission_policies` + FK + ۷ index (شامل ۲ composite)
  - **پاک‌سازی idempotent** طراحی سراسری رها‌شده: `DELETE FROM policy_values WHERE parameter_key IN (چهار کلید hourly_mission_*)` و `DELETE FROM policies WHERE category = 'hourly_mission'`
  - COMMENTهای فارسی
- اجرای migration: دستی با psql (پروژه runner خودکار ندارد).
- **تست‌ها:** SQL migration اجرا نمی‌شود؛ جدول‌ها با `Base.metadata.create_all` ساخته می‌شوند. پس **هر مدل جدید باید در `models/__init__.py` import شود**.

---

## ۸. سیاست‌ها — جایگزین Policy keyهای سراسری

### ❌ حذف‌شده (طراحی قدیمی فاز ۱ قبل از اصلاح)

```
category = hourly_mission
├── hourly_mission_enabled
├── hourly_mission_working_hours_only
├── hourly_mission_allowed_on_holidays
└── hourly_mission_deduct_from_required_minutes
```

- ثابت‌های `HOURLY_MISSION_POLICY_CATEGORY`, `HOURLY_MISSION_PARAM_KEYS`, `HOURLY_MISSION_DEFAULTS`, `HOURLY_MISSION_PARAM_NOTES` از `web/routes/admin_policy.py` **حذف شدند**.
- helper `_hourly_mission_flag_values` و context `hourly_mission` در GET `/admin/policies` **حذف شدند**.
- POST سراسری چهار فیلد در `/admin/policies` **حذف شد**.
- فرم چهار سوییچ در `policies.html` **حذف شد** (جایگزین: کارت لینک‌دار).

### ✅ جایگزین

- جدول `hourly_mission_policies` (بخش ۵.۴)
- خواندن: `resolve_hourly_mission_policy` / `get_effective_hourly_mission_settings` از `web/services/hourly_mission_service.py`
- ذخیره در UI: POST `/admin/policies/hourly-mission/save` و `/{policy_id}/update` (فقط `super_admin` + permission `manage_users`)
- **فرم‌ها:** هر چهار فیلد checkbox با `Form("off")` (نه `Form("on")`)؛ چون checkbox فقط هنگام checked ارسال می‌شود؛ وضعیت اولیه UI توسط template کنترل می‌شود:
  - `enabled` / `working_hours_only` / `deduct_from_required_minutes`: `{% if not policy or policy.X %}checked{% endif %}`
  - `allowed_on_holidays`: `{% if policy and policy.allowed_on_holidays %}checked{% endif %}`
  - مقدار checked = `"on"`؛ مقایسه در route: `value == 'on'`
- **حذف soft:** POST `/{policy_id}/delete` → `is_active = False`
- **overlap:** هنگام save/update، بررسی همپوشانی بازه تاریخی برای همان scope (گروه یا همان user override)

---

## ۹. تست‌های انجام‌شده و نتیجه

اجرای تست: `.venv\Scripts\python.exe -m pytest` از ریشه (PowerShell — بدون head/tail).

| دستور / محدوده | نتیجه |
|----------------|--------|
| `pytest tests/test_hourly_mission.py` (۱۶ تست، **ایزوله**) | ✅ **16 passed** (~5s) |
| `pytest tests/test_policy.py tests/test_daily_status.py tests/test_hourly_leave_integration.py` روی درخت تمیز (git stash) | ⚠️ **15 failed, 50 passed** — شکست‌ها **pre-existing** ناشی از آلودگی DB مشترک بین تست‌ها |
| `pytest` کل suite | ⚠️ ۲۱ تست ناموفق pre-existing شناخته‌شده (بخش زیر) |

### تست‌های `tests/test_hourly_mission.py` (۱۶)

- ثبت مدل‌ها در `Base.metadata` + export از `models`
- ساخته‌شدن هر دو جدول در دیتابیس تست (create_all)
- ساخت + خواندن رکورد مأموریت + `duration_minutes` / `status_name` / timestamps
- رد `start_time >= end_time` و status نامعتبر با `IntegrityError`
- چهار کد وضعیت P/A/R/D
- resolve: گروه بدون override؛ override برندهٔ گروه؛ عدم اثر override کاربر دیگر؛ fallback به default
- چهار گزینه مستقل در ذخیره/بازخوانی
- رندر کارت در `/admin/policies` (+ نبود فرم/کلیدهای قدیمی)
- رندر صفحه لیست با scopeها + دکمه افزودن
- رندر فرم با چهار switch
- ذخیره HTTP با گزینه‌های مستقل (checkbox خاموش → False)
- 403 برای غیر super_admin

### ⚠️ شکست‌های pre-existing (غیرمرتبط)

تعدادی از تست‌های `test_policy.py` / `test_daily_status.py` / `test_hourly_leave_integration.py` در **اجرای ترکیبی** به‌دلیل آلودگی `timex_test_db` (StaleDataError / 307 / ObjectDeletedError) شکست می‌خورند؛ حتی با `git stash` روی درخت تمیز هم تکرار می‌شوند. **تست فاز ۱ باید ایزوله اجرا شود.**

### ⚠️ درس مهم: هرگز دو دستور pytest موازی علیه یک DB

دو پروسه pytest همزمان روی `timex_test_db` باعث StaleDataError، DeadlockDetected، ریدایرکت‌های 307 کاذب و نتایج false-positive می‌شود. **همیشه سریال.**

### ⚠️ ۲۱ تست ناموفق کل suite — از قبل موجود

- `tests/test_attendance_policy_service.py` — ۱۹ تست
- `tests/test_admin_travel_leave_preview_route.py` — ۱ تست
- `tests/test_travel_leave_attendance.py` — ۱ تست

---

## ۱۰. نکات مهم برای مدل بعدی

1. **این فایل را اول بخوان.** بعد فقط فایل‌های بخش ۶ را باز کن؛ پروژه را از صفر نگرد.
2. اجرای تست: `.venv\Scripts\python.exe -m pytest` از ریشه. **هرگز دو pytest موازی** ( آلودگی DB مشترک).
3. **شاخه کاری:** `work` — commit فاز ۱: `Add hourly mission data model and policies`.
4. **سیاست مأموریت ساعتی باید برای گروه/نوع استخدام و employee override قابل تفکیک باشد و هرگز به‌عنوان یک policy global مشترک برای تمام کارکنان resolve نشود.**
5. هنگام افزودن route ثبت/تأیید در فاز ۲+:
   - اول `enabled` را از `get_effective_hourly_mission_settings(db, employee, date)` بگیر (false → جلوی ثبت را بگیر).
   - از `resolve_attendance_policy` + `resolve_policy_day` برای ساعات موظفی استفاده کن (کپی نکن) — فقط اگر `working_hours_only` True بود.
   - اگر `allowed_on_holidays` False بود، روز تعطیل را رد کن (الگوی سه‌گانه holiday در بخش ۵.۵).
   - overlap را روی `hourly_missions` همان `user_id` + `mission_date` با status در `('P','A')` بسنج (الگو: overlap مرخصی ساعتی در `hourly_leave_service`).
   - هرگز در `LeaveRequest` یا `DailyStatus` رکورد مأموریت ساعتی نساز.
6. UI: از Bootstrap/RTL موجود (`base.html`) استفاده کن.
7. مدل‌ها را با `TimestampMixin` بساز؛ FK به `users.user_id` با `ondelete="CASCADE"`؛ index با `index=True`.
8. تست‌ها migration SQL اجرا نمی‌کنند — constraintهای DB باید در مدل هم باشند تا `create_all` بسازد.
9. Checkbox در FastAPI form: پیش‌فرض `Form("off")`؛ مقدار ارسالی checked برابر `"on"`؛ مقایسه `== 'on'`.

---

## ۱۱. مواردی که عمداً در فاز ۱ انجام **نشد**

- ❌ route ثبت مأموریت ساعتی توسط کاربر
- ❌ route تأیید/رد توسط مدیر
- ❌ سرویس validation مأموریت (overlap، ساعات موظفی، روز تعطیل)
- ❌ اتصال مأموریت به attendance
- ❌ تغییر `DailyStatus` / `LeaveRequest` / گزارش‌ها / Leave Balance
- ❌ ثبت punch ساختگی / notification / API جداگانه

---

## ۱۲. لاگ تغییرات فازها

| تاریخ | فاز | خلاصه |
|-------|-----|--------|
| ۱۴۰۵/۰۶ (2026-09-24) | ۱ | ایجاد مدل `HourlyMission` + migration 006 + چهار policy key سراسری + UI + تست‌ها + راهنما |
| ۱۴۰۵/۰۶ (2026-09-24) | ۱-اصلاح | جایگزینی policy سراسری با `HourlyMissionPolicy` scoped + سرویس resolve + CRUD صفحه اختصاصی + بازنویسی تست‌ها + بازنویسی راهنما |

**فایل‌های نهایی (پس از اصلاح):**

```
M  database/migrations/006_hourly_mission.sql
M  models/__init__.py
M  models/hourly_mission.py
M  tests/test_hourly_mission.py
M  web/routes/admin_policy.py
M  web/templates/admin/policies.html
A  web/services/hourly_mission_service.py
A  web/templates/admin/policy_hourly_mission.html
A  web/templates/admin/policy_hourly_mission_form.html
M  docs/hourly_mission_implementation.md
```

پیام commit پیشنهادی: `Scope hourly mission policies by group and employee`

**قدم بعدی = فاز ۲:** route ثبت مأموریت ساعتی توسط کاربر (فرم + چک `enabled` از resolve + service validation پایه). قبل از شروع، بخش‌های ۱، ۵، ۶ و ۱۰ همین فایل را مرور کن.
