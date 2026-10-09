BEGIN;

-- Optional: add in-grace late/early minutes to monthly-report work hours.
-- Default stays off so existing policies keep the previous numbers
-- until an admin enables the rule.

ALTER TABLE attendance_policies
    ADD COLUMN IF NOT EXISTS include_grace_in_work BOOLEAN NOT NULL DEFAULT FALSE;

COMMENT ON COLUMN attendance_policies.include_grace_in_work IS 'اگر true: دقایق داخل فرجهٔ تأخیر/تعجیلِ فعال به کارکرد گزارش‌های ماهانه اضافه می‌شود';

COMMIT;
