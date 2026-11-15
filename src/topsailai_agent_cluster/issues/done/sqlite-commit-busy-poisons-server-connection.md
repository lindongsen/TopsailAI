---
maintainer: AI
author: DawsonLin
status: done
created: 2026-11-12
resolved: 2026-11-13
---

# SQLite commit failure poisoned the Server connection

## Symptom

After Endpoint expiry hit `SQLITE_BUSY` during commit, every later inventory write on gd-dev failed with `cannot start a transaction within a transaction`. All Endpoints remained connected, but every CLI read returned the last inventory committed before the failure.

## Root cause

SQLite can leave the underlying transaction active when `COMMIT` returns `SQLITE_BUSY`. `database/sql.Tx.Commit` had already marked its transaction handle finished, so the deferred rollback did not reliably clean the driver connection. The Server pool permits one connection, which made that single poisoned connection a permanent write outage.

## Resolution

Server storage now pins a `sql.Conn` for each explicit transaction, rolls back on the same connection after body or commit failure, and discards the connection when rollback cannot be confirmed. Connection-local SQLite PRAGMAs are encoded in the driver DSN so a replacement connection retains the same durability and lock-wait settings. Endpoint expiry and inventory replacement use the shared transaction helper.

## Verification

A real SQLite regression test holds an external read transaction until the Server commit returns busy, releases the lock, and proves the next inventory write succeeds. The same test fails on the pre-fix source with the production nested-transaction error. The full Server unit, BDD and integration suites pass. The BDD inventory scenario also verifies the recovery through the real HTTP boundary.
