-- Reverse 013_align_annual_leave_policy_mirrors.sql
-- Restores PolicyValue annual_leave_dept_* from _al_policy_mirror_audit_013.
-- Does not touch contracts or leave balances.

BEGIN;

UPDATE policy_values pv
SET parameter_value = a.old_value,
    updated_at = NOW()
FROM (
    SELECT DISTINCT ON (parameter_key)
        parameter_key, old_value
    FROM _al_policy_mirror_audit_013
    ORDER BY parameter_key, applied_at DESC, id DESC
) a
WHERE pv.parameter_key = a.parameter_key
  AND pv.region_code IS NULL
  AND a.old_value IS NOT NULL;

-- Rows that were inserted by 013 (old_value NULL): remove mirror only if
-- current value still equals the audited new_value.
DELETE FROM policy_values pv
USING (
    SELECT DISTINCT ON (parameter_key)
        parameter_key, new_value
    FROM _al_policy_mirror_audit_013
    WHERE old_value IS NULL
    ORDER BY parameter_key, applied_at DESC, id DESC
) a
WHERE pv.parameter_key = a.parameter_key
  AND pv.region_code IS NULL
  AND pv.parameter_value = a.new_value;

DROP TABLE IF EXISTS _al_policy_mirror_audit_013;

COMMIT;
