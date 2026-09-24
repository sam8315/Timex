BEGIN;

-- ============================================
-- Hourly Mission feature (Phase 1 — revised: scoped policies)
-- Adds: hourly_missions, hourly_mission_policies
-- Independent from LeaveRequest (hourly leave) and DailyStatus (daily mission)
--
-- NOTE: This migration existed only on the local `work` branch (never pushed
--       to origin/work), so it is edited in place. The original global
--       PolicyValue seed (category='hourly_mission') was abandoned in favor
--       of scoped HourlyMissionPolicy rows (group + employee override).
--       Cleanup statements below remove any local leftovers idempotently.
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
-- Scoped hourly-mission policies (mirrors hourly_leave_policies)
-- ============================================
CREATE TABLE IF NOT EXISTS hourly_mission_policies (
    id SERIAL PRIMARY KEY,
    employment_type_code VARCHAR(10) NOT NULL,
    user_id VARCHAR(50),
    effective_from_date DATE NOT NULL,
    effective_to_date DATE,
    is_active BOOLEAN DEFAULT TRUE NOT NULL,

    -- Four boolean flags
    enabled BOOLEAN DEFAULT TRUE NOT NULL,
    working_hours_only BOOLEAN DEFAULT TRUE NOT NULL,
    allowed_on_holidays BOOLEAN DEFAULT FALSE NOT NULL,
    deduct_from_required_minutes BOOLEAN DEFAULT TRUE NOT NULL,

    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,

    CONSTRAINT fk_hourly_mission_policies_user FOREIGN KEY (user_id)
        REFERENCES users(user_id) ON DELETE CASCADE
);

-- Indexes for efficient lookups (mirrors hourly_leave_policies)
CREATE INDEX IF NOT EXISTS ix_hourly_mission_policies_emp_type ON hourly_mission_policies(employment_type_code);
CREATE INDEX IF NOT EXISTS ix_hourly_mission_policies_user ON hourly_mission_policies(user_id);
CREATE INDEX IF NOT EXISTS ix_hourly_mission_policies_from_date ON hourly_mission_policies(effective_from_date);
CREATE INDEX IF NOT EXISTS ix_hourly_mission_policies_to_date ON hourly_mission_policies(effective_to_date);
CREATE INDEX IF NOT EXISTS ix_hourly_mission_policies_active ON hourly_mission_policies(is_active);
CREATE INDEX IF NOT EXISTS ix_hourly_mission_policies_emp_type_date ON hourly_mission_policies(employment_type_code, effective_from_date);
CREATE INDEX IF NOT EXISTS ix_hourly_mission_policies_user_date ON hourly_mission_policies(user_id, effective_from_date);

-- ============================================
-- Cleanup of the abandoned global-key design (idempotent; no-op if absent)
-- ============================================
DELETE FROM policy_values WHERE parameter_key IN (
    'hourly_mission_enabled',
    'hourly_mission_working_hours_only',
    'hourly_mission_allowed_on_holidays',
    'hourly_mission_deduct_from_required_minutes'
);
DELETE FROM policies WHERE category = 'hourly_mission';

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

COMMENT ON TABLE hourly_mission_policies IS 'سیاست مأموریت ساعتی برای نوع عضویت یا override کارمند';
COMMENT ON COLUMN hourly_mission_policies.employment_type_code IS 'کد نوع عضویت: 1=رسمی، 2=وظیفه، 3=خریدخدمت، 4=قراردادی، 5=پزشک';
COMMENT ON COLUMN hourly_mission_policies.user_id IS 'اگر ست شده، این Policy فقط برای این کارمند اعمال می‌شود (Override)';
COMMENT ON COLUMN hourly_mission_policies.enabled IS 'مأموریت ساعتی فعال است';
COMMENT ON COLUMN hourly_mission_policies.working_hours_only IS 'مأموریت ساعتی فقط در ساعات موظفی مجاز است';
COMMENT ON COLUMN hourly_mission_policies.allowed_on_holidays IS 'مأموریت ساعتی در روز تعطیل مجاز است';
COMMENT ON COLUMN hourly_mission_policies.deduct_from_required_minutes IS 'مدت مأموریت ساعتی از موظفی کسر می‌شود';

COMMIT;
