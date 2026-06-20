-- Initial schema for AI-Agent Community Server (ACS)
-- SQLite-compatible version.
-- Tables: groups, group_member, group_messages, agent_message_processing

-- Table: groups
-- Represents a community/session in the ACS system.
CREATE TABLE IF NOT EXISTS "groups" (
    group_id      VARCHAR(64)  PRIMARY KEY,
    group_name    VARCHAR(255) NOT NULL,
    group_context TEXT         DEFAULT '',
    group_key     VARCHAR(255) DEFAULT NULL,
    create_at_ms  BIGINT       NOT NULL,
    update_at_ms  BIGINT       NOT NULL,
    deleted_at    TEXT
);

CREATE INDEX IF NOT EXISTS idx_groups_deleted_at ON "groups"(deleted_at);
CREATE INDEX IF NOT EXISTS idx_groups_create_at_ms ON "groups"(create_at_ms);

-- Table: group_member
-- Represents a member (user or agent) within a group.
CREATE TABLE IF NOT EXISTS group_member (
    group_id            VARCHAR(64)  NOT NULL,
    member_id           VARCHAR(64)  NOT NULL,
    member_name         VARCHAR(255) NOT NULL,
    member_description  TEXT         DEFAULT '',
    member_status       VARCHAR(32)  NOT NULL DEFAULT 'offline',
    member_type         VARCHAR(32)  NOT NULL,
    member_interface    TEXT         DEFAULT '',
    last_read_message_id VARCHAR(64) DEFAULT '',
    create_at_ms        BIGINT       NOT NULL,
    update_at_ms        BIGINT       NOT NULL,
    deleted_at          TEXT,
    PRIMARY KEY (group_id, member_id)
);

CREATE INDEX IF NOT EXISTS idx_group_member_group_id ON group_member(group_id);
CREATE INDEX IF NOT EXISTS idx_group_member_member_id ON group_member(member_id);
CREATE INDEX IF NOT EXISTS idx_group_member_member_type ON group_member(member_type);
CREATE INDEX IF NOT EXISTS idx_group_member_deleted_at ON group_member(deleted_at);

-- Table: group_messages
-- Stores messages sent within a group session.
CREATE TABLE IF NOT EXISTS group_messages (
    message_id          VARCHAR(64)  PRIMARY KEY,
    group_id            VARCHAR(64)  NOT NULL,
    message_text        TEXT         DEFAULT '',
    message_attachments TEXT         DEFAULT '[]',
    sender_id           VARCHAR(64)  NOT NULL,
    sender_type         VARCHAR(32)  NOT NULL,
    processed_msg_id    VARCHAR(64)  DEFAULT '',
    mentions            TEXT         DEFAULT '[]',
    is_deleted          BOOLEAN      NOT NULL DEFAULT FALSE,
    delete_at_ms        BIGINT       DEFAULT 0,
    create_at_ms        BIGINT       NOT NULL,
    update_at_ms        BIGINT       NOT NULL,
    deleted_at          TEXT
);

CREATE INDEX IF NOT EXISTS idx_group_messages_group_id ON group_messages(group_id);
CREATE INDEX IF NOT EXISTS idx_group_messages_sender_id ON group_messages(sender_id);
CREATE INDEX IF NOT EXISTS idx_group_messages_processed_msg_id ON group_messages(processed_msg_id);
CREATE INDEX IF NOT EXISTS idx_group_messages_create_at_ms ON group_messages(create_at_ms);
CREATE INDEX IF NOT EXISTS idx_group_messages_deleted_at ON group_messages(deleted_at);

-- Table: agent_message_processing
-- Tracks agent message processing to prevent duplicates and loops.
CREATE TABLE IF NOT EXISTS agent_message_processing (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    group_id        VARCHAR(64)  NOT NULL,
    message_id      VARCHAR(64)  NOT NULL,
    agent_id        VARCHAR(64)  NOT NULL,
    status          VARCHAR(32)  NOT NULL DEFAULT 'pending',
    error_message   TEXT         DEFAULT '',
    processed_at_ms BIGINT       DEFAULT 0,
    create_at_ms    BIGINT       NOT NULL,
    update_at_ms    BIGINT       NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_amp_group_msg ON agent_message_processing(group_id, message_id);
CREATE INDEX IF NOT EXISTS idx_amp_agent_id ON agent_message_processing(agent_id);
CREATE INDEX IF NOT EXISTS idx_amp_status ON agent_message_processing(status);
CREATE INDEX IF NOT EXISTS idx_amp_create_at_ms ON agent_message_processing(create_at_ms);
