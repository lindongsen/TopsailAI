---
maintainer: AI
programming_language: go
---

# Issue: Agent Message Processing Table Cleanup

## Description

The `agent_message_processing` table has no cleanup logic, causing it to grow unboundedly. Every agent trigger (both auto-trigger and mention-trigger paths) creates records in this table, but there is no mechanism to delete old records.

## Problem

- Records are created on every agent trigger via `internal/nats/auto_trigger.go` and `internal/nats/consumer.go`
- No `DELETE` operations exist for this table anywhere in the codebase
- No scheduled cleanup job, TTL, or retention policy is implemented
- Over time, this leads to unbounded database storage growth

## Impact

Database storage will grow indefinitely as every agent trigger creates records that are never deleted. In a busy system with many groups, messages, and agents, this table will accumulate millions of rows, degrading query performance and consuming disk space.

## Solution

Added a periodic cleanup task (`CleanupTask`) with configurable retention policies:

1. **Terminal records** (status = `completed` or `failed`) are deleted after a configurable retention period (default: 7 days)
2. **Stale pending records** (status = `pending` and older than a threshold) are deleted (default: 24 hours)
3. Cleanup runs as a background goroutine with graceful shutdown support
4. Uses configurable batch size to avoid long-running transactions (default: 1000 records per run)

## Files Modified

- `internal/config/config.go` — Added `CleanupConfig` struct with defaults and environment variable binding
- `internal/db/cleanup.go` — New cleanup logic with goroutine lifecycle, nil-DB guard, and structured logging
- `cmd/server/main.go` — Integrated `CleanupTask` Start/Stop into server lifecycle
- `internal/models/agent_processing.go` — Added `IsTerminalStatus()` helper method

## Files Created

- `internal/config/config_test.go` — 8 config tests (defaults, overrides, boundary values)
- `internal/db/cleanup_test.go` — 25 unit and edge-case tests
- `internal/db/cleanup_integration_test.go` — 6 integration-style tests (real DB, intervals, graceful shutdown)
- `internal/models/agent_processing_test.go` — 5 model tests

## Environment Variables Added

| Variable | Default | Description |
|----------|---------|-------------|
| `ACS_CLEANUP_ENABLED` | `true` | Enable or disable the cleanup background task |
| `ACS_CLEANUP_INTERVAL` | `1h` | Interval between cleanup executions |
| `ACS_CLEANUP_RETENTION_DAYS` | `7` | Days to retain terminal (completed/failed) records |
| `ACS_CLEANUP_STALE_PENDING_HOURS` | `24` | Hours after which pending records are considered stale |
| `ACS_CLEANUP_BATCH_SIZE` | `1000` | Maximum records to delete per cleanup execution |

## Status

Fixed
