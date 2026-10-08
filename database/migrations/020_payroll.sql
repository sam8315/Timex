-- Payroll module (MVP)
-- Idempotent: safe on existing production DBs.

BEGIN;

CREATE TABLE IF NOT EXISTS payroll_components (
    id SERIAL PRIMARY KEY,
    code VARCHAR(40) NOT NULL,
    name VARCHAR(120) NOT NULL,
    kind VARCHAR(20) NOT NULL,
    calc_mode VARCHAR(40) NOT NULL,
    subject_to_insurance BOOLEAN NOT NULL DEFAULT FALSE,
    subject_to_tax BOOLEAN NOT NULL DEFAULT FALSE,
    sort_order INTEGER NOT NULL DEFAULT 100,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    deleted_at TIMESTAMPTZ NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_payroll_components_code UNIQUE (code),
    CONSTRAINT ck_payroll_components_kind CHECK (kind IN ('earning', 'deduction')),
    CONSTRAINT ck_payroll_components_calc_mode CHECK (calc_mode IN (
        'daily_x_covered',
        'fixed_monthly_prorata',
        'seniority_chain',
        'friday_attendance',
        'manual',
        'policy_eidi',
        'policy_bonus',
        'percent_insurance',
        'percent_tax'
    ))
);

CREATE INDEX IF NOT EXISTS ix_payroll_components_active
    ON payroll_components (is_active) WHERE deleted_at IS NULL;

CREATE TABLE IF NOT EXISTS payroll_annual_laws (
    id SERIAL PRIMARY KEY,
    year_j INTEGER NOT NULL,
    new_seniority_daily NUMERIC(18, 4) NOT NULL,
    wage_increase_factor NUMERIC(10, 6) NOT NULL DEFAULT 1,
    effective_from DATE NOT NULL,
    effective_to DATE NULL,
    version VARCHAR(40) NOT NULL DEFAULT '1',
    source_reference VARCHAR(255) NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'active',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_payroll_annual_laws_year_version UNIQUE (year_j, version),
    CONSTRAINT ck_payroll_annual_laws_status CHECK (status IN ('active', 'draft', 'retired'))
);

CREATE INDEX IF NOT EXISTS ix_payroll_annual_laws_year
    ON payroll_annual_laws (year_j);

CREATE TABLE IF NOT EXISTS payroll_rate_settings (
    id SERIAL PRIMARY KEY,
    insurance_employee_pct NUMERIC(8, 4) NOT NULL DEFAULT 7,
    tax_pct NUMERIC(8, 4) NOT NULL DEFAULT 0,
    friday_coefficient NUMERIC(8, 4) NOT NULL DEFAULT 1.96,
    eidi_payment_month INTEGER NOT NULL DEFAULT 12,
    bonus_payment_month INTEGER NOT NULL DEFAULT 12,
    eidi_day_factor NUMERIC(10, 4) NOT NULL DEFAULT 60,
    bonus_day_factor NUMERIC(10, 4) NOT NULL DEFAULT 0,
    hours_per_day NUMERIC(8, 4) NOT NULL DEFAULT 7.3333,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT ck_payroll_rate_eidi_month CHECK (eidi_payment_month BETWEEN 1 AND 12),
    CONSTRAINT ck_payroll_rate_bonus_month CHECK (bonus_payment_month BETWEEN 1 AND 12)
);

CREATE TABLE IF NOT EXISTS payroll_assignments (
    id SERIAL PRIMARY KEY,
    component_id INTEGER NOT NULL
        REFERENCES payroll_components(id) ON DELETE CASCADE,
    membership_type_code VARCHAR(10) NULL,
    user_id VARCHAR(50) NULL
        REFERENCES users(user_id) ON DELETE CASCADE,
    amount NUMERIC(18, 4) NOT NULL DEFAULT 0,
    effective_from DATE NOT NULL,
    effective_to DATE NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    notes TEXT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT ck_payroll_assignments_scope CHECK (
        (user_id IS NOT NULL AND membership_type_code IS NULL)
        OR (user_id IS NULL AND membership_type_code IS NOT NULL)
    )
);

CREATE INDEX IF NOT EXISTS ix_payroll_assignments_component
    ON payroll_assignments (component_id);
CREATE INDEX IF NOT EXISTS ix_payroll_assignments_membership
    ON payroll_assignments (membership_type_code);
CREATE INDEX IF NOT EXISTS ix_payroll_assignments_user
    ON payroll_assignments (user_id);
CREATE INDEX IF NOT EXISTS ix_payroll_assignments_from
    ON payroll_assignments (effective_from);

