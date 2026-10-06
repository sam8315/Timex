-- مبنای شروع استحقاق مرخصی وظیفه روی MembershipTypeRule
BEGIN;

ALTER TABLE membership_type_rules
    ADD COLUMN IF NOT EXISTS leave_start_date_basis VARCHAR(20);

UPDATE membership_type_rules
SET leave_start_date_basis = 'dispatch'
WHERE leave_start_date_basis IS NULL;

ALTER TABLE membership_type_rules
    ALTER COLUMN leave_start_date_basis SET DEFAULT 'dispatch';

ALTER TABLE membership_type_rules
    ALTER COLUMN leave_start_date_basis SET NOT NULL;

ALTER TABLE membership_type_rules
    DROP CONSTRAINT IF EXISTS ck_membership_rule_leave_start_basis;

ALTER TABLE membership_type_rules
    ADD CONSTRAINT ck_membership_rule_leave_start_basis
    CHECK (leave_start_date_basis IN ('dispatch', 'unit_entry', 'clinic_entry'));

COMMENT ON COLUMN membership_type_rules.leave_start_date_basis IS
    'Conscript leave entitlement start basis: dispatch | unit_entry | clinic_entry';

COMMIT;
