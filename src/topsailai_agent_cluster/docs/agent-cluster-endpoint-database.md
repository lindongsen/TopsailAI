---
maintainer: AI
author: DawsonLin
status: discussion-draft
created: 2026-11-15
---

# Endpoint Database

## Scope

The Endpoint keeps its own SQLite database, separate from the Server database described in
`docs/agent-cluster-database.md`. That document covers the Server tables only. This document
covers the Endpoint tables, their migration history and the compatibility boundary between
Endpoint binary versions.

Five tables exist: `resource_mapping`, `command_journal`, `source_cache`, `receipt_settlement`
and `server_identity_seen`. They are created by
`internal/storage/endpoint/internal/migrations/001_initial.sql`, which is embedded into the
binary at compile time.

## Schema history

`001_initial.sql` creates all five tables. `resource_mapping` is keyed by
`(adapter_id, resource_kind, provider_resource_key)` with `UNIQUE (resource_id)`.

`002_resource_mapping_kind.sql` replaces the single `provider_key` column of `resource_mapping`
with `provider_resource_key` plus `resource_kind`. It renames the old table, creates the new
shape, copies every row with `resource_id` carried across positionally, drops the old table and
commits. The migration runs inside one `BEGIN IMMEDIATE` ... `COMMIT` pair, so a failure leaves
the previous shape in place.

`command_journal` and `source_cache` are not touched by `002`.

`003_receipt_settlement_origin.sql` adds `settled_by` to `receipt_settlement` and relaxes
`reason` to nullable. It is a table rebuild rather than an `ALTER TABLE`, because SQLite cannot
drop a `NOT NULL` constraint in place and `reason` must accept NULL for an acknowledgement. The
rebuild follows the same rename, create, copy, drop, commit shape as `002`.

`settled_by` names which terminal outcome ended the resend obligation: `rejection` when the
Server refused the receipt, `acknowledgement` when the Server durably stored it. `reason` carries
a rejection reason only, so it is NULL for an acknowledgement rather than an empty string. The
column carries `DEFAULT 'rejection'` for one reason: an older binary inserts only
`(command_id, reason, settled_at_ms)`, and without a default that insert would fail against the
migrated table.

`receipt_settlement` is a separate table rather than a column on `command_journal` precisely
because the downgrade guard pins `command_journal` and `source_cache` to identical columns across
versions. A new table leaves that contract intact, which is also why `003` may change
`receipt_settlement` while `command_journal` and `source_cache` stay untouched.

## Migration bookkeeping

There is no `schema_migrations` table. Migration state is inferred from the schema itself:
`internal/storage/endpoint/db.go` reads the columns of `resource_mapping` and decides whether the
database is already current, still legacy, or unrecognised. It reads the columns of
`receipt_settlement` for the same reason before applying `003`, and treats the presence of
`settled_by` as the marker that `003` already ran.

## Downgrade boundary

Downgrade is not detected at startup. An older Endpoint binary opens a database written by a
newer binary without any error, because its migration step only executes
`CREATE TABLE IF NOT EXISTS` statements, which are no-ops against tables that already exist. The
older binary performs no schema inspection at all.

The failure therefore arrives late and only in part:

- `resource_mapping` queries fail with `no such column: provider_key`, because the newer database
  stores the provider key in `provider_resource_key` and adds `resource_kind`.
- `command_journal` and `source_cache` keep the same columns in both versions, so the older binary
  reads and writes them successfully against the newer database.
- `receipt_settlement` gains `settled_by` in `003`, but the older binary still writes it: its
  three-column insert omits `settled_by`, which the column default fills with `rejection`. That is
  the correct classification for every settlement an older binary can produce, because an older
  binary has no acknowledgement path at all.

The second point is the dangerous one. An older binary that starts against a newer database does
not merely fail; it appends journal and cache rows to a database whose `resource_mapping` it cannot
read. Those rows are written by code that predates the resource-kind namespace.

## Why the newer binary cannot refuse on the older binary's behalf

The check in `internal/storage/endpoint/db.go` that returns `resource_mapping schema is unsupported`
belongs to the newer binary. It rejects a database whose `resource_mapping` has neither the current
columns nor the legacy `provider_key`. It does not run in the older binary, and the older binary
contains no equivalent.

A newer database cannot force an older binary to refuse either. The older migration step is a set
of `CREATE TABLE IF NOT EXISTS` statements, and SQLite treats those as no-ops when the table is
already present. There is no schema marker the older binary would read and reject.

## Supported direction

Upgrade is supported: an older database is converted by `002` and `003` when a newer binary
opens it.

Downgrade is not supported and cannot be made safe from the newer side. Running an older binary
against a newer database is refused by nothing; the operator must restore the previous binary
together with a database backup taken before the upgrade. No alias table, key-format migration or
version-aware lookup exists to bridge the two shapes.
