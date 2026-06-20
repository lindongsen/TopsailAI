-- Rollback initial schema for AI-Agent Community Server (ACS)
-- SQLite-compatible version.

DROP TABLE IF EXISTS agent_message_processing;
DROP TABLE IF EXISTS group_messages;
DROP TABLE IF EXISTS group_member;
DROP TABLE IF EXISTS "groups";
