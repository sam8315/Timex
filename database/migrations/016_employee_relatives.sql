-- Employee relatives (policy-agnostic family facts)
-- Also created via SQLAlchemy models / create_all.
-- Idempotent: safe on existing production DBs.

BEGIN;

CREATE TABLE IF NOT EXISTS employee_relatives (
    id SERIAL PRIMARY KEY,
    user_id VARCHAR(50) NOT NULL
        REFERENCES users(user_id) ON DELETE CASCADE,
    first_name VARCHAR(100) NOT NULL,
    last_name VARCHAR(100) NOT NULL,
    father_name VARCHAR(100) NULL,
    national_code VARCHAR(10) NULL,
    birth_date DATE NULL,
    gender VARCHAR(1) NULL,
    relationship_type VARCHAR(20) NOT NULL,
    marital_status VARCHAR(1) NULL,
    marriage_date DATE NULL,
    divorce_date DATE NULL,
    death_date DATE NULL,
    is_studying BOOLEAN NULL,
    study_start_date DATE NULL,
    study_end_date DATE NULL,
    employment_status VARCHAR(20) NULL,
    insurance_status VARCHAR(20) NULL,
    is_disabled BOOLEAN NULL,
    disability_start_date DATE NULL,
    disability_end_date DATE NULL,
    notes TEXT NULL,
    deleted_at TIMESTAMPTZ NULL,
    deleted_by VARCHAR(50) NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_employee_relatives_user_id
    ON employee_relatives (user_id);

CREATE INDEX IF NOT EXISTS ix_employee_relatives_national_code
    ON employee_relatives (national_code);

CREATE INDEX IF NOT EXISTS ix_employee_relatives_relationship_type
    ON employee_relatives (relationship_type);

CREATE INDEX IF NOT EXISTS ix_employee_relatives_deleted_at
    ON employee_relatives (deleted_at);

CREATE INDEX IF NOT EXISTS ix_employee_relatives_user_relationship
    ON employee_relatives (user_id, relationship_type);

CREATE UNIQUE INDEX IF NOT EXISTS uq_employee_relative_user_national_code_active
    ON employee_relatives (user_id, national_code)
    WHERE national_code IS NOT NULL AND deleted_at IS NULL;

ALTER TABLE employee_relatives
    DROP CONSTRAINT IF EXISTS ck_employee_relative_relationship_type;
ALTER TABLE employee_relatives
    ADD CONSTRAINT ck_employee_relative_relationship_type
    CHECK (relationship_type IN (
        'SPOUSE', 'CHILD', 'FATHER', 'MOTHER', 'SIBLING', 'OTHER'
    ));

ALTER TABLE employee_relatives
    DROP CONSTRAINT IF EXISTS ck_employee_relative_gender;
ALTER TABLE employee_relatives
    ADD CONSTRAINT ck_employee_relative_gender
    CHECK (gender IS NULL OR gender IN ('M', 'F'));

ALTER TABLE employee_relatives
    DROP CONSTRAINT IF EXISTS ck_employee_relative_marital_status;
ALTER TABLE employee_relatives
    ADD CONSTRAINT ck_employee_relative_marital_status
    CHECK (marital_status IS NULL OR marital_status IN ('S', 'M', 'D', 'W'));

ALTER TABLE employee_relatives
    DROP CONSTRAINT IF EXISTS ck_employee_relative_employment_status;
ALTER TABLE employee_relatives
    ADD CONSTRAINT ck_employee_relative_employment_status
    CHECK (
        employment_status IS NULL
        OR employment_status IN ('employed', 'unemployed')
    );

ALTER TABLE employee_relatives
    DROP CONSTRAINT IF EXISTS ck_employee_relative_insurance_status;
ALTER TABLE employee_relatives
    ADD CONSTRAINT ck_employee_relative_insurance_status
    CHECK (
        insurance_status IS NULL
        OR insurance_status IN ('insured', 'uninsured')
    );

ALTER TABLE employee_relatives
    DROP CONSTRAINT IF EXISTS ck_employee_relative_national_code;
ALTER TABLE employee_relatives
    ADD CONSTRAINT ck_employee_relative_national_code
    CHECK (national_code IS NULL OR national_code ~ '^[0-9]{10}$');

ALTER TABLE employee_relatives
    DROP CONSTRAINT IF EXISTS ck_employee_relative_divorce_after_marriage;
ALTER TABLE employee_relatives
    ADD CONSTRAINT ck_employee_relative_divorce_after_marriage
    CHECK (
        divorce_date IS NULL OR marriage_date IS NULL
        OR divorce_date >= marriage_date
    );

ALTER TABLE employee_relatives
    DROP CONSTRAINT IF EXISTS ck_employee_relative_study_range;
ALTER TABLE employee_relatives
    ADD CONSTRAINT ck_employee_relative_study_range
    CHECK (
        study_end_date IS NULL OR study_start_date IS NULL
        OR study_end_date >= study_start_date
    );

ALTER TABLE employee_relatives
    DROP CONSTRAINT IF EXISTS ck_employee_relative_disability_range;
ALTER TABLE employee_relatives
    ADD CONSTRAINT ck_employee_relative_disability_range
    CHECK (
        disability_end_date IS NULL OR disability_start_date IS NULL
        OR disability_end_date >= disability_start_date
    );

ALTER TABLE employee_relatives
    DROP CONSTRAINT IF EXISTS ck_employee_relative_death_after_birth;
ALTER TABLE employee_relatives
    ADD CONSTRAINT ck_employee_relative_death_after_birth
    CHECK (
        death_date IS NULL OR birth_date IS NULL
        OR death_date >= birth_date
    );

ALTER TABLE employee_relatives
    DROP CONSTRAINT IF EXISTS ck_employee_relative_marriage_after_birth;
ALTER TABLE employee_relatives
    ADD CONSTRAINT ck_employee_relative_marriage_after_birth
    CHECK (
        marriage_date IS NULL OR birth_date IS NULL
        OR marriage_date >= birth_date
    );

COMMENT ON TABLE employee_relatives IS
    'Policy-agnostic employee family/relative facts (no allowance eligibility fields)';

COMMIT;
