BEGIN IMMEDIATE;
ALTER TABLE receipt_settlement RENAME TO receipt_settlement_legacy;
CREATE TABLE receipt_settlement (
    command_id TEXT PRIMARY KEY,
    reason TEXT,
    settled_by TEXT NOT NULL DEFAULT 'rejection',
    settled_at_ms BIGINT NOT NULL
);
INSERT INTO receipt_settlement(
    command_id,
    reason,
    settled_by,
    settled_at_ms
)
SELECT
    command_id,
    reason,
    'rejection',
    settled_at_ms
FROM receipt_settlement_legacy;
DROP TABLE receipt_settlement_legacy;
COMMIT;
