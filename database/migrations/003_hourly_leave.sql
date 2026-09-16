BEGIN;

-- ============================================
-- Phase 7: Hourly Leave Tables
-- Created: 2026-09-07
-- Purpose: Store hourly leave policies, resolutions, and minute-based transactions
-- ============================================

-- Hourly Leave Policy table (NO weekly schedule — uses AttendancePolicyDay)
CREATE TABLE hourly_leave_policies (
    id SERIAL PRIMARY KEY,
    employment_type_code VARCHAR(10) NOT NULL,
    user_id VARCHAR(50),
    effective_from_date DATE NOT NULL,
    effective_to_date DATE,
    is_active BOOLEAN DEFAULT TRUE NOT NULL,

    -- HL-specific rules
    hourly_leave_entitled BOOLEAN DEFAULT TRUE NOT NULL,
    max_daily_minutes INTEGER DEFAULT 180 NOT NULL,
    monthly_exempt_minutes INTEGER DEFAULT 480 NOT NULL,
    conversion_minutes_per_day INTEGER DEFAULT 480 NOT NULL,
    granularity_minutes INTEGER DEFAULT 15 NOT NULL,
    min_request_minutes INTEGER DEFAULT 15,
    max_request_minutes INTEGER DEFAULT 240,

    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,

    CONSTRAINT fk_hourly_leave_policies_user FOREIGN KEY (user_id)
        REFERENCES users(user_id) ON DELETE CASCADE
);

-- Indexes for efficient lookups
CREATE INDEX idx_hourly_leave_policies_emp_type ON hourly_leave_policies(employment_type_code);
CREATE INDEX idx_hourly_leave_policies_user ON hourly_leave_policies(user_id);
CREATE INDEX idx_hourly_leave_policies_from_date ON hourly_leave_policies(effective_from_date);
CREATE INDEX idx_hourly_leave_policies_to_date ON hourly_leave_policies(effective_to_date);
CREATE INDEX idx_hourly_leave_policies_active ON hourly_leave_policies(is_active);
CREATE INDEX ix_hourly_leave_policies_emp_type_date ON hourly_leave_policies(employment_type_code, effective_from_date);
CREATE INDEX ix_hourly_leave_policies_user_date ON hourly_leave_policies(user_id, effective_from_date);

-- Hourly Leave Resolution (audit trail per request)
CREATE TABLE hourly_leave_resolutions (
    id SERIAL PRIMARY KEY,
    leave_request_id INTEGER NOT NULL REFERENCES leave_requests(id),

    -- Input
    requested_minutes INTEGER NOT NULL,

    -- Policy snapshot at approval time
    policy_conversion_rate INTEGER NOT NULL,
    policy_monthly_exempt INTEGER NOT NULL,
    policy_daily_limit INTEGER NOT NULL,
    policy_entitled BOOLEAN NOT NULL,

    -- Daily limit check
    daily_usage_before INTEGER NOT NULL DEFAULT 0,
    daily_usage_after INTEGER NOT NULL,
    daily_limit_exceeded BOOLEAN NOT NULL DEFAULT FALSE,
    full_day_conversion BOOLEAN NOT NULL DEFAULT FALSE,

    -- Monthly exempt calculation
    monthly_exempt_used_before INTEGER NOT NULL DEFAULT 0,
    monthly_exempt_applied INTEGER NOT NULL DEFAULT 0,

    -- Subject to AL
    minutes_subject_to_al INTEGER NOT NULL,

    -- Annual accumulation
    annual_subject_minutes_before INTEGER NOT NULL DEFAULT 0,
    annual_subject_minutes_after INTEGER NOT NULL,
    annual_remainder_minutes INTEGER NOT NULL,

    -- AL conversion (only newly completed days)
    new_al_days_deducted INTEGER NOT NULL DEFAULT 0,

    -- Status tracking
    status VARCHAR(10) NOT NULL DEFAULT 'PENDING',

    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL
);

CREATE INDEX idx_hourly_leave_resolutions_request ON hourly_leave_resolutions(leave_request_id);
CREATE INDEX idx_hourly_leave_resolutions_status ON hourly_leave_resolutions(status);

