BEGIN;

CREATE TABLE system_announcements (
    id SERIAL PRIMARY KEY,
    version VARCHAR(30),
    title VARCHAR(200) NOT NULL,
    summary VARCHAR(500),
    content TEXT,
    announcement_type VARCHAR(30) NOT NULL DEFAULT 'general',
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    published_at TIMESTAMP WITH TIME ZONE NULL,
    expires_at TIMESTAMP WITH TIME ZONE NULL,
    created_by VARCHAR(50) NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_system_announcements_created_by
        FOREIGN KEY (created_by) REFERENCES users(user_id) ON DELETE SET NULL
);

CREATE TABLE user_announcements (
    id SERIAL PRIMARY KEY,
    user_id VARCHAR(50) NOT NULL,
    announcement_id INTEGER NOT NULL,
    seen_at TIMESTAMP WITH TIME ZONE NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_user_announcements_user
        FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
    CONSTRAINT fk_user_announcements_announcement
        FOREIGN KEY (announcement_id) REFERENCES system_announcements(id) ON DELETE CASCADE,
    CONSTRAINT uq_user_announcements_user_announcement
        UNIQUE (user_id, announcement_id)
);

CREATE INDEX ix_system_announcements_active_published
    ON system_announcements (is_active, published_at);
CREATE INDEX ix_system_announcements_expires_at
    ON system_announcements (expires_at);
CREATE INDEX ix_user_announcements_user_announcement
    ON user_announcements (user_id, announcement_id);
CREATE INDEX ix_user_announcements_user_seen
    ON user_announcements (user_id, seen_at);

COMMIT;
