-- Membership types + versioned rules + reserved codes
-- Fail-closed: does not rewrite contracts / leave balances / transactions.

CREATE TABLE IF NOT EXISTS membership_types (
    code VARCHAR(6) PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    description TEXT NULL,
    sort_order INTEGER NOT NULL DEFAULT 0,
    code_locked BOOLEAN NOT NULL DEFAULT FALSE,
    behavior_profile VARCHAR(40) NOT NULL DEFAULT 'standard_prorate',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT ck_membership_types_code_positive CHECK (code ~ '^[1-9][0-9]{0,5}$'),
    CONSTRAINT ck_membership_types_behavior_profile CHECK (
        behavior_profile IN (
            'permanent', 'conscript', 'physician', 'standard_prorate'
        )
    )
);

CREATE INDEX IF NOT EXISTS ix_membership_types_is_active
    ON membership_types (is_active);

CREATE TABLE IF NOT EXISTS membership_type_rules (
    id SERIAL PRIMARY KEY,
    membership_type_code VARCHAR(6) NOT NULL
        REFERENCES membership_types(code) ON DELETE CASCADE,
    effective_from DATE NOT NULL,
    annual_leave_base INTEGER NOT NULL DEFAULT 0,
    supports_service_deduction BOOLEAN NOT NULL DEFAULT FALSE,
    supports_extra_service BOOLEAN NOT NULL DEFAULT FALSE,
    supports_positive_seniority BOOLEAN NOT NULL DEFAULT FALSE,
    status VARCHAR(20) NOT NULL DEFAULT 'active',
    supersedes_rule_id INTEGER NULL
        REFERENCES membership_type_rules(id) ON DELETE SET NULL,
    created_by VARCHAR(50) NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_membership_rule_code_effective
        UNIQUE (membership_type_code, effective_from),
    CONSTRAINT ck_membership_rule_annual_nonneg
        CHECK (annual_leave_base >= 0),
    CONSTRAINT ck_membership_rule_status
        CHECK (status IN ('pending', 'scheduled', 'active', 'superseded'))
);

CREATE INDEX IF NOT EXISTS ix_membership_type_rules_code
    ON membership_type_rules (membership_type_code);
CREATE INDEX IF NOT EXISTS ix_membership_type_rules_effective_from
    ON membership_type_rules (effective_from);

CREATE TABLE IF NOT EXISTS reserved_membership_codes (
    code VARCHAR(6) PRIMARY KEY,
    reason TEXT NULL,
    reserved_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    reserved_by VARCHAR(50) NULL
);

COMMENT ON TABLE membership_types IS 'DB-managed membership types (replaces CONTRACT_TYPES)';
COMMENT ON TABLE membership_type_rules IS 'Versioned full-snapshot membership rules';
COMMENT ON TABLE reserved_membership_codes IS 'Retired membership codes that cannot be reused';
