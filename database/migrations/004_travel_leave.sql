BEGIN;

-- ============================================
-- Travel Leave feature
-- Adds: cities, employee_service_locations,
--        travel_leave_details,
--        travel_leave_policy_rules,
--        travel_leave_quota_settings
-- ============================================

-- Reference cities
CREATE TABLE IF NOT EXISTS cities (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    province VARCHAR(100),
    latitude FLOAT NOT NULL,
    longitude FLOAT NOT NULL,
    is_active BOOLEAN DEFAULT TRUE NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL
);

-- Existing installations may already have a legacy `cities` table.
-- Check/add required columns before any ORM query or index/seed depends on them.
ALTER TABLE cities ADD COLUMN IF NOT EXISTS province VARCHAR(100);
ALTER TABLE cities ADD COLUMN IF NOT EXISTS latitude FLOAT;
ALTER TABLE cities ADD COLUMN IF NOT EXISTS longitude FLOAT;
ALTER TABLE cities ADD COLUMN IF NOT EXISTS is_active BOOLEAN DEFAULT TRUE;
ALTER TABLE cities ADD COLUMN IF NOT EXISTS created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP;
ALTER TABLE cities ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP;

CREATE INDEX IF NOT EXISTS idx_cities_name ON cities(name);
CREATE INDEX IF NOT EXISTS idx_cities_active ON cities(is_active);

