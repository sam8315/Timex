# راهنمای پیاده‌سازی مأموریت ساعتی (Hourly Mission)

> این فایل حافظه بلندمدت پروژه است. مدل بعدی باید با خواندن همین فایل + فایل‌های اشاره‌شده بتواند ادامه کار را بدون بررسی کل گفتگو انجام دهد.
> آخرین به‌روزرسانی: در پایان فاز ۱.

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
| ذخیره‌سازی | جدول مستقل `hourly_missions` — **نه** داخل `LeaveRequest` و **نه** داخل `DailyStatus` |
| مدل SQLAlchemy | `models/hourly_mission.py` → کلاس `HourlyMission` |
| مدت مأموریت | **محاسبه‌شده** (property `duration_minutes`) — ذخیره نمی‌شود |
| سیاست کلی | چهار `PolicyValue` در دسته `hourly_mission` جدول‌های `policies`/`policy_values` (بدون جدول جدید) |
| UI سیاست | بخشی از صفحه موجود `/admin/policies` (`web/templates/admin/policies.html`) — صفحه جدید ساخته **نشد** |
| validation/service/route ثبت | **فازهای بعد** — در فاز ۱ ایجاد نشد |

### چرا DailyStatus نیست؟

`DailyStatus` برای وضعیت‌های روزانه است؛ مأموریت روزانه (`M`) کل موظفی روز را صفر می‌کند، در حالی که مأموریت ساعتی فقط بخشی از زمان روز را پوشش می‌دهد. ترکیب این دو مفهوم در یک جدول باعث شاخه‌شدن پیچیده در محاسبات گزارش می‌شود.

### چرا LeaveRequest نیست؟

`LeaveRequest` مفهوم مرخصی است (days_count، LeaveBalance، تراکنش‌ها). مأموریت ساعتی تعادل مرخصی ندارد و منطق کسری متفاوتی (کسر از موظفی، نه از مرخصی) خواهد داشت.

---

## ۳. فازهای پروژه

| فاز | محتوا | وضعیت |
|-----|--------|--------|
| **فاز ۱** | مدل داده + migration + چهار سیاست کلی + UI سیاست در صفحه «سیاست کلی» + ثبت دانش در همین فایل | ✅ انجام شد |
| فاز ۲ | Route ثبت مأموریت ساعتی توسط کاربر + فرم + فراخوانی service validation پایه | ⬜ |
| فاز ۳ | Route تأیید/رد توسط مدیر + سرویس validation کامل (overlap، ساعات موظفی، روز تعطیل) | ⬜ |
| فاز ۴ | اتصال به attendance/گزارش‌ها (اعمال `hourly_mission_deduct_from_required_minutes` در محاسبه موظفی مؤثر) | ⬜ |
| فاز ۵ | نوتیفیکیشن + بهبود گزارش‌ها در صورت نیاز | ⬜ |

> ترتیب فازها ممکن است با صلاحدید کاربر تغییر کند؛ اما هر فاز فقط در محدوده خودش کار کند.

---

## ۴. وضعیت فاز فعلی

**فاز ۱ — تکمیل شده.**

انجام شده:

1. فایل راهنما (همین فایل)
2. مدل `HourlyMission` در `models/hourly_mission.py`
3. Migration: `database/migrations/006_hourly_mission.sql`
4. ثبت مدل در `models/__init__.py`
5. چهار Policy key در سیستم `Policy`/`PolicyValue` + UI در `/admin/policies`
6. تست‌های فاز ۱ (`tests/test_hourly_mission.py`)

انجام **نشده** (عمداً — فازهای بعد): بخش ۱۰.

---

## ۵. تصمیم‌های معماری

### ۵.۱ نام‌گذاری (بررسی شده با convention پروژه)

- پیشنهاد اولیه: `models/employee_hourly_mission.py`
- **نام نهایی:** `models/hourly_mission.py`
- **کلاس:** `HourlyMission` — **جدول:** `hourly_missions`
- دلیل: جدول‌های `employee_*` در این پروژه داده‌های اصلی/صفتی کارمند هستند (phone, address, bank_account, …)، در حالی که رکوردهای تراکنشی با نام قابلیت نام‌گذاری می‌شوند: `leave_request`، `daily_status`، `attendance`. مأموریت ساعتی یک رکورد تراکنشی/درخواستی است.

