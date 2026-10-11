-- رفتار استعلاجی و غیبت روی خود قلم. قانون‌های قبلی پیش‌فرض یک‌بار کپی می‌شوند.

ALTER TABLE payroll_components
    ADD COLUMN IF NOT EXISTS sick_mode VARCHAR(20) NOT NULL DEFAULT 'keep',
    ADD COLUMN IF NOT EXISTS absence_mode VARCHAR(20) NOT NULL DEFAULT 'keep',
    ADD COLUMN IF NOT EXISTS day_basis VARCHAR(30) NOT NULL DEFAULT 'fixed_30';

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'ck_payroll_components_sick_mode'
    ) THEN
        ALTER TABLE payroll_components
            ADD CONSTRAINT ck_payroll_components_sick_mode
            CHECK (sick_mode IN ('keep', 'prorate', 'exclude'));
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'ck_payroll_components_absence_mode'
    ) THEN
        ALTER TABLE payroll_components
            ADD CONSTRAINT ck_payroll_components_absence_mode
            CHECK (absence_mode IN ('keep', 'prorate', 'ignore'));
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'ck_payroll_components_day_basis'
    ) THEN
        ALTER TABLE payroll_components
            ADD CONSTRAINT ck_payroll_components_day_basis
            CHECK (day_basis IN ('fixed_30', 'calendar_month', 'scheduled_work'));
    END IF;
END $$;

UPDATE payroll_components AS component
SET sick_mode = rule.sick_mode,
    absence_mode = rule.absence_mode,
    day_basis = rule.basis
FROM (
    SELECT DISTINCT ON (component_id)
        component_id, sick_mode, absence_mode, basis
    FROM payroll_day_adjustment_rules
    WHERE is_active
      AND membership_type_code IS NULL
      AND user_id IS NULL
    ORDER BY component_id, effective_from DESC
) AS rule
WHERE component.id = rule.component_id
  AND component.sick_mode = 'keep'
  AND component.absence_mode = 'keep'
  AND component.day_basis = 'fixed_30';
