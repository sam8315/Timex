-- Employee relatives verification workflow (PENDING / VERIFIED / REJECTED)
-- Idempotent: safe on existing production DBs.

BEGIN;

ALTER TABLE employee_relatives
    ADD COLUMN IF NOT EXISTS status VARCHAR(20);

ALTER TABLE employee_relatives
    ADD COLUMN IF NOT EXISTS submitted_by VARCHAR(50);

ALTER TABLE employee_relatives
    ADD COLUMN IF NOT EXISTS verified_by VARCHAR(50);

ALTER TABLE employee_relatives
    ADD COLUMN IF NOT EXISTS verified_at TIMESTAMPTZ;

ALTER TABLE employee_relatives
    ADD COLUMN IF NOT EXISTS rejection_reason TEXT;

-- Existing admin-entered rows treated as verified
UPDATE employee_relatives
SET status = 'VERIFIED'
WHERE status IS NULL;

ALTER TABLE employee_relatives
    ALTER COLUMN status SET DEFAULT 'PENDING';

ALTER TABLE employee_relatives
    ALTER COLUMN status SET NOT NULL;

CREATE INDEX IF NOT EXISTS ix_employee_relatives_status
    ON employee_relatives (status);

ALTER TABLE employee_relatives
    DROP CONSTRAINT IF EXISTS ck_employee_relative_status;
ALTER TABLE employee_relatives
    ADD CONSTRAINT ck_employee_relative_status
    CHECK (status IN ('PENDING', 'VERIFIED', 'REJECTED'));

COMMENT ON COLUMN employee_relatives.status IS
    'Verification: PENDING | VERIFIED | REJECTED';

COMMIT;