### ۵.۲ وضعیت‌ها (Status)

از همان single-character convention مدل `LeaveRequest` استفاده شد:

| کد | معنی | برچسب فارسی |
|----|------|-------------|
| `P` | pending | در انتظار |
| `A` | approved | تایید شده |
| `R` | rejected | رد شده |
| `D` | cancelled | لغو شده |

نکته: در `LeaveRequest` کد `D` معنای «حذف شده» دارد؛ اینجا «لغو شده» (cancel) پوشش داده می‌شود. cycle چهارگانه درخواست (pending/approved/rejected/cancelled) کامل است.

### ۵.۳ فیلدهای مدل

| فیلد | نوع | توضیح |
|------|-----|--------|
| `id` | int PK | |
| `user_id` | String(50) FK → `users.user_id` ON DELETE CASCADE, index | کارمند/کاربر |
| `mission_date` | Date, index | تاریخ مأموریت |
| `start_time` | Time NOT NULL | ساعت شروع |
| `end_time` | Time NOT NULL | ساعت پایان |
| `reason` | Text NULL | علت/توضیح |
| `destination` | String(200) NULL | مقصد (متن ساده؛ نه city FK — سبک‌تر و کافی برای مأموریت ساعتی) |
| `status` | String(1) default `'P'`, index | P/A/R/D |
| `approved_by` | String(50) NULL | تأییدکننده |
| `approved_at` | DateTime(timezone=True) NULL | زمان تأیید |
| `rejection_reason` | Text NULL | دلیل رد |
| `created_at` / `updated_at` | `TimestampMixin` | مطابق convention کل پروژه |

- رابطه: `user = relationship("User", backref="hourly_missions")` (مثل `LeaveRequest`)
- **مدت مأموریت ذخیره نمی‌شود** → property `duration_minutes` (دقیقه، محاسبه‌شده)
- Constraintهای DB:
  - `ck_hourly_missions_time_order` → `CHECK (start_time < end_time)`
  - `ck_hourly_missions_status` → `CHECK (status IN ('P','A','R','D'))`
  - هر دو در مدل و migration هستند (نام‌گذاری `ck_*` مطابق `employee_address`)

### ۵.۴ چهار Global Policy

دسته (category): **`hourly_mission`** — Policy container با نام «سیاست مأموریت ساعتی».

| Policy key | پیش‌فرض | معنی |
|------------|---------|------|
| `hourly_mission_enabled` | `true` | اگر false باشد، کاربر نمی‌تواند در فازهای بعد درخواست ثبت کند |
| `hourly_mission_working_hours_only` | `true` | در فاز سرویس: start/end باید داخل ساعات موظفی همان روز (بر اساس `AttendancePolicy` واقعی کارمند — نه ساعت ثابت سراسری) باشد |
| `hourly_mission_allowed_on_holidays` | `false` | آیا مأموریت ساعتی در روز تعطیل مجاز است |
| `hourly_mission_deduct_from_required_minutes` | `true` | اگر true: مدت تأییدشده از موظفی مؤثر روز کسر می‌شود؛ اگر false: فقط گزارش می‌شود. **روی خود رکورد مأموریت اثری ندارد** — فقط محاسبه سرویس/گزارش را کنترل می‌کند |

ذخیره‌سازی: `PolicyValue` با `region_code = NULL` (سراسری)، مقادیر رشته‌ای `'true'`/`'false'` (همان pattern پیامک `sms_enabled`).

**نکته برای فازهای بعد:** خواندن مقدار → اگر `PolicyValue` نبود، از defaultهای بالا استفاده شود (کد مرجع: `_hourly_mission_flag_values` در `web/routes/admin_policy.py`).

### ۵.۵ تعریف Holiday در پروژه (برای فازهای بعد — مفهوم جدید نسازید)

