CREATE TABLE IF NOT EXISTS command_journal (
    command_id TEXT PRIMARY KEY,
    request_hash TEXT NOT NULL,
    intent_json TEXT NOT NULL,
    phase TEXT NOT NULL,
    receipt_json TEXT,
    created_at_ms BIGINT NOT NULL,
    updated_at_ms BIGINT NOT NULL
);
CREATE TABLE IF NOT EXISTS resource_mapping (
    adapter_id TEXT NOT NULL,
    provider_key TEXT NOT NULL,
    resource_id TEXT NOT NULL,
    created_at_ms BIGINT NOT NULL,
    update_at_ms BIGINT NOT NULL,
    PRIMARY KEY (adapter_id, provider_key),
    UNIQUE (resource_id)
);
CREATE TABLE IF NOT EXISTS source_cache (
    adapter_id TEXT PRIMARY KEY,
    provider_type TEXT NOT NULL,
    display_name TEXT NOT NULL,
    version TEXT NOT NULL,
    health TEXT NOT NULL,
    sessions_json TEXT NOT NULL,
    report_complete INTEGER NOT NULL,
    collection_status TEXT NOT NULL,
    last_attempt_at_ms BIGINT NOT NULL,
    last_success_at_ms BIGINT,
    data_known INTEGER NOT NULL,
    stale INTEGER NOT NULL,
    error_code TEXT,
    error_message TEXT,
    update_at_ms BIGINT NOT NULL
);
