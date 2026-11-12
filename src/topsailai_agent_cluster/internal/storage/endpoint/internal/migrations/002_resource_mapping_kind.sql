BEGIN IMMEDIATE;
ALTER TABLE resource_mapping RENAME TO resource_mapping_legacy;
CREATE TABLE resource_mapping (
    adapter_id TEXT NOT NULL,
    resource_kind TEXT NOT NULL,
    provider_resource_key TEXT NOT NULL,
    resource_id TEXT NOT NULL,
    created_at_ms BIGINT NOT NULL,
    update_at_ms BIGINT NOT NULL,
    PRIMARY KEY (adapter_id, resource_kind, provider_resource_key),
    UNIQUE (resource_id)
);
INSERT INTO resource_mapping(
    adapter_id,
    resource_kind,
    provider_resource_key,
    resource_id,
    created_at_ms,
    update_at_ms
)
SELECT
    adapter_id,
    CASE WHEN provider_key LIKE 'model:%' THEN 'model_profile' ELSE 'session' END,
    provider_key,
    resource_id,
    created_at_ms,
    update_at_ms
FROM resource_mapping_legacy;
DROP TABLE resource_mapping_legacy;
COMMIT;
