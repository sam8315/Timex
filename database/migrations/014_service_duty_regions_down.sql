BEGIN;

DROP INDEX IF EXISTS idx_contracts_duty_region;
ALTER TABLE contracts DROP COLUMN IF EXISTS service_duty_region_code;
ALTER TABLE contracts DROP COLUMN IF EXISTS is_native;
ALTER TABLE contracts DROP COLUMN IF EXISTS clinic_entry_date;
ALTER TABLE contracts DROP COLUMN IF EXISTS unit_entry_date;
ALTER TABLE contracts DROP COLUMN IF EXISTS dispatch_date;

DROP TABLE IF EXISTS service_duty_regions;

COMMIT;
