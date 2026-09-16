BEGIN;

-- Travel Leave policy v2: scope configuration by contract type (Membership)
-- and marital status. Existing global rules/quota are copied to each
-- supported contract type so existing behavior is preserved.

CREATE TABLE IF NOT EXISTS travel_leave_policies (
    id SERIAL PRIMARY KEY,
    contract_type_code VARCHAR(10) NOT NULL UNIQUE,
    is_enabled BOOLEAN DEFAULT TRUE NOT NULL,
    distance_method VARCHAR(30) DEFAULT 'geographic' NOT NULL,
    description TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL
);

ALTER TABLE travel_leave_policy_rules ADD COLUMN IF NOT EXISTS policy_id INTEGER;
ALTER TABLE travel_leave_quota_settings ADD COLUMN IF NOT EXISTS policy_id INTEGER;
ALTER TABLE travel_leave_quota_settings ADD COLUMN IF NOT EXISTS marital_status VARCHAR(1);
ALTER TABLE travel_leave_details ADD COLUMN IF NOT EXISTS membership_code_snapshot VARCHAR(10);
ALTER TABLE travel_leave_details ADD COLUMN IF NOT EXISTS marital_status_snapshot VARCHAR(1);
ALTER TABLE travel_leave_details ADD COLUMN IF NOT EXISTS distance_method_snapshot VARCHAR(30);

-- parameter_key used to be globally unique; quotas are now scoped by policy/status.
ALTER TABLE travel_leave_quota_settings
    DROP CONSTRAINT IF EXISTS travel_leave_quota_settings_parameter_key_key;

INSERT INTO travel_leave_policies (contract_type_code, is_enabled, distance_method, description)
SELECT v.code, TRUE, 'geographic', 'Migrated Travel Leave policy'
FROM (VALUES ('1'), ('2'), ('3'), ('4'), ('5'), ('6'), ('7')) AS v(code)
WHERE NOT EXISTS (SELECT 1 FROM travel_leave_policies p WHERE p.contract_type_code = v.code);

-- Preserve the previous global rules by copying them to every policy.
INSERT INTO travel_leave_policy_rules
    (policy_id, min_km, max_km, travel_days, description, is_active)
SELECT p.id, r.min_km, r.max_km, r.travel_days, r.description, r.is_active
FROM travel_leave_policies p
CROSS JOIN travel_leave_policy_rules r
WHERE r.policy_id IS NULL;
DELETE FROM travel_leave_policy_rules WHERE policy_id IS NULL;

-- Preserve the previous global quota separately for unmarried/married users.
INSERT INTO travel_leave_quota_settings
    (policy_id, marital_status, annual_max_usage, description, parameter_key, parameter_value)
SELECT p.id, s.marital_status, q.annual_max_usage, q.description,
       'annual_max_usage_' || p.contract_type_code || '_' || s.marital_status,
       q.annual_max_usage::VARCHAR
FROM travel_leave_policies p
CROSS JOIN (VALUES ('S'), ('M')) AS s(marital_status)
CROSS JOIN (
    SELECT annual_max_usage, description
    FROM travel_leave_quota_settings
    WHERE policy_id IS NULL
    ORDER BY id
    LIMIT 1
) q
WHERE NOT EXISTS (
    SELECT 1 FROM travel_leave_quota_settings x
    WHERE x.policy_id = p.id AND x.marital_status = s.marital_status
);
DELETE FROM travel_leave_quota_settings WHERE policy_id IS NULL;

ALTER TABLE travel_leave_policy_rules ALTER COLUMN policy_id SET NOT NULL;
ALTER TABLE travel_leave_quota_settings ALTER COLUMN policy_id SET NOT NULL;
ALTER TABLE travel_leave_quota_settings ALTER COLUMN marital_status SET NOT NULL;

ALTER TABLE travel_leave_policy_rules
    ADD CONSTRAINT fk_tlpr_policy
    FOREIGN KEY (policy_id) REFERENCES travel_leave_policies(id) ON DELETE CASCADE;
ALTER TABLE travel_leave_quota_settings
    ADD CONSTRAINT fk_tlqs_policy
    FOREIGN KEY (policy_id) REFERENCES travel_leave_policies(id) ON DELETE CASCADE;

CREATE INDEX IF NOT EXISTS idx_tlpr_policy ON travel_leave_policy_rules(policy_id);
CREATE INDEX IF NOT EXISTS idx_tlqs_policy_status ON travel_leave_quota_settings(policy_id, marital_status);
CREATE UNIQUE INDEX IF NOT EXISTS uq_tlqs_policy_status ON travel_leave_quota_settings(policy_id, marital_status);

COMMENT ON TABLE travel_leave_policies IS 'Travel Leave policy scoped by Contract.contract_type_code';
COMMENT ON COLUMN travel_leave_policies.distance_method IS 'geographic is the currently implemented direct-distance method';

COMMIT;
