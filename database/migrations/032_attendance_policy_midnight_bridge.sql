BEGIN;

-- The midnight continuous-shift rule is a global setting stored in
-- policies/policy_values (category 'attendance_midnight_bridge'), not a
-- per-attendance-policy option. Drop the short-lived per-policy columns.

ALTER TABLE attendance_policies DROP COLUMN IF EXISTS midnight_bridge_enabled;
ALTER TABLE attendance_policies DROP COLUMN IF EXISTS midnight_bridge_before_minutes;
ALTER TABLE attendance_policies DROP COLUMN IF EXISTS midnight_bridge_after_minutes;

COMMIT;
