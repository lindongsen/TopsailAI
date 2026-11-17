---
maintainer: AI
author: DawsonLin
status: resolved
created: 2026-11-14
resolved: 2026-11-17
---

# Server SQLite foreign keys are not enabled in the DSN

## Symptom

Foreign key enforcement on the Server database depended on a single connection surviving for the
lifetime of the process. It was not a property of the database handle. When that connection was
discarded, enforcement silently disappeared and referential integrity was no longer checked.

## Root cause

`PRAGMA foreign_keys = ON` appeared only in the migration script
(`internal/storage/server/internal/migrations/001_initial.sql:1`). It was not part of the DSN.

`Open` (`internal/storage/server/db.go:24-45`) set only three pragmas:

```go
pragmas.Add("_pragma", "journal_mode(DELETE)")
pragmas.Add("_pragma", "synchronous(FULL)")
pragmas.Add("_pragma", "busy_timeout(5000)")
```

`foreign_keys` was absent. SQLite defaults it to OFF per connection, so the setting was applied
only to whichever connection executed the migration.

It worked only because `db.SetMaxOpenConns(1)` (`db.go:38`) kept exactly one connection alive, and
that connection was the one that ran the migration.

## Why this was a live hazard

`internal/storage/server/transaction.go:36-45` deliberately discards a connection after a
transaction failure:

```go
discardErr := conn.Raw(func(any) error { return driver.ErrBadConn })
```

The comment states the connection is "discarded instead of returning an active transaction to
the pool". That fix is correct for its own purpose, but it means the connection that carried
`foreign_keys = ON` can be replaced by a fresh one that does not.

The fleet has already produced 70 `cannot start a transaction within a transaction` errors
before the fix landed, so the discard path is not hypothetical.

## Detection failure

No test opened a second connection and asserted that FK enforcement was active. Every storage test
used the same `Store` instance created by `Open`, so it inherited the migrated connection and never
observed the default.

The defect was invisible to the suite by construction: the only way to see it is to inspect a
connection that did not run the migration.

## Correction applied

`foreign_keys(ON)` was added to the DSN pragma list in `Open`, so every connection carries it:

```go
pragmas.Add("_pragma", "foreign_keys(ON)")
```

A comment at the site records why the DSN is the only correct location: the pragma is
per-connection, the migration configures only the connection that ran it, and
`rollbackTransaction` discards a poisoned connection with `driver.ErrBadConn`.

## Two claims in the original report were wrong

### The prescribed test could never pass

The original "Required correction" asked for a test that opens an independent connection to the
same file and asserts `PRAGMA foreign_keys` returns 1. That test is structurally unpassable,
because the pragma lives in the DSN and not in the database file. Measured on already-fixed code:

```text
store connection        foreign_keys=1
independent connection  foreign_keys=0
```

Any connection opened from a bare path never inherits a DSN pragma, so the assertion fails no
matter how the production code is written. A test written that way would have been dismissed as a
broken test rather than recognised as a broken prescription.

The tests that were actually added assert the property that matters: after the migrated connection
is discarded, the pooled replacement still enforces FK. Both were observed to fail on unfixed code
and pass on fixed code.

### Cascade deletion is not blocked by the foreign key

The original report claimed that enabling the foreign key would block `ExpireDegradedEndpoints`,
making this a prerequisite for `degraded-endpoint-deletion-destroys-unconfirmed-evidence.md`.

That is false. The production delete order removes child rows before the parent row
(`commands` -> `endpoint_session_state` -> `endpoints`), so the constraint is satisfied at every
step. Measured with the real delete order:

```text
FK OFF   step1=true step2=true step3=true  endpoints_left=0 orphans=0
FK ON    step1=true step2=true step3=true  endpoints_left=0 orphans=0
```

Enabling the foreign key therefore does not change the endpoint-expiry behaviour, and it is not a
prerequisite for that issue. That issue was resolved separately by the human decision to keep the
cascade and log every removed command.

## The real hazard the original report missed

`admitCommand` (`internal/server/commands.go:201`) has no `requireRegisteredEndpoint` check, unlike
every read path:

| Path | Endpoint existence checked |
|---|---|
| output snapshot / follow | yes (`http.go:171,225`) |
| messages / history / detail / model / metrics | yes, each returns `endpoint_not_found` |
| command admission `admitCommand` | **no** |

Measured on unfixed code after a connection discard:

```text
foreign_keys after discard = 0
AdmitCommand error = <nil>          (admitted)
orphan command rows = 1
```

With the fix applied:

```text
foreign_keys after discard = 1
AdmitCommand error = constraint failed: FOREIGN KEY constraint failed (787)
orphan command rows = 0
```

So the real consequence of the missing pragma was not a broken cascade. It was that a command for
a machine that was never registered could be stored silently, producing a row that can never be
dispatched and can never be joined to an Endpoint.

The missing admission check and the raw SQLite error text returned to the caller are a separate
defect, recorded in `issues/admission-accepts-unregistered-endpoint-and-leaks-sqlite-error.md`.

## Behaviour change

None on the normal path. The migrated connection already enforced FK, so the HTTP response for an
unregistered endpoint is identical before and after:

```text
status=400 {"code":"admission_failed","message":"constraint failed: FOREIGN KEY constraint failed (787)"}
```

The fix closes only the post-discard hole.

## Verification

| Check | Result |
|---|---|
| `go test ./internal/storage/server/ -run TestForeignKeys -v` | both PASS |
| Same tests with the pragma removed | both FAIL, naming the DSN as the cause |
| `go test ./internal/storage/server/` | ok |
| `go test ./internal/server/` | ok |
| `go test ./src/main/agent-cluster-server/` | ok |
| `go vet ./internal/storage/server/` | clean |
| `gofmt -l internal/storage/server/` | clean |
| Live database orphan rows | `endpoints=3 commands=43 orphan_commands=0 orphan_inventory=0`, so enabling FK cannot fail on existing data |
| Endpoint storage | migrations contain no `REFERENCES`, unaffected |

## Driver-version note

The first probe used `modernc.org/sqlite v1.0.0` and reported `_pragma` ineffective for every
pragma, including the `busy_timeout` that is known to work. The project uses `v1.39.1`. Re-running
with the project version reversed the result: `_pragma=foreign_keys(ON)` yields `foreign_keys=1`.
The v1.0.0 experiment was invalid and was discarded rather than reported.
