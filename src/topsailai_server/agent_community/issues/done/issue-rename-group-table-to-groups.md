---
maintainer: AI
workspace: /TopsailAI/src/topsailai_server/agent_community
---

# Issue: Rename database table `group` to `groups`

## Description
The database table previously named `group` has been renamed to `groups` to avoid conflicts with the SQL reserved keyword `GROUP` and to align with the documentation in `ORIGIN.md` and `README.md`.

## Affected Files

1. `/TopsailAI/src/topsailai_server/agent_community/internal/models/group.go`
   - `TableName()` now returns `"groups"`.

2. `/TopsailAI/src/topsailai_server/agent_community/internal/db/migrations/000001_init_schema.up.sql`
   - `CREATE TABLE IF NOT EXISTS "groups"`
   - Indexes renamed to `idx_groups_deleted_at` and `idx_groups_create_at_ms`
   - Header comment updated to `-- Table: groups`

3. `/TopsailAI/src/topsailai_server/agent_community/internal/db/migrations/000001_init_schema.down.sql`
   - `DROP TABLE IF EXISTS "groups"`

## Verification

- [x] All SQL references to the table use `groups`.
- [x] Go code compiles successfully (`go build ./...`).
- [x] Unit tests pass (`go test ./...`).
- [x] Documentation is consistent (`ORIGIN.md`, `README.md` already reference `groups`).

## Status

Done.
