BEGIN;

-- ============================================
-- Hourly Mission feature (Phase 1)
-- Adds: hourly_missions table
-- Seeds: hourly_mission global policy + 4 parameter keys
-- Independent from LeaveRequest (hourly leave) and DailyStatus (daily mission)
-- ============================================

CREATE TABLE IF NOT EXISTS hourly_missions (
    id SERIAL PRIMARY KEY,
    user_id VARCHAR(50) NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    mission_date DATE NOT NULL,
    start_time TIME NOT NULL,
    end_time TIME NOT NULL,
    reason TEXT,
    destination VARCHAR(200),
    status VARCHAR(1) NOT NULL DEFAULT 'P',
    approved_by VARCHAR(50),
    approved_at TIMESTAMP WITH TIME ZONE,
    rejection_reason TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT ck_hourly_missions_time_order CHECK (start_time < end_time),
    CONSTRAINT ck_hourly_missions_status CHECK (status IN ('P', 'A', 'R', 'D'))
);

CREATE INDEX IF NOT EXISTS ix_hourly_missions_user_id ON hourly_missions(user_id);
CREATE INDEX IF NOT EXISTS ix_hourly_missions_mission_date ON hourly_missions(mission_date);
CREATE INDEX IF NOT EXISTS ix_hourly_missions_status ON hourly_missions(status);

-- ============================================
-- Global policy container (idempotent)
-- ============================================
INSERT INTO policies (category, name, description, is_active)
SELECT 'hourly_mission', 'سیاست مأموریت ساعتی',
       'تنظیمات کلی مأموریت ساعتی (فعال بودن، ساعات موظفی، روز تعطیل، کسر از موظفی)', TRUE
WHERE NOT EXISTS (SELECT 1 FROM policies WHERE category = 'hourly_mission');

-- Four global settings (idempotent: only missing keys are inserted)
INSERT INTO policy_values (
    policy_id, region_code, parameter_key, parameter_value, is_editable, notes
)
SELECT p.id, NULL, v.parameter_key, v.parameter_value, TRUE, v.notes
FROM policies p
CROSS JOIN (
    VALUES
        ('hourly_mission_enabled', 'true', 'مأموریت ساعتی فعال است'),
        ('hourly_mission_working_hours_only', 'true', 'مأموریت ساعتی فقط در ساعات موظفی مجاز است'),
        ('hourly_mission_allowed_on_holidays', 'false', 'مأموریت ساعتی در روز تعطیل مجاز است'),
        ('hourly_mission_deduct_from_required_minutes', 'true', 'مدت مأموریت ساعتی از موظفی کسر می‌شود')
) AS v(parameter_key, parameter_value, notes)
WHERE p.category = 'hourly_mission'
  AND NOT EXISTS (
      SELECT 1 FROM policy_values pv
      WHERE pv.policy_id = p.id
        AND pv.parameter_key = v.parameter_key
        AND pv.region_code IS NULL
  );

-- ============================================
-- Comments (Persian)
-- ============================================
COMMENT ON TABLE hourly_missions IS 'مأموریت ساعتی کارمندان (مستقل از مرخصی و وضعیت روزانه)';
COMMENT ON COLUMN hourly_missions.mission_date IS 'تاریخ مأموریت';
COMMENT ON COLUMN hourly_missions.start_time IS 'ساعت شروع مأموریت';
COMMENT ON COLUMN hourly_missions.end_time IS 'ساعت پایان مأموریت (باید بعد از start باشد)';
COMMENT ON COLUMN hourly_missions.destination IS 'مقصد مأموریت (اختیاری)';
COMMENT ON COLUMN hourly_missions.status IS 'وضعیت: P=در انتظار، A=تایید شده، R=رد شده، D=لغو شده';
COMMENT ON COLUMN hourly_missions.approved_by IS 'شناسه تأییدکننده';
COMMENT ON COLUMN hourly_missions.rejection_reason IS 'دلیل رد شدن درخواست';

COMMIT;
