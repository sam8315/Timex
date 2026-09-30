BEGIN;

-- Derive employee service region from the city's region grade.
ALTER TABLE cities
    ADD COLUMN IF NOT EXISTS region_code VARCHAR(20) NOT NULL DEFAULT 'NORMAL';

UPDATE cities
SET region_code = 'NORMAL'
WHERE region_code IS NULL OR BTRIM(region_code) = '';

COMMIT;
