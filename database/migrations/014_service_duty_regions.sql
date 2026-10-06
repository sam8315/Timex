-- مناطق خدمت وظیفه (مدت ماه دقیق) + فیلدهای قرارداد وظیفه
BEGIN;

CREATE TABLE IF NOT EXISTS service_duty_regions (
    id SERIAL PRIMARY KEY,
    code VARCHAR(40) UNIQUE NOT NULL,
    name VARCHAR(200) NOT NULL,
    native_affects BOOLEAN NOT NULL DEFAULT FALSE,
    duration_months INTEGER NULL,
    duration_months_native INTEGER NULL,
    duration_months_non_native INTEGER NULL,
    sort_order INTEGER NOT NULL DEFAULT 0,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT ck_service_duty_region_duration CHECK (
        (
            native_affects = FALSE
            AND duration_months IS NOT NULL
            AND duration_months > 0
        )
        OR (
            native_affects = TRUE
            AND duration_months_native IS NOT NULL
            AND duration_months_native > 0
            AND duration_months_non_native IS NOT NULL
            AND duration_months_non_native > 0
        )
    )
);

CREATE INDEX IF NOT EXISTS idx_service_duty_regions_code ON service_duty_regions(code);
CREATE INDEX IF NOT EXISTS idx_service_duty_regions_active ON service_duty_regions(is_active);

-- Seed اختیاری (قابل ویرایش/حذف از UI؛ runtime وابسته نیست)
INSERT INTO service_duty_regions (
    code, name, native_affects,
    duration_months, duration_months_native, duration_months_non_native,
    sort_order, is_active
)
VALUES
    ('OPERATIONAL', 'مناطق درگیر و عملیاتی', TRUE, NULL, 15, 14, 10, TRUE),
    ('BORDER_HARSH', 'مناطق مرزی و بدآب‌وهوا', TRUE, NULL, 15, 15, 20, TRUE),
    ('NORMAL_DUTY', 'مناطق عادی', TRUE, NULL, 21, 18, 30, TRUE),
    ('AMRIYEH', 'امریه دستگاه غیرنظامی', FALSE, 24, NULL, NULL, 40, TRUE)
ON CONFLICT (code) DO NOTHING;

ALTER TABLE contracts ADD COLUMN IF NOT EXISTS dispatch_date DATE NULL;
ALTER TABLE contracts ADD COLUMN IF NOT EXISTS unit_entry_date DATE NULL;
ALTER TABLE contracts ADD COLUMN IF NOT EXISTS clinic_entry_date DATE NULL;
ALTER TABLE contracts ADD COLUMN IF NOT EXISTS is_native BOOLEAN NULL;
ALTER TABLE contracts ADD COLUMN IF NOT EXISTS service_duty_region_code VARCHAR(40) NULL;

CREATE INDEX IF NOT EXISTS idx_contracts_duty_region
    ON contracts(service_duty_region_code);

COMMIT;
