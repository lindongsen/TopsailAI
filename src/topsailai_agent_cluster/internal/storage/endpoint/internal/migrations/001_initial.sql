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
    resource_kind TEXT NOT NULL,
    provider_resource_key TEXT NOT NULL,
    resource_id TEXT NOT NULL,
    created_at_ms BIGINT NOT NULL,
    update_at_ms BIGINT NOT NULL,
    PRIMARY KEY (adapter_id, resource_kind, provider_resource_key),
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
-- receipt_settlement records receipts the Endpoint must stop re-sending because
-- the current Server proved it can never apply them.
--
-- It is a separate table rather than a column on command_journal because the
-- downgrade guard pins command_journal and source_cache to identical columns
-- across versions, so an older binary must keep writing those tables unchanged.
-- A new table leaves that contract intact and is created automatically on an
-- existing database, because every statement here is CREATE TABLE IF NOT EXISTS
-- and the initial migration runs on every startup.
--
-- A row here is a decision, not a deletion: the journal entry and its receipt
-- stay readable, so the evidence that a receipt existed is preserved while the
-- resend set shrinks.
CREATE TABLE IF NOT EXISTS receipt_settlement (
    command_id TEXT PRIMARY KEY,
    reason TEXT NOT NULL,
    settled_at_ms BIGINT NOT NULL
);
