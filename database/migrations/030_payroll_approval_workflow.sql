-- گردش تأیید چندمرحله‌ای لیست حقوق.
-- تنظیمات مراحل الگو است؛ با شروع گردش هر لیست، مراحل در payroll_run_approval_steps ثابت می‌شود.

CREATE TABLE IF NOT EXISTS payroll_approval_step_settings (
    id SERIAL PRIMARY KEY,
    step_order INTEGER NOT NULL,
    title VARCHAR(120) NOT NULL,
    approver_user_id VARCHAR(50) REFERENCES users(user_id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_payroll_approval_step_settings_order
        UNIQUE (step_order) DEFERRABLE INITIALLY DEFERRED,
    CONSTRAINT ck_payroll_approval_step_settings_order CHECK (step_order >= 1),
    CONSTRAINT ck_payroll_approval_step_settings_title CHECK (length(trim(title)) > 0)
);

CREATE INDEX IF NOT EXISTS ix_payroll_approval_step_settings_approver_user_id
    ON payroll_approval_step_settings (approver_user_id);

CREATE TABLE IF NOT EXISTS payroll_run_approval_steps (
    id SERIAL PRIMARY KEY,
    run_id INTEGER NOT NULL REFERENCES payroll_runs(id) ON DELETE CASCADE,
    step_order INTEGER NOT NULL,
    title VARCHAR(120) NOT NULL,
    approver_user_id VARCHAR(50) REFERENCES users(user_id) ON DELETE SET NULL,
    approved_by VARCHAR(50) REFERENCES users(user_id) ON DELETE SET NULL,
    approved_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_payroll_run_approval_steps_order UNIQUE (run_id, step_order),
    CONSTRAINT ck_payroll_run_approval_steps_order CHECK (step_order >= 1),
    CONSTRAINT ck_payroll_run_approval_steps_title CHECK (length(trim(title)) > 0)
);

CREATE INDEX IF NOT EXISTS ix_payroll_run_approval_steps_run_id
    ON payroll_run_approval_steps (run_id);
CREATE INDEX IF NOT EXISTS ix_payroll_run_approval_steps_approver_user_id
    ON payroll_run_approval_steps (approver_user_id);

-- مراحل پیش‌فرض، فقط اگر هنوز تنظیمی نیست.
INSERT INTO payroll_approval_step_settings (step_order, title)
SELECT v.step_order, v.title
FROM (VALUES
    (1, 'نیروی انسانی'),
    (2, 'حسابدار'),
    (3, 'مدیر مالی'),
    (4, 'مدیر درمانگاه')
) AS v(step_order, title)
WHERE NOT EXISTS (SELECT 1 FROM payroll_approval_step_settings);

-- اجرای قدیمی تأییدشده/منتشرشده: یک مرحلهٔ تک‌تأییدی با همان تأییدکننده و زمان قبلی.
INSERT INTO payroll_run_approval_steps
    (run_id, step_order, title, approver_user_id, approved_by, approved_at)
SELECT r.id, 1, 'تأیید', r.approved_by, r.approved_by, r.approved_at
FROM payroll_runs r
WHERE r.status IN ('approved', 'published')
  AND NOT EXISTS (
      SELECT 1 FROM payroll_run_approval_steps s WHERE s.run_id = r.id
  );