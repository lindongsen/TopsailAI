-- Migration: add accounts, api_keys, and audit_logs tables for ACS authentication and auditing.
-- SQLite-compatible version.

-- Table: accounts
-- Stores user accounts and authentication credentials.
CREATE TABLE IF NOT EXISTS accounts (
    account_id                  VARCHAR(64)  PRIMARY KEY,
    account_name                VARCHAR(255) NOT NULL,
    account_description         TEXT         DEFAULT '',
    role                        VARCHAR(32)  NOT NULL,
    status                      VARCHAR(32)  NOT NULL DEFAULT 'active',
    delete_at_ms                BIGINT       DEFAULT 0,
    creator_id                  VARCHAR(64)  NOT NULL,
    external_id                 VARCHAR(255) DEFAULT NULL,
    email                       VARCHAR(255) DEFAULT NULL,
    auth_provider               VARCHAR(64)  DEFAULT NULL,
    avatar_url                  TEXT         DEFAULT NULL,
    login_name                  VARCHAR(255) NOT NULL,
    login_password              VARCHAR(255) DEFAULT '',
    login_session_key           VARCHAR(255) DEFAULT '',
    login_session_expired_time  BIGINT       DEFAULT 0,
    create_at_ms                BIGINT       NOT NULL,
    update_at_ms                BIGINT       NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_accounts_status ON accounts(status);
CREATE INDEX IF NOT EXISTS idx_accounts_role ON accounts(role);
CREATE UNIQUE INDEX IF NOT EXISTS idx_accounts_login_name ON accounts(login_name);

-- Table: api_keys
-- Stores API keys for account authentication.
CREATE TABLE IF NOT EXISTS api_keys (
    api_key_id    VARCHAR(64)  PRIMARY KEY,
    api_key_name  VARCHAR(255) NOT NULL,
    api_key_hash  VARCHAR(255) NOT NULL,
    role          VARCHAR(32)  NOT NULL,
    status        VARCHAR(32)  NOT NULL DEFAULT 'active',
    creator_id    VARCHAR(64)  NOT NULL,
    owner_id      VARCHAR(64)  NOT NULL,
    create_at_ms  BIGINT       NOT NULL,
    update_at_ms  BIGINT       NOT NULL,
    CONSTRAINT fk_api_keys_owner_id
        FOREIGN KEY (owner_id)
        REFERENCES accounts(account_id)
        ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_api_keys_owner_id ON api_keys(owner_id);
CREATE INDEX IF NOT EXISTS idx_api_keys_status ON api_keys(status);
CREATE INDEX IF NOT EXISTS idx_api_keys_role ON api_keys(role);

-- Table: audit_logs
-- Records security and lifecycle events.
CREATE TABLE IF NOT EXISTS audit_logs (
    audit_log_id   VARCHAR(64)  PRIMARY KEY,
    account_id     VARCHAR(64)  NOT NULL,
    api_key_id     VARCHAR(64)  NOT NULL,
    action         VARCHAR(255) NOT NULL,
    resource_type  VARCHAR(255) NOT NULL,
    resource_id    VARCHAR(255) NOT NULL,
    resource_name  VARCHAR(255) DEFAULT '',
    detail         TEXT         DEFAULT '',
    client_ip      VARCHAR(64)  DEFAULT '',
    create_at_ms   BIGINT       NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_audit_logs_account_id ON audit_logs(account_id);
CREATE INDEX IF NOT EXISTS idx_audit_logs_api_key_id ON audit_logs(api_key_id);
CREATE INDEX IF NOT EXISTS idx_audit_logs_resource ON audit_logs(resource_type, resource_id);
CREATE INDEX IF NOT EXISTS idx_audit_logs_create_at_ms ON audit_logs(create_at_ms);
