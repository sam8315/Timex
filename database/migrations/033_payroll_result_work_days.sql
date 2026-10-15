BEGIN;

-- Days worked on a payslip: covered days minus normal absence and sick days
-- not paid by the employer. NULL for results calculated before this column.

ALTER TABLE payroll_results ADD COLUMN IF NOT EXISTS work_days INTEGER;

COMMIT;
