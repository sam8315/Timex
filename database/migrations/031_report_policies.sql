-- سیاست گزارش: تنظیمات نسخه‌دار و مستقل برای هر گزارش (v1: legal_overtime_monthly).
-- بدون seed: در نبود ردیف، پیش‌فرض‌های کد اعمال می‌شود و داده‌ای بازنویسی نمی‌شود.

CREATE TABLE IF NOT EXISTS report_policies (
    id SERIAL PRIMARY KEY,
    report_key VARCHAR(50) NOT NULL,
    effective_from_date DATE NOT NULL,
    effective_to_date DATE,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    schema_version INTEGER NOT NULL DEFAULT 1,
    settings JSONB NOT NULL DEFAULT '{}'::jsonb,
    notes TEXT,
    created_by VARCHAR(50),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT ck_report_policies_date_order
        CHECK (effective_to_date IS NULL OR effective_to_date >= effective_from_date)
);

CREATE INDEX IF NOT EXISTS ix_report_policies_report_key ON report_policies (report_key);
CREATE INDEX IF NOT EXISTS ix_report_policies_key_from
    ON report_policies (report_key, effective_from_date);
CREATE UNIQUE INDEX IF NOT EXISTS uq_report_policies_active_key_from
    ON report_policies (report_key, effective_from_date) WHERE is_active;
