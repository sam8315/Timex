-- Separate organizational department from membership type.
-- Schema only. Does not backfill employee rows and does not invent departments.

BEGIN;

CREATE TABLE IF NOT EXISTS departments (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL UNIQUE,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_departments_is_active ON departments (is_active);

ALTER TABLE employee ADD COLUMN IF NOT EXISTS department_id INTEGER NULL;
ALTER TABLE employee ADD COLUMN IF NOT EXISTS membership_type_code VARCHAR(6) NULL;

CREATE INDEX IF NOT EXISTS ix_employee_department_id ON employee (department_id);
CREATE INDEX IF NOT EXISTS ix_employee_membership_type_code ON employee (membership_type_code);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'employee_department_id_fkey'
    ) THEN
        ALTER TABLE employee
            ADD CONSTRAINT employee_department_id_fkey
            FOREIGN KEY (department_id) REFERENCES departments (id)
            ON DELETE SET NULL;
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'fk_employee_membership_type_code'
    ) THEN
        ALTER TABLE employee
            ADD CONSTRAINT fk_employee_membership_type_code
            FOREIGN KEY (membership_type_code) REFERENCES membership_types (code)
            ON DELETE RESTRICT;
    END IF;
END $$;

COMMIT;
