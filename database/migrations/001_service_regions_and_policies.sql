BEGIN;

-- The existing Employee model maps to the singular employee table.
ALTER TABLE employee ADD COLUMN region_code VARCHAR(20) DEFAULT 'NORMAL';

CREATE TABLE regions (
    id SERIAL PRIMARY KEY,
    code VARCHAR(20) UNIQUE NOT NULL,
    name VARCHAR(100) NOT NULL,
    description VARCHAR(500),
    default_annual_leave_days FLOAT DEFAULT 30.0,
    is_active BOOLEAN DEFAULT TRUE,
    sort_order INTEGER DEFAULT 0,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL
);

CREATE TABLE policies (
    id SERIAL PRIMARY KEY,
    category VARCHAR(50) NOT NULL,
    name VARCHAR(200) NOT NULL,
    description TEXT,
    is_active BOOLEAN DEFAULT TRUE,
    effective_from_year INTEGER,
    effective_to_year INTEGER,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL
);

CREATE TABLE policy_values (
    id SERIAL PRIMARY KEY,
    policy_id INTEGER NOT NULL,
    region_code VARCHAR(20),
    parameter_key VARCHAR(100) NOT NULL,
    parameter_value VARCHAR(500) NOT NULL,
    is_editable BOOLEAN DEFAULT TRUE,
    notes TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL
);

CREATE TABLE policy_audit_logs (
    id SERIAL PRIMARY KEY,
    entity_type VARCHAR(50) NOT NULL,
    entity_id VARCHAR(100),
    action VARCHAR(50) NOT NULL,
    old_value TEXT,
    new_value TEXT,
    changed_by VARCHAR(50),
    reason TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL
);

CREATE TABLE employee_regions (
    id SERIAL PRIMARY KEY,
    user_id VARCHAR(50) NOT NULL,
    region_code VARCHAR(20) NOT NULL,
    effective_from DATE NOT NULL,
    effective_to DATE,
    approved_by VARCHAR(50),
    reason VARCHAR(500),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL
);

CREATE INDEX idx_regions_code ON regions(code);
CREATE INDEX idx_policy_values_policy_id ON policy_values(policy_id);
CREATE INDEX idx_policy_values_region ON policy_values(region_code);
CREATE INDEX idx_employee_regions_user_id ON employee_regions(user_id);
CREATE INDEX idx_policy_audit_entity ON policy_audit_logs(entity_type, entity_id);

INSERT INTO regions (code, name, description, default_annual_leave_days, sort_order) VALUES
    ('NORMAL', 'عادی', 'منطقه عادی بدون شرایط خاص', 30, 1),
    ('GRADE_1', 'درجه یک', 'منطقه بد آب و هوا درجه یک', 35, 2),
    ('GRADE_2', 'درجه دو', 'منطقه بد آب و هوا درجه دو', 40, 3),
    ('GRADE_3', 'درجه سه', 'منطقه بد آب و هوا درجه سه', 45, 4);

INSERT INTO policies (category, name, description, is_active) VALUES
    ('leave', 'سیاست مرخصی', 'سیاست کلی مرخصی شامل مرخصی استحقاقی، انتقال و بازخرید', TRUE);

INSERT INTO policy_values (
    policy_id, region_code, parameter_key, parameter_value, is_editable, notes
)
SELECT policy.id, value.region_code, value.parameter_key, value.parameter_value,
       value.is_editable, value.notes
FROM policies AS policy
CROSS JOIN (
    VALUES
        ('NORMAL', 'annual_leave_days', '30', TRUE, 'مرخصی استحقاقی منطقه عادی'),
        ('GRADE_1', 'annual_leave_days', '35', TRUE, 'مرخصی استحقاقی منطقه درجه یک'),
        ('GRADE_2', 'annual_leave_days', '40', TRUE, 'مرخصی استحقاقی منطقه درجه دو'),
        ('GRADE_3', 'annual_leave_days', '45', TRUE, 'مرخصی استحقاقی منطقه درجه سه'),
        (NULL, 'max_carry_forward', '9', TRUE, 'سقف انتقال مرخصی به سال بعد (مستقل از منطقه)'),
        (NULL, 'max_buyback', '15', TRUE, 'سقف بازخرید مرخصی (مستقل از منطقه)')
) AS value(region_code, parameter_key, parameter_value, is_editable, notes)
WHERE policy.category = 'leave' AND policy.name = 'سیاست مرخصی';

COMMIT;