تعطیل بودن یک روز از **سه منبع** تشکیل شده (طبق `web/services/attendance_policy_service.py` و `core/holiday_manager.py`):

1. **جمعه** — هفته کاری شمسی: `date.weekday() == 4` (در validation مرخصی ساعتی هم جدا بررسی می‌شود)
2. **جدول `holidays`** (`models/holiday.py`) — `holiday_date` + `group_id` (NULL = ملی/همه، یا کد گروه عضویت `'1'`..`'5'`)
3. **`AttendancePolicyDay.is_working_day`** — روز غیرکاری در برنامه هفتگی سیاست حضور همان کارمند

سرویس موجود: `resolve_attendance_policy()` + `resolve_policy_day()` از `web/services/attendance_policy_service.py` (نگاه کنید به نحوه استفاده در `validate_hourly_leave_request`).

---

## ۶. فایل‌های مرتبط

### فاز ۱ (ایجاد/تغییر)

| فایل | عمل |
|------|-----|
| `docs/hourly_mission_implementation.md` | CREATED (همین فایل) |
| `models/hourly_mission.py` | CREATED — مدل `HourlyMission` |
| `models/__init__.py` | MODIFIED — import + `__all__` |
| `database/migrations/006_hourly_mission.sql` | CREATED — جدول + seed چهار policy |
| `web/routes/admin_policy.py` | MODIFIED — ثابت‌ها، helper خواندن، GET context، POST save |
| `web/templates/admin/policies.html` | MODIFIED — بخش تنظیمات چهارگانه |
| `tests/test_hourly_mission.py` | CREATED — تست‌های فاز ۱ |

### فایل‌های مرجع (نخوانید مگر نیاز — فقط برای الگو)

| فایل | چرا مهم است |
|------|-------------|
| `models/leave_request.py` | الگوی status code های `P/A/R/D`، فیلدهای تأیید، `to_dict` |
| `models/daily_status.py` | الگوی جدول روزانه + UniqueConstraint (که عمداً استفاده **نشد**) |
| `models/policy.py` | ساختار `Policy` / `PolicyValue` / `PolicyAuditLog` |
| `web/routes/admin_policy.py` | helperهای `_get_param` / `_set_param` / `_get_leave_policy` + الگوی صفحات سیاست |
| `web/services/notification_service.py` | الگوی policy key سراسری با مقدار true/false (`sms_enabled`) |
| `web/services/hourly_leave_service.py` | الگوی validation مرخصی ساعتی (ساعات موظفی، overlap، روز تعطیل) — برای فاز ۲/۳ |
| `web/services/attendance_policy_service.py` | `resolve_policy` / `resolve_policy_day` / `time_to_minutes` / تعریف holiday |
| `database/migrations/003_hourly_leave.sql` و `004_travel_leave.sql` | الگوی SQL migration (BEGIN/COMMIT، index، COMMENT) |
| `database/migrations/001_service_regions_and_policies.sql` | الگوی seed کردن Policy + PolicyValue |
| `tests/conftest.py` | fixtureهای تست (`db`, `client`, `make_user`, `login_as`)؛ **migrationهای SQL در تست اجرا نمی‌شوند** — فقط `create_all` |

---

## ۷. Migrationهای مرتبط

- **شماره:** `006` (بعد از `005_travel_leave_policies.sql` — آخرین قبل از این فاز)
- **فایل:** `database/migrations/006_hourly_mission.sql`
- شامل: `CREATE TABLE hourly_missions` + ۲ CHECK + ۳ index + COMMENT + seed `policies` و چهار `policy_values` (idempotent با `IF NOT EXISTS` / `NOT EXISTS`)
- اجرای migration: پروژه runner خودکار ندارد؛ مثل migrationهای قبلی **دستی** با psql/ادمین اجرا می‌شود.
- **تست‌ها:** SQL migration اجرا نمی‌شود؛ جدول در تست‌ها با `Base.metadata.create_all` (در `tests/conftest.py`) ساخته می‌شود. پس **هر مدل جدید باید حتماً در `models/__init__.py` import شود** تا در metadata ثبت شود.

