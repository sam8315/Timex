-- Append-only audit history for employee relatives
-- Idempotent: safe on existing production DBs.

BEGIN;

CREATE TABLE IF NOT EXISTS employee_relative_history (
    id SERIAL PRIMARY KEY,
    relative_id INTEGER NOT NULL,
    user_id VARCHAR(50) NOT NULL,
    action VARCHAR(20) NOT NULL,
    changed_by_user_id VARCHAR(50),
    changed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    detail TEXT,
    first_name VARCHAR(100),
    last_name VARCHAR(100),
    father_name VARCHAR(100),
    national_code VARCHAR(10),
    birth_date DATE,
    gender VARCHAR(1),
    relationship_type VARCHAR(20),
    marital_status VARCHAR(1),
    marriage_date DATE,
    divorce_date DATE,
    death_date DATE,
    is_studying BOOLEAN,
    study_start_date DATE,
    study_end_date DATE,
    employment_status VARCHAR(20),
    insurance_status VARCHAR(20),
    is_disabled BOOLEAN,
    disability_start_date DATE,
    disability_end_date DATE,
    notes TEXT,
    status VARCHAR(20),
    rejection_reason TEXT
);

CREATE INDEX IF NOT EXISTS ix_employee_relative_history_relative_id
    ON employee_relative_history (relative_id);
CREATE INDEX IF NOT EXISTS ix_employee_relative_history_user_id
    ON employee_relative_history (user_id);
CREATE INDEX IF NOT EXISTS ix_employee_relative_history_action
    ON employee_relative_history (action);
CREATE INDEX IF NOT EXISTS ix_employee_relative_history_changed_by
    ON employee_relative_history (changed_by_user_id);
CREATE INDEX IF NOT EXISTS ix_employee_relative_history_changed_at
    ON employee_relative_history (changed_at DESC);

ALTER TABLE employee_relative_history
    DROP CONSTRAINT IF EXISTS ck_employee_relative_history_action;
ALTER TABLE employee_relative_history
    ADD CONSTRAINT ck_employee_relative_history_action
    CHECK (action IN (
        'CREATE', 'UPDATE', 'DELETE', 'VERIFY', 'REJECT',
        'STUDY_EXPIRE', 'FILE_ADD', 'FILE_DELETE'
    ));

COMMENT ON TABLE employee_relative_history IS
    'Append-only relative change snapshots (no FK to relatives/users)';

COMMIT;
