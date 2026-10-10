-- Drop the legacy membership cache. Organizational department is department_id.
-- Applied from startup after the membership backfill. Idempotent.

ALTER TABLE employee DROP COLUMN IF EXISTS department;
