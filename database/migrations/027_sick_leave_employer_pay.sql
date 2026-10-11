BEGIN;

-- Sick-leave employer-pay flag. NULL means unknown; existing rows stay NULL.
ALTER TABLE leave_requests
    ADD COLUMN IF NOT EXISTS employer_pays_wages BOOLEAN NULL;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'ck_leave_requests_employer_pays_sl'
    ) THEN
        ALTER TABLE leave_requests
            ADD CONSTRAINT ck_leave_requests_employer_pays_sl
            CHECK (
                employer_pays_wages IS NULL
                OR (leave_type = 'SL' AND status = 'A')
            );
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS ix_leave_requests_sick_pay
    ON leave_requests (leave_type, status, employer_pays_wages);

CREATE TABLE IF NOT EXISTS leave_request_audits (
    id SERIAL PRIMARY KEY,
    leave_request_id INTEGER NOT NULL REFERENCES leave_requests(id) ON DELETE CASCADE,
    action VARCHAR(40) NOT NULL,
    before_json TEXT NULL,
    after_json TEXT NULL,
    actor VARCHAR(50) NULL,
    reason TEXT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_leave_request_audits_request
    ON leave_request_audits (leave_request_id);

CREATE TABLE IF NOT EXISTS leave_financial_orders (
    id SERIAL PRIMARY KEY,
    leave_request_id INTEGER NOT NULL REFERENCES leave_requests(id) ON DELETE CASCADE,
    user_id VARCHAR(50) NOT NULL,
    order_type VARCHAR(20) NOT NULL,
    year_j INTEGER NOT NULL,
    month_j INTEGER NOT NULL,
    run_id INTEGER NULL REFERENCES payroll_runs(id) ON DELETE SET NULL,
    resolution VARCHAR(20) NOT NULL DEFAULT 'unspecified',
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    before_amounts_json TEXT NULL,
    after_amounts_json TEXT NULL,
    actor VARCHAR(50) NULL,
    reason TEXT NULL,
    applied_at TIMESTAMPTZ NULL,
    applied_by VARCHAR(50) NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT ck_leave_financial_orders_type
        CHECK (order_type IN ('initial', 'change', 'cancel')),
    CONSTRAINT ck_leave_financial_orders_resolution
        CHECK (resolution IN ('recalc', 'next_period', 'reopen', 'unspecified')),
    CONSTRAINT ck_leave_financial_orders_status
        CHECK (status IN ('pending', 'applied', 'rejected'))
);

CREATE INDEX IF NOT EXISTS ix_leave_financial_orders_request
    ON leave_financial_orders (leave_request_id);

CREATE INDEX IF NOT EXISTS ix_leave_financial_orders_user
    ON leave_financial_orders (user_id);

CREATE TABLE IF NOT EXISTS payroll_day_adjustment_rules (
    id SERIAL PRIMARY KEY,
    component_id INTEGER NOT NULL REFERENCES payroll_components(id) ON DELETE CASCADE,
    membership_type_code VARCHAR(10) NULL,
    user_id VARCHAR(50) NULL REFERENCES users(user_id) ON DELETE CASCADE,
    effective_from DATE NOT NULL,
    effective_to DATE NULL,
    sick_mode VARCHAR(20) NOT NULL DEFAULT 'keep',
    absence_mode VARCHAR(20) NOT NULL DEFAULT 'keep',
    basis VARCHAR(30) NOT NULL DEFAULT 'fixed_30',
    notes TEXT NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT ck_payroll_day_rules_one_scope
        CHECK (user_id IS NULL OR membership_type_code IS NULL),
    CONSTRAINT ck_payroll_day_rules_sick_mode
        CHECK (sick_mode IN ('keep', 'prorate', 'exclude')),
    CONSTRAINT ck_payroll_day_rules_absence_mode
        CHECK (absence_mode IN ('keep', 'prorate', 'ignore')),
    CONSTRAINT ck_payroll_day_rules_basis
        CHECK (basis IN ('fixed_30', 'calendar_month', 'scheduled_work'))
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_payroll_day_rules_scope
    ON payroll_day_adjustment_rules (
        component_id,
        COALESCE(membership_type_code, ''),
        COALESCE(user_id, ''),
        effective_from
    );

COMMIT;
