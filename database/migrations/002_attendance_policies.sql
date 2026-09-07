BEGIN;

-- ============================================
-- Phase 5: Attendance Policy Tables
-- Created: 2026-09-07
-- Purpose: Store per-employment-type attendance policies with weekly schedules
-- ============================================

-- Attendance Policy table
CREATE TABLE attendance_policies (
    id SERIAL PRIMARY KEY,
    employment_type_code VARCHAR(10) NOT NULL,
    user_id VARCHAR(50),
    effective_from_date DATE NOT NULL,
    effective_to_date DATE,
    late_enabled BOOLEAN DEFAULT TRUE NOT NULL,
    late_allowed_minutes INTEGER DEFAULT 0 NOT NULL,
    late_reference_mode VARCHAR(20) DEFAULT 'FIXED_TIME' NOT NULL,
    early_leave_enabled BOOLEAN DEFAULT TRUE NOT NULL,
    early_leave_allowed_minutes INTEGER DEFAULT 0 NOT NULL,
    early_leave_reference_mode VARCHAR(20) DEFAULT 'FIXED_TIME' NOT NULL,
    is_active BOOLEAN DEFAULT TRUE NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,

    CONSTRAINT fk_attendance_policies_user FOREIGN KEY (user_id)
        REFERENCES users(user_id) ON DELETE CASCADE
);

-- Indexes for efficient lookups
CREATE INDEX idx_attendance_policies_emp_type ON attendance_policies(employment_type_code);
CREATE INDEX idx_attendance_policies_user ON attendance_policies(user_id);
CREATE INDEX idx_attendance_policies_from_date ON attendance_policies(effective_from_date);
CREATE INDEX idx_attendance_policies_to_date ON attendance_policies(effective_to_date);
CREATE INDEX idx_attendance_policies_active ON attendance_policies(is_active);
CREATE INDEX ix_attendance_policies_emp_type_date ON attendance_policies(employment_type_code, effective_from_date);
CREATE INDEX ix_attendance_policies_user_date ON attendance_policies(user_id, effective_from_date);

-- Weekly schedule for each policy (7 days per policy)
CREATE TABLE attendance_policy_days (
    id SERIAL PRIMARY KEY,
    policy_id INTEGER NOT NULL,
    weekday INTEGER NOT NULL,
    is_working_day BOOLEAN DEFAULT TRUE NOT NULL,
    start_time TIME,
    end_time TIME,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,

    CONSTRAINT fk_attendance_policy_days_policy
        FOREIGN KEY (policy_id) REFERENCES attendance_policies(id) ON DELETE CASCADE
);

-- Unique constraint: one schedule per weekday per policy
CREATE UNIQUE INDEX uq_attendance_policy_day_policy_weekday
    ON attendance_policy_days(policy_id, weekday);

-- Index for policy lookups
CREATE INDEX idx_attendance_policy_days_policy ON attendance_policy_days(policy_id);

COMMENT ON TABLE attendance_policies IS 'سیاست‌های حضور و غیاب برای هر نوع عضویت (رسمی، وظیفه، خریدخدمت، قراردادی، پزشک)';
COMMENT ON TABLE attendance_policy_days IS 'برنامه هفتگی هر سیاست حضور و غیاب (ورود/خروج روزانه)';

COMMENT ON COLUMN attendance_policies.employment_type_code IS 'کد نوع عضویت: 1=رسمی، 2=وظیفه، 3=خریدخدمت، 4=قراردادی، 5=پزشک';
COMMENT ON COLUMN attendance_policies.user_id IS 'اگر ست شده، این Policy فقط برای این کارمند اعمال می‌شود (Override)';
COMMENT ON COLUMN attendance_policies.late_allowed_minutes IS 'دقایق مجاز دیرکرد (Grace Period قبل از Violation)';
COMMENT ON COLUMN attendance_policies.late_reference_mode IS 'FIXED_TIME = از Weekly Schedule، SHIFT = از جدول شیفت (آینده)';
COMMENT ON COLUMN attendance_policies.early_leave_allowed_minutes IS 'دقایق مجاز خروج زود (Grace Period قبل از Violation)';
COMMENT ON COLUMN attendance_policies.early_leave_reference_mode IS 'FIXED_TIME = از Weekly Schedule، SHIFT = از جدول شیفت (آینده)';

COMMENT ON COLUMN attendance_policy_days.weekday IS '0=دوشنبه، 1=سه‌شنبه، 2=چهارشنبه، 3=پنج‌شنبه، 4=جمعه، 5=شنبه، 6=یکشنبه';
COMMENT ON COLUMN attendance_policy_days.start_time IS 'ساعت ورود (برای روزهای کاری)';
COMMENT ON COLUMN attendance_policy_days.end_time IS 'ساعت خروج (برای روزهای کاری)';

COMMIT;