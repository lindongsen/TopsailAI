---
status: closed
severity: high
related_files:
  - internal/db/db.go
  - internal/db/migrate.go
  - internal/services/bootstrap.go
  - cmd/server/main.go
related_test_case: Plan 04 — 4.8 Default Account Creation Race Protection
---
# Database Migration Race on Multi-Node Startup

## Summary

When multiple ACS server instances are started simultaneously against the same empty PostgreSQL database, the database auto-migration step races. One instance succeeds in creating the schema, while the other fails with:

```
ERROR: duplicate key value violates unique constraint "pg_type_typname_nsp_index" (SQLSTATE 23505)
```

The failing instance exits before reaching the bootstrap distributed lock, so it cannot participate in the cluster until the database is pre-migrated or the instance is restarted after the first one finishes migration.

## Impact

- Concurrent startup of multiple ACS nodes against a fresh database is unreliable.
- A stateless distributed service should tolerate simultaneous startup, but currently it cannot.
- The bootstrap distributed lock (fixed in `issue-bootstrap-distributed-lock-invalid-key.md`) is never reached by the failing node, so its protection is insufficient for a true cold-start cluster scenario.

## Steps to Reproduce

1. Create a fresh PostgreSQL database:
   ```bash
   psql -h localhost -U postgres -d postgres -c "DROP DATABASE IF EXISTS acs_race_test;"
   psql -h localhost -U postgres -d postgres -c "CREATE DATABASE acs_race_test;"
   psql -h localhost -U postgres -d acs_race_test -c "GRANT ALL ON SCHEMA public TO acs;"
   ```

2. Start two ACS server instances at nearly the same time from different working directories:
   ```bash
   # Node 1
   cd /tmp/acs_race_node1
   ACS_HTTP_PORT=7373 ACS_DATABASE_NAME=acs_race_test ACS_NATS_SERVERS=nats://localhost:4222 ./bin/acs-server

   # Node 2
   cd /tmp/acs_race_node2
   ACS_HTTP_PORT=7374 ACS_DATABASE_NAME=acs_race_test ACS_NATS_SERVERS=nats://localhost:4222 ./bin/acs-server
   ```

3. Observe that one node fails during `auto-migrate` with `pg_type_typname_nsp_index` duplicate key violation, while the other succeeds.

## Expected Behavior

- Both nodes start successfully.
- Exactly one node creates the database schema.
- The other node detects that the schema already exists (or waits for migration to complete) and proceeds to bootstrap.
- The bootstrap distributed lock then ensures only one set of default accounts is created.

## Actual Behavior

Node 1 log:
```
{"timestamp":"2026-06-26T03:54:56Z","level":"INFO","message":"starting ACS server","module":"server","trace_id":"","port":7373}
ERROR: duplicate key value violates unique constraint "pg_type_typname_nsp_index" (SQLSTATE 23505)
CREATE TABLE "groups" (...)
server failed: failed to initialize database: failed to auto-migrate database: ERROR: duplicate key value violates unique constraint "pg_type_typname_nsp_index" (SQLSTATE 23505)
```

Node 2 log:
```
{"timestamp":"2026-06-26T03:54:56Z","level":"INFO","message":"database initialized and migrated successfully",...}
{"timestamp":"2026-06-26T03:54:56Z","level":"INFO","message":"created default admin account",...}
{"timestamp":"2026-06-26T03:54:56Z","level":"INFO","message":"created default manager account",...}
{"timestamp":"2026-06-26T03:54:56Z","level":"INFO","message":"ACS server started successfully",...}
```

## Root Cause

`internal/db/db.go` calls `db.AutoMigrate(...)` during server initialization without any distributed coordination. When two processes run `AutoMigrate` concurrently on an empty PostgreSQL database, both attempt to create the same tables/types, causing a race on `pg_type` catalog rows.

The bootstrap distributed lock in `internal/services/bootstrap.go` is acquired **after** migration, so it cannot protect the migration itself.

## Fix

Implemented in `internal/db/db.go` and `cmd/server/main.go`:

- `cmd/server/main.go` now connects to NATS **before** initializing the database, so the NATS KV bucket is available for the migration lock.
- `internal/db/db.go` protects `AutoMigrate` with a NATS KV distributed lock at key `acs.lock.bootstrap.migration`.
- The lock holder runs `AutoMigrate`; other nodes wait for the lock to be released and then run an idempotent `AutoMigrate` to verify the schema.
- The wait timeout is aligned with the NATS KV bucket TTL (`2h`) so that a crashed migrator does not cause other nodes to time out prematurely.
- A `defer`/`recover` block ensures the lock is deleted even if `AutoMigrate` panics; the panic is re-raised so the server still fails loudly.
- Unit tests in `internal/db/migration_lock_test.go` verify lock acquisition/release, waiting behavior, nil-KV fallback, timeout, and panic cleanup.

## Verification After Fix

1. Drop and recreate `acs_race_test`.
2. Start two ACS instances simultaneously.
3. Both instances should start successfully.
4. Database should contain exactly one admin and one manager account.
5. Only one working directory should contain `ACS_ACCOUNT_ADMIN_API_KEY.acs` and `ACS_ACCOUNT_MANAGER_API_KEY.acs`.

## Environment

- ACS commit: after bootstrap lock fix (`acs.lock.bootstrap.default-accounts`)
- Database: PostgreSQL 14+ on localhost:5432
- NATS: nats://localhost:4222
- Nodes: 127.0.0.1:7373 and 127.0.0.1:7374
- Date observed: 2026-06-26
- Date fixed: 2026-06-26