---

## ۸. Policy keyهای استفاده‌شده

```
category = hourly_mission
├── hourly_mission_enabled                      (پیش‌فرض: true)
├── hourly_mission_working_hours_only           (پیش‌فرض: true)
├── hourly_mission_allowed_on_holidays          (پیش‌فرض: false)
└── hourly_mission_deduct_from_required_minutes (پیش‌فرض: true)
```

ثابت‌ها در: `web/routes/admin_policy.py` → `HOURLY_MISSION_POLICY_CATEGORY`, `HOURLY_MISSION_PARAM_KEYS`, `HOURLY_MISSION_DEFAULTS`, `HOURLY_MISSION_PARAM_NOTES`.

ذخیره در UI: POST `/admin/policies/hourly-mission/save` (فقط `super_admin` + permission `manage_users`) — از helper `_set_param` استفاده می‌کند که `PolicyAuditLog` هم ثبت می‌کند.

خواندن در UI: `_hourly_mission_flag_values(db)` → dict از چهار کلید با در نظر گرفتن default.

---

## ۹. تست‌های انجام‌شده و نتیجه

اجرای تست با: `.venv\Scripts\python.exe -m pytest` از ریشه پروژه (دیتابیس تست `timex_test_db` روی PostgreSQL محلی).

| دستور / محدوده | نتیجه |
|----------------|--------|
| `pytest tests/test_hourly_mission.py` (۱۰ تست جدید فاز ۱) | ✅ **10 passed** (~4s) |
| `pytest tests/test_policy.py tests/test_daily_status.py tests/test_access.py tests/test_hourly_leave_integration.py` (تست‌های مرتبط قبلی) | ✅ **132 passed** (~72s) |
| `pytest` کل test suite (۱۰۸۹ تست) | ⚠️ **1068 passed, 21 failed** (~13min) |
| `pytest tests/test_hourly_mission.py tests/test_policy.py tests/test_daily_status.py` (اجرای نهایی قبل از commit) | ✅ **44 passed** |

### تست‌های جدید فاز ۱ (`tests/test_hourly_mission.py`)

- import/ثبت مدل در `Base.metadata` و export از `models`
- ساخته‌شدن جدول `hourly_missions` در دیتابیس تست (create_all)
- ساخت + خواندن رکورد معتبر + بررسی `duration_minutes` / `status_name` / timestamps
- رد شدن `start_time >= end_time` با `IntegrityError` (CHECK constraint)
- رد شدن status نامعتبر (`X`) با `IntegrityError`
- چهار کد وضعیت P/A/R/D
- رندر شدن بخش تنظیمات در صفحه `/admin/policies`
- ذخیره چهار policy key از طریق POST (با audit log) + مقداردهی `false` برای checkbox خاموش
- idempotent بودن save (بدون رکورد تکراری)
- عدم دسترسی non-super_admin (403)

### ⚠️ ۲۱ تست ناموفق کل suite — **از قبل موجود و غیرمرتبط**

این ۲۱ تست حتی روی درخت تمیز (قبل از تغییرات فاز ۱، با `git stash`) هم شکست می‌خوردند؛ یعنی **رگرسیون فاز ۱ نیستند**:

- `tests/test_attendance_policy_service.py` — ۱۹ تست (TestResolvePolicy, TestComputeLate, …)
- `tests/test_admin_travel_leave_preview_route.py` — ۱ تست
- `tests/test_travel_leave_attendance.py` — ۱ تست

اگر فازهای بعد به این فایل‌ها برخوردند، ابتدا وضعیت آن‌ها را روی commit پایه بررسی کنید تا تقصیر تغییر جدید نباشد.

### نکته درباره اجرای کل suite

کل suite حدود **۱۳ دقیقه** طول می‌کشد (۱۰۸۹ تست)؛ برای هر فاز معقول است اجرا شود. حداقلِ پیشنهادی قبل از هر commit: `pytest tests/test_hourly_mission.py tests/test_policy.py tests/test_daily_status.py tests/test_hourly_leave_integration.py`.

