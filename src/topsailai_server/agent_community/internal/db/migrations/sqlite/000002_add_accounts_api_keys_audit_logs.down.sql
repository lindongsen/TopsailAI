-- Rollback migration: drop accounts, api_keys, and audit_logs tables.
-- SQLite-compatible version.

DROP TABLE IF EXISTS audit_logs;
DROP TABLE IF EXISTS api_keys;
DROP TABLE IF EXISTS accounts;
