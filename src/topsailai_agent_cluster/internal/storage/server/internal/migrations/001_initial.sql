PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS endpoints (
    endpoint_id TEXT PRIMARY KEY,
    instance_id TEXT NOT NULL,
    display_name TEXT NOT NULL,
    hostname TEXT NOT NULL DEFAULT '',
    connection_state TEXT NOT NULL,
    offline_since_at_ms BIGINT NOT NULL DEFAULT 0,
    observed_at_ms BIGINT NOT NULL,
    capability_revision TEXT NOT NULL,
    create_at_ms BIGINT NOT NULL,
    update_at_ms BIGINT NOT NULL
);

CREATE TABLE IF NOT EXISTS endpoint_session_state (
    endpoint_id TEXT PRIMARY KEY REFERENCES endpoints(endpoint_id) ON DELETE CASCADE,
    schema_version TEXT NOT NULL,
    source_generation TEXT NOT NULL,
    snapshot_revision BIGINT NOT NULL,
    observed_at_ms BIGINT NOT NULL,
    received_at_ms BIGINT NOT NULL,
    sessions_json TEXT NOT NULL,
    create_at_ms BIGINT NOT NULL,
    update_at_ms BIGINT NOT NULL
);

CREATE TABLE IF NOT EXISTS commands (
    command_id TEXT PRIMARY KEY,
    request_hash TEXT NOT NULL,
    endpoint_id TEXT NOT NULL REFERENCES endpoints(endpoint_id),
    operation TEXT NOT NULL,
    target_json TEXT,
    intent_json TEXT NOT NULL,
    status TEXT NOT NULL,
    phase TEXT NOT NULL,
    delivery_boundary TEXT NOT NULL,
    effect_certainty TEXT NOT NULL,
    deadline_at_ms BIGINT NOT NULL,
    receipt_json TEXT,
    create_at_ms BIGINT NOT NULL,
    update_at_ms BIGINT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_commands_endpoint_status ON commands(endpoint_id, status);
CREATE INDEX IF NOT EXISTS idx_endpoints_update ON endpoints(update_at_ms, endpoint_id);
