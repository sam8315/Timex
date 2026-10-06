-- Rollback leave_start_date_basis
BEGIN;

ALTER TABLE membership_type_rules
    DROP CONSTRAINT IF EXISTS ck_membership_rule_leave_start_basis;

ALTER TABLE membership_type_rules
    DROP COLUMN IF EXISTS leave_start_date_basis;

COMMIT;
