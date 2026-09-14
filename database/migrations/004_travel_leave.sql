-- Travel Leave feature (مرخصی توراهی) - extension of Annual Leave (AL)

-- Reference cities (Iranian cities) - idempotent seed
CREATE TABLE IF NOT EXISTS cities (
    id SERIAL PRIMARY KEY,
    name VARCHAR(200) NOT NULL,
    province VARCHAR(200),
    latitude FLOAT,
    longitude FLOAT,
    active BOOLEAN DEFAULT TRUE,
    UNIQUE(name, province)
);

-- Ensure seed cities exist (idempotent)
INSERT INTO cities (name, province, latitude, longitude, active) VALUES
('کازرون','فارس',29.59,52.55,true),
('شیراز','فارس',29.59,52.58,true),
('بوشهر','بوشهر',28.92,50.83,true),
('یاسوج','کهگیلویه و بویراحمد',30.67,51.17,true),
('اهواز','خوزستان',31.32,48.68,true),
('اصفهان','اصفهان',32.65,51.67,true),
('تهران','تهران',35.69,51.39,true),
('قم','قم',34.64,50.88,true),
('کرمان','کرمان',30.28,57.07,true),
('بندرعباس','هرمزگان',27.18,56.28,true),
('یزد','یزد',31.89,54.36,true),
('کرمانشاه','کرمانشاه',34.32,47.07,true),
('سنندج','کردستان',35.31,46.99,true),
('تبریز','آذربایجان شرقی',38.08,46.29,true),
('ارومیه','آذربایجان غربی',37.55,45.08,true),
('رشت','گیلان',37.28,49.58,true),
('ساری','مازندران',36.55,53.06,true),
('مشهد','خراسان رضوی',36.30,59.60,true),
('زاهدان','سیستان و بلوچستان',29.49,60.88,true),
('خرم‌آباد','لرستان',33.49,48.34,true)
ON CONFLICT DO NOTHING;

-- TravelLeaveDetail: 1:1 linked to LeaveRequest
CREATE TABLE IF NOT EXISTS travel_leave_details (
    id SERIAL PRIMARY KEY,
    leave_request_id INTEGER NOT NULL UNIQUE REFERENCES leave_requests(id) ON DELETE CASCADE,
    origin_city_id INTEGER REFERENCES cities(id),
    destination_city_id INTEGER REFERENCES cities(id),
    distance_km FLOAT,
    travel_days_calculated INTEGER,
    travel_days_final INTEGER,
    travel_policy_id INTEGER REFERENCES policies(id),
    travel_policy_rule_id INTEGER,
    manual_override BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Add index for lookup by leave request
CREATE INDEX IF NOT EXISTS idx_travel_leave_request ON travel_leave_details(leave_request_id);

-- Policy distance rules can be stored in policy_values; no new table needed.
