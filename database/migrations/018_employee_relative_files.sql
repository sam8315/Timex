-- Multiple private file attachments for employee relatives
-- Idempotent: safe on existing production DBs.

BEGIN;

CREATE TABLE IF NOT EXISTS employee_relative_files (
    id SERIAL PRIMARY KEY,
    relative_id INTEGER NOT NULL
        REFERENCES employee_relatives (id) ON DELETE CASCADE,
    storage_key VARCHAR(255) NOT NULL,
    original_filename VARCHAR(255) NOT NULL,
    mime_type VARCHAR(100),
    size_bytes INTEGER,
    uploaded_by VARCHAR(50),
    uploaded_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    deleted_at TIMESTAMPTZ,
    deleted_by VARCHAR(50),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_employee_relative_files_relative_id
    ON employee_relative_files (relative_id);

CREATE INDEX IF NOT EXISTS ix_employee_relative_files_deleted_at
    ON employee_relative_files (deleted_at);

CREATE INDEX IF NOT EXISTS ix_employee_relative_files_relative_active
    ON employee_relative_files (relative_id)
    WHERE deleted_at IS NULL;

COMMENT ON TABLE employee_relative_files IS
    'Private attachments for employee relatives (PDF/images)';

COMMIT;
