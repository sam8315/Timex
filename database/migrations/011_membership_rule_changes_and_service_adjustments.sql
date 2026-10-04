-- Retroactive membership rule change requests + service_adjustments
-- Tables are also created via SQLAlchemy models / create_all.

CREATE TABLE IF NOT EXISTS membership_rule_change_requests (
    id SERIAL PRIMARY KEY,
    membership_type_code VARCHAR(6) NOT NULL
        REFERENCES membership_types(code) ON DELETE CASCADE,
    rule_id INTEGER NULL
        REFERENCES membership_type_rules(id) ON DELETE SET NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'draft',
    preview_json TEXT NULL,
    affected_count INTEGER NOT NULL DEFAULT 0,
    created_by VARCHAR(50) NULL,
    confirmed_by VARCHAR(50) NULL,
    confirmed_at TIMESTAMPTZ NULL,
    applied_at TIMESTAMPTZ NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS membership_rule_change_audit (
    id SERIAL PRIMARY KEY,
    request_id INTEGER NOT NULL
        REFERENCES membership_rule_change_requests(id) ON DELETE CASCADE,
    contract_id INTEGER NULL,
    user_id VARCHAR(50) NULL,
    before_json TEXT NULL,
    after_json TEXT NULL,
    actor VARCHAR(50) NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS service_adjustments (
    id SERIAL PRIMARY KEY,
    employee_id VARCHAR(50) NOT NULL
        REFERENCES users(user_id) ON DELETE CASCADE,
    contract_id INTEGER NULL
        REFERENCES contracts(id) ON DELETE SET NULL,
    adjustment_type VARCHAR(40) NOT NULL,
    years INTEGER NOT NULL DEFAULT 0,
    months INTEGER NOT NULL DEFAULT 0,
    days INTEGER NOT NULL DEFAULT 0,
    title VARCHAR(200) NULL,
    reason TEXT NULL,
    effective_date DATE NOT NULL,
    description TEXT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'active',
    created_by VARCHAR(50) NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    corrects_adjustment_id INTEGER NULL
        REFERENCES service_adjustments(id) ON DELETE SET NULL,
    CONSTRAINT ck_service_adjustment_type CHECK (
        adjustment_type IN (
            'service_deduction', 'extra_service', 'positive_seniority'
        )
    ),
    CONSTRAINT ck_service_adjustment_status CHECK (
        status IN ('active', 'corrected', 'void')
    )
);