-- Effective service locations for employees
CREATE TABLE IF NOT EXISTS employee_service_locations (
    id SERIAL PRIMARY KEY,
    user_id VARCHAR(50) NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    city_id INTEGER NOT NULL REFERENCES cities(id) ON DELETE RESTRICT,
    address_text TEXT,
    effective_from DATE NOT NULL,
    effective_to DATE,
    created_by VARCHAR(50),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_esl_user_id ON employee_service_locations(user_id);
CREATE INDEX IF NOT EXISTS idx_esl_city_id ON employee_service_locations(city_id);
CREATE INDEX IF NOT EXISTS idx_esl_effective ON employee_service_locations(user_id, effective_from, effective_to);

-- Travel Leave detail (1:1 with leave_requests)
CREATE TABLE IF NOT EXISTS travel_leave_details (
    id SERIAL PRIMARY KEY,
    leave_request_id INTEGER NOT NULL UNIQUE REFERENCES leave_requests(id) ON DELETE CASCADE,

    -- Origin snapshot
    origin_service_location_id INTEGER REFERENCES employee_service_locations(id),
    origin_city_id INTEGER REFERENCES cities(id),
    origin_city_name_snapshot VARCHAR(100),
    origin_latitude_snapshot FLOAT,
    origin_longitude_snapshot FLOAT,

    -- Destination snapshot
    destination_city_id INTEGER NOT NULL REFERENCES cities(id),
    destination_city_name_snapshot VARCHAR(100) NOT NULL,
    destination_province_snapshot VARCHAR(100),
    destination_latitude_snapshot FLOAT NOT NULL,
    destination_longitude_snapshot FLOAT NOT NULL,

    -- Calculation
    distance_km FLOAT NOT NULL,
    calculated_travel_days INTEGER NOT NULL,
    final_travel_days INTEGER NOT NULL,

    -- Manual override
    manual_override BOOLEAN DEFAULT FALSE NOT NULL,
    override_reason TEXT,
    overridden_by VARCHAR(50),
    overridden_at TIMESTAMP WITH TIME ZONE,

    -- Policy snapshots
    policy_id INTEGER,
    policy_rule_id INTEGER,
    annual_max_usage_snapshot INTEGER,
    rule_min_km_snapshot FLOAT,
    rule_max_km_snapshot FLOAT,
    rule_travel_days_snapshot INTEGER,

    -- Jalali year for quota
    jalali_year INTEGER NOT NULL,

    -- Lifecycle timestamps
    calculated_at TIMESTAMP WITH TIME ZONE,
    approved_at TIMESTAMP WITH TIME ZONE,

    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_tld_leave_request ON travel_leave_details(leave_request_id);
CREATE INDEX IF NOT EXISTS idx_tld_jalali_year ON travel_leave_details(jalali_year);

-- Travel Leave distance-band rules
CREATE TABLE IF NOT EXISTS travel_leave_policy_rules (
    id SERIAL PRIMARY KEY,
    min_km FLOAT NOT NULL,
    max_km FLOAT NOT NULL,
    travel_days INTEGER NOT NULL,
    description TEXT,
    is_active INTEGER DEFAULT 1 NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL
);

-- Travel Leave annual quota setting
CREATE TABLE IF NOT EXISTS travel_leave_quota_settings (
    id SERIAL PRIMARY KEY,
    annual_max_usage INTEGER DEFAULT 3 NOT NULL,
    description TEXT,
    parameter_key VARCHAR(100) NOT NULL UNIQUE,
    parameter_value VARCHAR(50) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL
);

-- ============================================
-- Seed reference data (idempotent)
-- ============================================

-- Seed major Iranian cities (idempotent)
INSERT INTO cities (name, province, latitude, longitude, is_active)
SELECT * FROM (VALUES
    ('Tehran', 'Tehran', 35.6892, 51.3890, TRUE),
    ('Mashhad', 'Razavi Khorasan', 36.2972, 59.6067, TRUE),
    ('Isfahan', 'Isfahan', 32.6546, 51.6680, TRUE),
    ('Karaj', 'Alborz', 35.8400, 50.9391, TRUE),
    ('Shiraz', 'Fars', 29.5918, 52.5836, TRUE),
    ('Tabriz', 'East Azerbaijan', 38.0800, 46.2919, TRUE),
    ('Ahvaz', 'Khuzestan', 31.3183, 48.6706, TRUE),
    ('Qom', 'Qom', 34.6416, 50.8764, TRUE),
    ('Kermanshah', 'Kermanshah', 34.3142, 47.0650, TRUE),
    ('Rasht', 'Gilan', 37.2808, 49.5875, TRUE),
    ('Bandar Abbas', 'Hormozgan', 27.1832, 56.2764, TRUE),
    ('Kerman', 'Kerman', 30.2839, 57.0834, TRUE),
    ('Urmia', 'West Azerbaijan', 37.5527, 45.0761, TRUE),
    ('Yazd', 'Yazd', 31.8974, 54.3569, TRUE),
    ('Zahedan', 'Sistan and Baluchestan', 29.4963, 60.8635, TRUE),
    ('Arak', 'Markazi', 34.0918, 49.6892, TRUE),
    ('Bandar-e Anzali', 'Gilan', 37.4722, 49.4684, TRUE),
    ('Bushehr', 'Bushehr', 28.9274, 50.8404, TRUE),
    ('Hamadan', 'Hamedan', 34.7990, 48.5146, TRUE),
    ('Ardabil', 'Ardabil', 38.2498, 48.2933, TRUE)
) AS v(name, province, latitude, longitude, is_active)
WHERE NOT EXISTS (SELECT 1 FROM cities LIMIT 1);

-- Seed default distance-band rules (idempotent: only if table empty)
INSERT INTO travel_leave_policy_rules (min_km, max_km, travel_days, description, is_active)
SELECT * FROM (VALUES
    (0.0, 199.99, 0, 'Below 200 km — ineligible', 1),
    (200.0, 500.0, 1, '200–500 km — 1 travel day', 1),
    (500.01, 1500.0, 2, '501–1500 km — 2 travel days', 1),
    (1500.01, 99999.0, 3, 'Above 1500 km — 3 travel days', 1)
) AS v(min_km, max_km, travel_days, description, is_active)
WHERE NOT EXISTS (SELECT 1 FROM travel_leave_policy_rules LIMIT 1);

-- Seed default quota (idempotent)
INSERT INTO travel_leave_quota_settings (annual_max_usage, description, parameter_key, parameter_value)
SELECT 3, 'Max approved travel leave uses per Jalali year', 'annual_max_usage', '3'
WHERE NOT EXISTS (SELECT 1 FROM travel_leave_quota_settings LIMIT 1);

-- Comments
COMMENT ON TABLE cities IS 'Reference cities for Travel Leave origin/destination';
COMMENT ON TABLE employee_service_locations IS 'Effective service-location history per employee';
COMMENT ON TABLE travel_leave_details IS 'Travel Leave calculation snapshot (1:1 with leave_requests)';
COMMENT ON TABLE travel_leave_policy_rules IS 'Distance-band rules for Travel Leave day calculation';
COMMENT ON TABLE travel_leave_quota_settings IS 'Annual Travel Leave usage quota configuration';

COMMIT;
