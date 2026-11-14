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

Three tables exist: `resource_mapping`, `command_journal` and `source_cache`. They are created
by `internal/storage/endpoint/internal/migrations/001_initial.sql`, which is embedded into the
binary at compile time.

## Schema history

`001_initial.sql` creates all three tables. `resource_mapping` is keyed by
`(adapter_id, resource_kind, provider_resource_key)` with `UNIQUE (resource_id)`.

`002_resource_mapping_kind.sql` replaces the single `provider_key` column of `resource_mapping`
with `provider_resource_key` plus `resource_kind`. It renames the old table, creates the new
shape, copies every row with `resource_id` carried across positionally, drops the old table and
commits. The migration runs inside one `BEGIN IMMEDIATE` ... `COMMIT` pair, so a failure leaves
the previous shape in place.

`command_journal` and `source_cache` are not touched by `002`.

## Migration bookkeeping

There is no `schema_migrations` table. Migration state is inferred from the schema itself:
`internal/storage/endpoint/db.go` reads the columns of `resource_mapping` and decides whether the
database is already current, still legacy, or unrecognised.

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

Upgrade is supported: an older database is converted by `002` when a newer binary opens it.

Downgrade is not supported and cannot be made safe from the newer side. Running an older binary
against a newer database is refused by nothing; the operator must restore the previous binary
together with a database backup taken before the upgrade. No alias table, key-format migration or
version-aware lookup exists to bridge the two shapes.
