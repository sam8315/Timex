-- Overtime policy per membership. Method and basis items are editable.

BEGIN;

CREATE TABLE IF NOT EXISTS payroll_overtime_policies (
    id SERIAL PRIMARY KEY,
    membership_type_code VARCHAR(10) NOT NULL,
    method VARCHAR(40) NOT NULL DEFAULT 'monthly_div',
    basis_codes TEXT NOT NULL DEFAULT '',
    divisor NUMERIC(18, 4) NOT NULL DEFAULT 157,
    premium_factor NUMERIC(8, 4) NOT NULL DEFAULT 1.4,
    ordinary_month_hours NUMERIC(18, 4) NOT NULL DEFAULT 220,
    effective_from DATE NOT NULL,
    effective_to DATE NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    notes TEXT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_payroll_overtime_membership UNIQUE (membership_type_code)
);

COMMIT;
