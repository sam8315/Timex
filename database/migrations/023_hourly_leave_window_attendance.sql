BEGIN;

-- Per-membership hourly-leave window and attendance-overlap rules.
-- Defaults stay off so existing policies keep the previous behavior
-- until an admin enables each rule for that membership type.

ALTER TABLE hourly_leave_policies
    ADD COLUMN IF NOT EXISTS enforce_allowed_window BOOLEAN NOT NULL DEFAULT FALSE;

ALTER TABLE hourly_leave_policies
    ADD COLUMN IF NOT EXISTS allowed_start_time TIME;

ALTER TABLE hourly_leave_policies
    ADD COLUMN IF NOT EXISTS allowed_end_time TIME;

ALTER TABLE hourly_leave_policies
    ADD COLUMN IF NOT EXISTS reject_attendance_overlap BOOLEAN NOT NULL DEFAULT FALSE;

COMMENT ON COLUMN hourly_leave_policies.enforce_allowed_window IS 'اگر true: مرخصی ساعتی فقط داخل بازه تعریف‌شده در همین سیاست مجاز است';
COMMENT ON COLUMN hourly_leave_policies.allowed_start_time IS 'شروع بازه مجاز مرخصی ساعتی';
COMMENT ON COLUMN hourly_leave_policies.allowed_end_time IS 'پایان بازه مجاز مرخصی ساعتی';
COMMENT ON COLUMN hourly_leave_policies.reject_attendance_overlap IS 'اگر true: تداخل بازه مرخصی با تردد همان روز رد می‌شود';

COMMIT;
