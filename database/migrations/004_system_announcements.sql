BEGIN;

CREATE TABLE system_announcements (
    id SERIAL PRIMARY KEY,
    version VARCHAR(30),
    title VARCHAR(200) NOT NULL,
    summary VARCHAR(500),
    content TEXT NOT NULL,
    announcement_type VARCHAR(30) NOT NULL DEFAULT 'feature',
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    published_at TIMESTAMP WITH TIME ZONE,
    expires_at TIMESTAMP WITH TIME ZONE,
    created_by VARCHAR(50),
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    CONSTRAINT fk_system_announcements_created_by
        FOREIGN KEY (created_by) REFERENCES users(user_id) ON DELETE SET NULL
);

CREATE INDEX ix_system_announcements_active_published
    ON system_announcements (is_active, published_at);
CREATE INDEX ix_system_announcements_expires_at
    ON system_announcements (expires_at);

CREATE TABLE user_announcements (
    id SERIAL PRIMARY KEY,
    user_id VARCHAR(50) NOT NULL,
    announcement_id INTEGER NOT NULL,
    seen_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    CONSTRAINT fk_user_announcements_user
        FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
    CONSTRAINT fk_user_announcements_announcement
        FOREIGN KEY (announcement_id) REFERENCES system_announcements(id) ON DELETE CASCADE,
    CONSTRAINT uq_user_announcements_user_announcement
        UNIQUE (user_id, announcement_id)
);

CREATE INDEX ix_user_announcements_user
    ON user_announcements (user_id);
CREATE INDEX ix_user_announcements_user_seen
    ON user_announcements (user_id, seen_at);

COMMENT ON TABLE system_announcements IS 'Published system announcements / release notes';
COMMENT ON TABLE user_announcements IS 'Per-user acknowledgement state for announcements';

COMMIT;