CREATE TABLE IF NOT EXISTS payroll_periods (
    id SERIAL PRIMARY KEY,
    year_j INTEGER NOT NULL,
    month_j INTEGER NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'open',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_payroll_periods_ym UNIQUE (year_j, month_j),
    CONSTRAINT ck_payroll_periods_month CHECK (month_j BETWEEN 1 AND 12),
    CONSTRAINT ck_payroll_periods_status CHECK (status IN ('open', 'closed'))
);

CREATE TABLE IF NOT EXISTS payroll_runs (
    id SERIAL PRIMARY KEY,
    period_id INTEGER NOT NULL
        REFERENCES payroll_periods(id) ON DELETE CASCADE,
    membership_type_code VARCHAR(10) NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'draft',
    notes TEXT NULL,
    created_by VARCHAR(50) NULL
        REFERENCES users(user_id) ON DELETE SET NULL,
    calculated_at TIMESTAMPTZ NULL,
    approved_at TIMESTAMPTZ NULL,
    approved_by VARCHAR(50) NULL
        REFERENCES users(user_id) ON DELETE SET NULL,
    published_at TIMESTAMPTZ NULL,
    published_by VARCHAR(50) NULL
        REFERENCES users(user_id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT ck_payroll_runs_status CHECK (status IN (
        'draft', 'calculated', 'approved', 'published'
    ))
);

CREATE INDEX IF NOT EXISTS ix_payroll_runs_period
    ON payroll_runs (period_id);
CREATE INDEX IF NOT EXISTS ix_payroll_runs_status
    ON payroll_runs (status);

CREATE TABLE IF NOT EXISTS payroll_results (
    id SERIAL PRIMARY KEY,
    run_id INTEGER NOT NULL
        REFERENCES payroll_runs(id) ON DELETE CASCADE,
    user_id VARCHAR(50) NOT NULL
        REFERENCES users(user_id) ON DELETE CASCADE,
    employee_name VARCHAR(200) NOT NULL DEFAULT '',
    membership_type_code VARCHAR(10) NULL,
    covered_days INTEGER NOT NULL DEFAULT 0,
    month_days INTEGER NOT NULL DEFAULT 30,
    gross_earnings NUMERIC(18, 4) NOT NULL DEFAULT 0,
    total_deductions NUMERIC(18, 4) NOT NULL DEFAULT 0,
    net_pay NUMERIC(18, 4) NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_payroll_results_run_user UNIQUE (run_id, user_id)
);

CREATE INDEX IF NOT EXISTS ix_payroll_results_run
    ON payroll_results (run_id);
CREATE INDEX IF NOT EXISTS ix_payroll_results_user
    ON payroll_results (user_id);

CREATE TABLE IF NOT EXISTS payroll_result_items (
    id SERIAL PRIMARY KEY,
    result_id INTEGER NOT NULL
        REFERENCES payroll_results(id) ON DELETE CASCADE,
    component_id INTEGER NULL
        REFERENCES payroll_components(id) ON DELETE SET NULL,
    component_code VARCHAR(40) NOT NULL,
    component_name VARCHAR(120) NOT NULL,
    kind VARCHAR(20) NOT NULL,
    amount NUMERIC(18, 4) NOT NULL DEFAULT 0,
    quantity NUMERIC(18, 4) NULL,
    unit_amount NUMERIC(18, 4) NULL,
    calc_note TEXT NULL,
    subject_to_insurance BOOLEAN NOT NULL DEFAULT FALSE,
    subject_to_tax BOOLEAN NOT NULL DEFAULT FALSE,
    sort_order INTEGER NOT NULL DEFAULT 100,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_payroll_result_items_result
    ON payroll_result_items (result_id);

CREATE TABLE IF NOT EXISTS payroll_manual_entries (
    id SERIAL PRIMARY KEY,
    run_id INTEGER NOT NULL
        REFERENCES payroll_runs(id) ON DELETE CASCADE,
    user_id VARCHAR(50) NOT NULL
        REFERENCES users(user_id) ON DELETE CASCADE,
    component_code VARCHAR(40) NOT NULL DEFAULT 'SHIFT',
    amount NUMERIC(18, 4) NOT NULL DEFAULT 0,
    quantity NUMERIC(18, 4) NULL,
    note TEXT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_payroll_manual_run_user_comp UNIQUE (run_id, user_id, component_code)
);

CREATE INDEX IF NOT EXISTS ix_payroll_manual_run
    ON payroll_manual_entries (run_id);

-- Seed default components
INSERT INTO payroll_components (code, name, kind, calc_mode, subject_to_insurance, subject_to_tax, sort_order)
VALUES
    ('DAILY_WAGE', 'حقوق روزانه', 'earning', 'daily_x_covered', TRUE, TRUE, 10),
    ('SHIFT', 'نوبت‌کاری', 'earning', 'manual', TRUE, TRUE, 20),
    ('FRIDAY_WORK', 'جمعه‌کاری', 'earning', 'friday_attendance', TRUE, TRUE, 30),
    ('HOUSING', 'حق مسکن', 'earning', 'fixed_monthly_prorata', TRUE, TRUE, 40),
    ('MARRIAGE', 'حق تأهل', 'earning', 'fixed_monthly_prorata', TRUE, TRUE, 50),
    ('WORKER_VOUCHER', 'بن کارگری', 'earning', 'fixed_monthly_prorata', TRUE, TRUE, 60),
    ('SENIORITY', 'پایه سنوات', 'earning', 'seniority_chain', TRUE, TRUE, 70),
    ('BONUS', 'پاداش', 'earning', 'policy_bonus', TRUE, TRUE, 80),
    ('EIDI', 'عیدی', 'earning', 'policy_eidi', TRUE, TRUE, 90),
    ('INSURANCE_EMPLOYEE', 'بیمه سهم کارمند', 'deduction', 'percent_insurance', FALSE, FALSE, 200),
    ('TAX', 'مالیات', 'deduction', 'percent_tax', FALSE, FALSE, 210)
ON CONFLICT (code) DO NOTHING;

INSERT INTO payroll_rate_settings (
    insurance_employee_pct, tax_pct, friday_coefficient,
    eidi_payment_month, bonus_payment_month, eidi_day_factor, bonus_day_factor, hours_per_day
)
SELECT 7, 0, 1.96, 12, 12, 60, 0, 7.3333
WHERE NOT EXISTS (SELECT 1 FROM payroll_rate_settings);

-- قوانین رسمی پایه سنوات (گروه ۱) — قابل ویرایش از UI سیاست
INSERT INTO payroll_annual_laws (
    year_j, new_seniority_daily, wage_increase_factor,
    effective_from, version, source_reference, status
)
VALUES
    (1391, 2500, 1.07, DATE '2012-03-20', 'official', 'بخشنامه مزد ۱۳۹۱ — پایه سنوات گروه ۱', 'active'),
    (1392, 3000, 1.10, DATE '2013-03-21', 'official', 'بخشنامه مزد ۱۳۹۲', 'active'),
    (1393, 6000, 1.14, DATE '2014-03-21', 'official', 'بخشنامه مزد ۱۳۹۳', 'active'),
    (1394, 10000, 1.14, DATE '2015-03-21', 'official', 'بخشنامه مزد ۱۳۹۴', 'active'),
    (1395, 10000, 1.14, DATE '2016-03-20', 'official', 'بخشنامه مزد ۱۳۹۵', 'active'),
    (1396, 17000, 1.12, DATE '2017-03-21', 'official', 'بخشنامه مزد ۱۳۹۶ — سایر سطوح ۱۲٪', 'active'),
    (1397, 17000, 1.104, DATE '2018-03-21', 'official', 'بخشنامه مزد ۱۳۹۷ — سایر سطوح ۱۰٫۴٪', 'active'),
    (1398, 23333, 1.13, DATE '2019-03-21', 'official', 'بخشنامه مزد ۱۳۹۸ — سایر سطوح ۱۳٪', 'active'),
    (1399, 33333, 1.15, DATE '2020-03-20', 'official', 'بخشنامه مزد ۱۳۹۹ — سایر سطوح ۱۵٪', 'active'),
    (1400, 46667, 1.26, DATE '2021-03-21', 'official', 'بخشنامه مزد ۱۴۰۰ — سایر سطوح ۲۶٪', 'active'),
    (1401, 70000, 1.38, DATE '2022-03-21', 'official', 'بخشنامه مزد ۱۴۰۱ — سایر سطوح ۳۸٪', 'active'),
    (1402, 70000, 1.21, DATE '2023-03-21', 'official', 'بخشنامه مزد ۱۴۰۲ — سایر سطوح ۲۱٪', 'active'),
    (1403, 70000, 1.22, DATE '2024-03-20', 'official', 'بخشنامه مزد ۱۴۰۳ — سایر سطوح ۲۲٪', 'active'),
    (1404, 94000, 1.32, DATE '2025-03-21', 'official', 'بخشنامه مزد ۱۴۰۴ — سایر سطوح ۳۲٪', 'active'),
    (1405, 166667, 1.45, DATE '2026-03-21', 'official', 'بخشنامه مزد ۱۴۰۵ — سایر سطوح ۴۵٪', 'active')
ON CONFLICT (year_j, version) DO NOTHING;

COMMIT;
