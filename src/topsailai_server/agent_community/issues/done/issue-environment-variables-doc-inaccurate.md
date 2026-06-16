---
maintainer: AI
workspace: /TopsailAI/src/topsailai_server/agent_community
---

# Issue: Environment Variables Documentation Inaccurate and Incomplete

**Status**: Fixed
**Priority**: Medium
**Component**: docs
**Related Files**:
- `docs/Environment_Variables.md`
- `internal/config/config.go`
- `internal/daemon/daemon.go`
- `internal/agent/interface.go`
- `cmd/cli/main.go`
- `cmd/cli/nats.go`

## Description

The `docs/Environment_Variables.md` file contained several inaccuracies and omissions compared to the actual environment variables used by the service. This issue documents the discrepancies found during review and the fixes applied.

## Discrepancies Found

### 1. Missing Server Timeout Variables
- `ACS_SERVER_READ_TIMEOUT` (default `30s`)
- `ACS_SERVER_WRITE_TIMEOUT` (default `30s`)

### 2. Incorrect Database Variable Names and Defaults
- Document used `ACS_DB_*` but actual code uses `ACS_DATABASE_*`.
- Missing `ACS_DATABASE_DRIVER` (default `postgres`).
- Default `ACS_DATABASE_USER` is `acs`, not `postgres`.
- Default `ACS_DATABASE_PASSWORD` is `acs`, not `postgres`.
- Default `ACS_DATABASE_NAME` is `acs` for PostgreSQL or `$ACS_HOME/agent_community.db` for SQLite.
- Document incorrectly listed `ACS_DB_MAX_OPEN_CONNS`, `ACS_DB_MAX_IDLE_CONNS`, and `ACS_DB_CONN_MAX_LIFETIME_MINUTES`, which are not present in `config.go`.

### 3. Missing NATS KV Lock Variables
- `ACS_NATS_KV_BUCKET` (default `acs_locks`)
- `ACS_NATS_LOCK_TTL_SECONDS` (default `7200`)
- `ACS_NATS_LOCK_RENEW_INTERVAL_SECONDS` (default `10`)

These are referenced in ORIGIN.md but not currently loaded in `config.go`. They should be documented as expected/planned configuration.

### 4. Missing WorkPool Variables
- `ACS_POOL_GLOBAL` (default `10`)
- `ACS_POOL_PER_USER` (default `5`)
- `ACS_POOL_PER_GROUP` (default `5`)
- `ACS_POOL_STATS_LOG_INTERVAL` (default `30s`)

Document used `ACS_AGENT_WORK_POOL_*` names which do not match the actual `ACS_POOL_*` keys in `config.go`.

### 5. Missing Log Variables
- Document did not include a Log Configuration section.
- Variables: `ACS_LOG_OUTPUT`, `ACS_LOG_LEVEL`, `ACS_LOG_FILE_PATH`, `ACS_LOG_MAX_SIZE_MB`, `ACS_LOG_MAX_AGE_DAYS`, `ACS_LOG_MAX_BACKUPS`.

### 6. Missing Agent Variables
- `ACS_AGENT_AUTO_TRIGGER_TIMEOUT` (default `10m`)
- `ACS_AGENT_PROMPT` (default empty)

### 7. Missing Daemon/Home Variables
- `ACS_HOME` (default `/topsailai`)
- `TOPSAILAI_HOME` (default `/topsailai`)

### 8. Missing CLI Variables
- `ACS_NATS_SERVERS` is also used by CLI.
- Default `ACS_CLI_MEMBER_ID` is `cli-user`.
- Default `ACS_CLI_MEMBER_NAME` is `CLI User`.

### 9. Missing Agent Chat Environment Variables
The dynamically built agent environment variables were not documented. Added a dedicated table for:
- `ACS_AGENT_API_BASE`, `ACS_AGENT_API_KEY`, `ACS_AGENT_API_AUTH`
- `ACS_AGENT_ID`, `ACS_AGENT_NAME`, `ACS_AGENT_TYPE`
- `ACS_AGENT_MODE`, `ACS_AGENT_MESSAGE`, `ACS_AGENT_TIMEOUT`
- `ACS_AGENT_PROMPT`, `ACS_GROUP_ID`, `ACS_GROUP_NAME`, `ACS_GROUP_CONTEXT`
- `ACS_SENDER_ID`, `ACS_SENDER_NAME`, `ACS_MESSAGE_ID`
- `ACS_MESSAGE_MENTIONS`, `ACS_MESSAGE_TRIGGER_TYPE`

## Fix

Updated `docs/Environment_Variables.md` to accurately reflect all environment variables found in the codebase, organized by component, with correct defaults and descriptions.

## Fixed

- **Fix date**: 2026-06-16
- **Fixed by**: km2-reviewer
- **Files changed**:
  - `docs/Environment_Variables.md`
