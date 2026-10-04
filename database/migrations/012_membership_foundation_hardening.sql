-- Foundation hardening: pending rules, behavior_profile, service_adjustment FKs RESTRICT
-- Idempotent / non-destructive. Does not rewrite contracts or leave data.

-- 1) behavior_profile on membership_types
ALTER TABLE membership_types
    ADD COLUMN IF NOT EXISTS behavior_profile VARCHAR(40) NOT NULL DEFAULT 'standard_prorate';

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'ck_membership_types_behavior_profile'
    ) THEN
        ALTER TABLE membership_types
            ADD CONSTRAINT ck_membership_types_behavior_profile
            CHECK (behavior_profile IN (
                'permanent', 'conscript', 'physician', 'standard_prorate'
            ));
    END IF;
END $$;

-- One-time backfill for legacy seed codes still on default profile
UPDATE membership_types SET behavior_profile = 'permanent'
 WHERE code = '1' AND behavior_profile = 'standard_prorate';
UPDATE membership_types SET behavior_profile = 'conscript'
 WHERE code = '2' AND behavior_profile = 'standard_prorate';
UPDATE membership_types SET behavior_profile = 'physician'
 WHERE code = '5' AND behavior_profile = 'standard_prorate';
-- 3,4,6,7 remain standard_prorate

-- 2) Expand rule status check to include pending
ALTER TABLE membership_type_rules
    DROP CONSTRAINT IF EXISTS ck_membership_rule_status;
ALTER TABLE membership_type_rules
    ADD CONSTRAINT ck_membership_rule_status
    CHECK (status IN ('pending', 'scheduled', 'active', 'superseded'));

-- 3) service_adjustments FKs → RESTRICT (employee + contract)
DO $$
DECLARE
    cname text;
BEGIN
    SELECT tc.constraint_name INTO cname
    FROM information_schema.table_constraints tc
    JOIN information_schema.key_column_usage kcu
      ON tc.constraint_name = kcu.constraint_name
     AND tc.table_schema = kcu.table_schema
    WHERE tc.table_name = 'service_adjustments'
      AND tc.constraint_type = 'FOREIGN KEY'
      AND kcu.column_name = 'employee_id'
    LIMIT 1;
    IF cname IS NOT NULL THEN
        EXECUTE format('ALTER TABLE service_adjustments DROP CONSTRAINT %I', cname);
    END IF;
    ALTER TABLE service_adjustments
        ADD CONSTRAINT fk_service_adjustments_employee_id
        FOREIGN KEY (employee_id) REFERENCES users(user_id) ON DELETE RESTRICT;

    SELECT tc.constraint_name INTO cname
    FROM information_schema.table_constraints tc
    JOIN information_schema.key_column_usage kcu
      ON tc.constraint_name = kcu.constraint_name
     AND tc.table_schema = kcu.table_schema
    WHERE tc.table_name = 'service_adjustments'
      AND tc.constraint_type = 'FOREIGN KEY'
      AND kcu.column_name = 'contract_id'
    LIMIT 1;
    IF cname IS NOT NULL THEN
        EXECUTE format('ALTER TABLE service_adjustments DROP CONSTRAINT %I', cname);
    END IF;
    ALTER TABLE service_adjustments
        ADD CONSTRAINT fk_service_adjustments_contract_id
        FOREIGN KEY (contract_id) REFERENCES contracts(id) ON DELETE RESTRICT;
END $$;
