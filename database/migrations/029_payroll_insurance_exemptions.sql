-- معافیت تاریخ‌دار بیمه سهم کارمند برای یک نفر. یک ردیف فعال برای هر کارمند.

CREATE TABLE IF NOT EXISTS payroll_insurance_exemptions (
    id SERIAL PRIMARY KEY,
    user_id VARCHAR(50) NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    effective_from DATE NOT NULL,
    effective_to DATE,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    notes TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_payroll_insurance_exemptions_user_id
    ON payroll_insurance_exemptions (user_id);

CREATE UNIQUE INDEX IF NOT EXISTS uq_payroll_insurance_exemptions_active_user
    ON payroll_insurance_exemptions (user_id)
    WHERE is_active;
