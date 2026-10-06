-- Align PolicyValue annual_leave_dept_* compatibility mirrors to
-- MembershipTypeRule.annual_leave_base (authoritative live SoT).
--
-- Scope: leave PolicyValue keys only. Does NOT rewrite contracts,
-- leave balances, or MembershipTypeRule rows.
--
-- Physician (code 5): Production drift annual_leave_dept_5=30 vs seed
-- Rule base=0 is the primary conflict this migration clears for dual-run.
-- Historical Contract.annual_leave_days snapshots are intentionally left
-- unchanged (Current Behavior charge snapshot).
--
-- Reversible: see 013_align_annual_leave_policy_mirrors_down.sql
-- (restores prior mirror values from audit backup table if present).

BEGIN;

CREATE TABLE IF NOT EXISTS _al_policy_mirror_audit_013 (
    id              SERIAL PRIMARY KEY,
    membership_code VARCHAR(16) NOT NULL,
    parameter_key   VARCHAR(80) NOT NULL,
    old_value       TEXT,
    new_value       TEXT NOT NULL,
    rule_base       INTEGER NOT NULL,
    applied_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Backup + update existing mirrors that diverge from active Rule base
WITH active_rules AS (
    SELECT DISTINCT ON (membership_type_code)
        membership_type_code AS code,
        annual_leave_base AS rule_base
    FROM membership_type_rules
    WHERE status = 'active'
    ORDER BY membership_type_code, effective_from DESC, id DESC
),
leave_policy AS (
    SELECT id AS policy_id
    FROM policies
    WHERE category = 'leave'
    ORDER BY id ASC
    LIMIT 1
),
targets AS (
    SELECT
        lp.policy_id,
        ar.code,
        ar.rule_base,
        ('annual_leave_dept_' || ar.code) AS parameter_key,
        pv.id AS pv_id,
        pv.parameter_value AS old_value
    FROM active_rules ar
    CROSS JOIN leave_policy lp
    LEFT JOIN policy_values pv
      ON pv.policy_id = lp.policy_id
     AND pv.parameter_key = ('annual_leave_dept_' || ar.code)
     AND pv.region_code IS NULL
)
INSERT INTO _al_policy_mirror_audit_013 (
    membership_code, parameter_key, old_value, new_value, rule_base
)
SELECT
    t.code,
    t.parameter_key,
    t.old_value,
    t.rule_base::text,
    t.rule_base
FROM targets t
WHERE t.old_value IS DISTINCT FROM t.rule_base::text;

WITH active_rules AS (
    SELECT DISTINCT ON (membership_type_code)
        membership_type_code AS code,
        annual_leave_base AS rule_base
    FROM membership_type_rules
    WHERE status = 'active'
    ORDER BY membership_type_code, effective_from DESC, id DESC
),
leave_policy AS (
    SELECT id AS policy_id
    FROM policies
    WHERE category = 'leave'
    ORDER BY id ASC
    LIMIT 1
)
UPDATE policy_values pv
SET parameter_value = ar.rule_base::text,
    notes = 'compat mirror of MembershipTypeRule.annual_leave_base code='
            || ar.code,
    updated_at = NOW()
FROM active_rules ar, leave_policy lp
WHERE pv.policy_id = lp.policy_id
  AND pv.parameter_key = ('annual_leave_dept_' || ar.code)
  AND pv.region_code IS NULL
  AND pv.parameter_value IS DISTINCT FROM ar.rule_base::text;

-- Insert missing mirrors
WITH active_rules AS (
    SELECT DISTINCT ON (membership_type_code)
        membership_type_code AS code,
        annual_leave_base AS rule_base
    FROM membership_type_rules
    WHERE status = 'active'
    ORDER BY membership_type_code, effective_from DESC, id DESC
),
leave_policy AS (
    SELECT id AS policy_id
    FROM policies
    WHERE category = 'leave'
    ORDER BY id ASC
    LIMIT 1
)
INSERT INTO policy_values (
    policy_id, parameter_key, parameter_value,
    region_code, notes, is_editable, created_at, updated_at
)
SELECT
    lp.policy_id,
    'annual_leave_dept_' || ar.code,
    ar.rule_base::text,
    NULL,
    'compat mirror of MembershipTypeRule.annual_leave_base code=' || ar.code,
    TRUE,
    NOW(),
    NOW()
FROM active_rules ar
CROSS JOIN leave_policy lp
WHERE NOT EXISTS (
    SELECT 1 FROM policy_values pv
    WHERE pv.policy_id = lp.policy_id
      AND pv.parameter_key = ('annual_leave_dept_' || ar.code)
      AND pv.region_code IS NULL
);

COMMIT;