---

## ۱۰. نکات مهم برای مدل بعدی

1. **این فایل را اول بخوان.** بعد فقط فایل‌های بخش ۶ را باز کن؛ پروژه را از صفر نگرد.
2. اجرای تست: `.venv\Scripts\python.exe -m pytest` از ریشه پروژه (pytest.ini → testpaths=tests). دیتابیس تست: `timex_test_db` روی PostgreSQL محلی (conftest خودش می‌سازد). قبل از commit حداقل: `pytest tests/test_hourly_mission.py tests/test_policy.py tests/test_daily_status.py tests/test_hourly_leave_integration.py`. کل suite ≈ ۱۳ دقیقه است؛ ۲۱ شکست شناخته‌شده از قبل دارد (بخش ۹).
3. **شاخه کاری:** `work` — commit فاز ۱: `Add hourly mission data model and policies`.
4. هنگام افزودن route ثبت/تأیید در فاز ۲+:
   - اول `hourly_mission_enabled` را چک کن (false → جلوی ثبت را بگیر).
   - از `resolve_attendance_policy` + `resolve_policy_day` برای ساعات موظفی استفاده کن (کپی نکن).
   - overlap را روی `hourly_missions` همان `user_id` + `mission_date` با status در `('P','A')` بسنج (الگو: overlap مرخصی ساعتی در `hourly_leave_service`).
   - هرگز در `LeaveRequest` یا `DailyStatus` رکورد مأموریت ساعتی نساز.
5. اگر policy key جدید خواستی، به `HOURLY_MISSION_PARAM_KEYS` و migration بعدی اضافه کن؛ نام‌گذاری: `hourly_mission_*` با مقدار `'true'`/`'false'`.
6. UI: از Bootstrap/RTL موجود (`base.html`) استفاده کن؛ قالب جدید لازم نیست مگر برای فرم‌های ثبت.
7. مدل‌ها را با `TimestampMixin` بساز؛ FK به `users.user_id` با `ondelete="CASCADE"`؛ index با `index=True`.
8. تست‌ها migration SQL اجرا نمی‌کنند — اگر constraint/db-level چیزی اضافه کردی، در مدل هم باید باشد تا `create_all` آن را بسازد.

---

## ۱۱. مواردی که عمداً در فاز ۱ انجام **نشد**

- ❌ route ثبت مأموریت ساعتی توسط کاربر
- ❌ route تأیید/رد توسط مدیر
- ❌ سرویس validation مأموریت (`web/services/hourly_mission_service.py` هنوز وجود ندارد)
- ❌ overlap checking
- ❌ کنترل ساعات موظفی در service
- ❌ اتصال مأموریت به attendance
- ❌ تغییر `DailyStatus`
- ❌ تغییر محاسبه گزارش روزانه/ماهانه
- ❌ تغییر گزارش خام
- ❌ تغییر `LeaveRequest`
- ❌ تغییر Leave Balance
- ❌ ثبت punch ساختگی
- ❌ notification
- ❌ API جداگانه

---

## ۱۲. لاگ تغییرات فازها

| تاریخ | فاز | خلاصه |
|-------|-----|--------|
| ۱۴۰۵/۰۶ (2026-09-24) | ۱ | ایجاد مدل `HourlyMission` + migration 006 + چهار policy key + UI سیاست کلی + تست‌ها + همین راهنما |

**فایل‌های commit فاز ۱:**

```
A  database/migrations/006_hourly_mission.sql
A  docs/hourly_mission_implementation.md
A  models/hourly_mission.py
A  tests/test_hourly_mission.py
M  models/__init__.py
M  web/routes/admin_policy.py
M  web/templates/admin/policies.html
```

پیام commit: `Add hourly mission data model and policies`

**قدم بعدی = فاز ۲:** route ثبت مأموریت ساعتی توسط کاربر (فرم + چک `hourly_mission_enabled` + service validation پایه). قبل از شروع، بخش‌های ۱، ۵، ۶ و ۱۰ همین فایل را مرور کن.