-- Hourly Leave Transaction (minute-based ledger)
CREATE TABLE hourly_leave_transactions (
    id SERIAL PRIMARY KEY,
    user_id VARCHAR(50) NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    year INTEGER NOT NULL,
    month INTEGER NOT NULL,
    amount_minutes INTEGER NOT NULL,
    transaction_type VARCHAR(10) NOT NULL,
    exempt_minutes INTEGER NOT NULL DEFAULT 0,
    subject_to_al_minutes INTEGER NOT NULL DEFAULT 0,
    description TEXT,
    reference_id INTEGER,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL
);

CREATE INDEX idx_hourly_leave_transactions_user_year_month ON hourly_leave_transactions(user_id, year, month);
CREATE INDEX idx_hourly_leave_transactions_type ON hourly_leave_transactions(transaction_type);
CREATE INDEX idx_hourly_leave_transactions_ref ON hourly_leave_transactions(reference_id);

-- Add start_time and end_time to leave_requests (nullable, only for HL type)
ALTER TABLE leave_requests ADD COLUMN start_time TIME;
ALTER TABLE leave_requests ADD COLUMN end_time TIME;

-- ============================================
-- Comments (Persian)
-- ============================================
COMMENT ON TABLE hourly_leave_policies IS 'سیاست مرخصی ساعتی برای هر نوع عضویت';
COMMENT ON TABLE hourly_leave_resolutions IS 'تاریخچه تصمیم‌گیری برای هر درخواست مرخصی ساعتی';
COMMENT ON TABLE hourly_leave_transactions IS 'تراکنش‌های مرخصی ساعتی بر اساس دقیقه';

COMMENT ON COLUMN hourly_leave_policies.employment_type_code IS 'کد نوع عضویت: 1=رسمی، 2=وظیفه، 3=خریدخدمت، 4=قراردادی، 5=پزشک';
COMMENT ON COLUMN hourly_leave_policies.user_id IS 'اگر ست شده، این Policy فقط برای این کارمند اعمال می‌شود (Override)';
COMMENT ON COLUMN hourly_leave_policies.hourly_leave_entitled IS 'اگر false: درخواست امکان‌پذیر است اما ماهانه exempt ندارد';
COMMENT ON COLUMN hourly_leave_policies.max_daily_minutes IS 'حداکثر دقیقه مرخصی ساعتی در روز — بیشتر از این = تبدیل به یک روز کامل';
COMMENT ON COLUMN hourly_leave_policies.monthly_exempt_minutes IS 'دقایق معاف از مرخصی استحقاقی در ماه (بدون انتقال)';
COMMENT ON COLUMN hourly_leave_policies.conversion_minutes_per_day IS 'دقیقه معادل یک روز مرخصی استحقاقی (مستقل از ساعت کاری روزانه)';
COMMENT ON COLUMN hourly_leave_policies.granularity_minutes IS 'حداقل و واحد گرد زمانی (مثلاً ۱۵ دقیقه)';

COMMENT ON COLUMN hourly_leave_resolutions.requested_minutes IS 'دقایق درخواست شده';
COMMENT ON COLUMN hourly_leave_resolutions.minutes_subject_to_al IS 'دقایق مشمول کسر از استحقاقی';
COMMENT ON COLUMN hourly_leave_resolutions.annual_subject_minutes_after IS 'مجموع دقایق مشمول استحقاقی در سال تا این درخواست';
COMMENT ON COLUMN hourly_leave_resolutions.new_al_days_deducted IS 'تعداد روزهای مرخصی استحقاقی کسر شده در این درخواست';

COMMENT ON COLUMN hourly_leave_transactions.amount_minutes IS 'دقایق مرخصی ساعتی';
COMMENT ON COLUMN hourly_leave_transactions.exempt_minutes IS 'دقایق معاف از کسر';
COMMENT ON COLUMN hourly_leave_transactions.subject_to_al_minutes IS 'دقایق مشمول کسر از استحقاقی';

COMMIT;
