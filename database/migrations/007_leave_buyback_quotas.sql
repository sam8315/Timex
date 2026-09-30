-- Migration 007: leave buyback quotas (process entitlement, not requestable leave)
CREATE TABLE IF NOT EXISTS leave_buyback_quotas (
    id SERIAL PRIMARY KEY,
    user_id VARCHAR(50) NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    year INTEGER NOT NULL,
    days INTEGER NOT NULL DEFAULT 0,
    source VARCHAR(30) NOT NULL DEFAULT 'HR_IMPORT',
    notes TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT uq_leave_buyback_user_year UNIQUE (user_id, year)
);

CREATE INDEX IF NOT EXISTS ix_leave_buyback_quotas_user_id ON leave_buyback_quotas(user_id);
CREATE INDEX IF NOT EXISTS ix_leave_buyback_quotas_year ON leave_buyback_quotas(year);

COMMENT ON TABLE leave_buyback_quotas IS 'سهمیه قابل‌بازخرید (فرآیندی؛ قابل مصرف در درخواست مرخصی نیست)';
COMMENT ON COLUMN leave_buyback_quotas.source IS 'HR_IMPORT / YEAR_END / MANUAL';
