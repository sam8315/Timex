-- Child allowance policy and annual minimum wage. Editable; not hardcoded in the engine.

BEGIN;

CREATE TABLE IF NOT EXISTS payroll_minimum_wages (
    id SERIAL PRIMARY KEY,
    year_j INTEGER NOT NULL,
    membership_type_code VARCHAR(10) NULL,
    daily_amount NUMERIC(18, 4) NOT NULL,
    effective_from DATE NOT NULL,
    source_reference VARCHAR(255) NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'active',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE payroll_minimum_wages
    ADD COLUMN IF NOT EXISTS membership_type_code VARCHAR(10);

ALTER TABLE payroll_minimum_wages
    DROP CONSTRAINT IF EXISTS uq_payroll_minimum_wages_year;

CREATE UNIQUE INDEX IF NOT EXISTS uq_payroll_min_wage_year_mem
    ON payroll_minimum_wages (year_j, COALESCE(membership_type_code, ''));

CREATE TABLE IF NOT EXISTS payroll_child_allowance_policies (
    id SERIAL PRIMARY KEY,
    membership_type_code VARCHAR(10) NOT NULL,
    applies_to_female BOOLEAN NOT NULL DEFAULT TRUE,
    age_limit_years INTEGER NOT NULL DEFAULT 18,
    require_study_above_age BOOLEAN NOT NULL DEFAULT TRUE,
    wage_day_multiplier NUMERIC(8, 4) NOT NULL DEFAULT 3,
    count_only_verified BOOLEAN NOT NULL DEFAULT FALSE,
    effective_from DATE NOT NULL,
    effective_to DATE NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    notes TEXT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_payroll_child_allowance_membership
    ON payroll_child_allowance_policies (membership_type_code);

ALTER TABLE payroll_components
    DROP CONSTRAINT IF EXISTS ck_payroll_components_calc_mode;

COMMIT;
