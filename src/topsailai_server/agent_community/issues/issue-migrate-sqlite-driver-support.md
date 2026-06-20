# Issue: migrate.go hardcodes PostgreSQL driver and migrations are PostgreSQL-specific

## Status

Fixed

`internal/db/migrate.go` currently hardcodes the `postgres` driver from `golang-migrate`:

```go
import "github.com/golang-migrate/migrate/v4/database/postgres"

driver, err := postgres.WithInstance(db, &postgres.Config{
    DatabaseName: cfg.Database.Name,
})
```

This means:

1. `MigrateUp`, `MigrateDown`, and `MigrateVersion` cannot be used with `ACS_DATABASE_DRIVER=sqlite`.
2. Unit tests for the migration utilities cannot run against SQLite in-memory or file databases.
3. The embedded migration SQL files use PostgreSQL-specific syntax (`CREATE EXTENSION`, `JSONB`, `BIGSERIAL`, `TIMESTAMPTZ`), which fails on SQLite even if the driver were swapped.

## Impact

- `internal/db/migrate.go` has **0% unit-test coverage**.
- The existing `db_test.go` tests for `MigrateUp`/`MigrateDown` are skipped.
- SQLite users cannot run schema migrations via `migrate.go`; they rely solely on GORM auto-migration in `db.go`.

## Proposed Solution

1. Refactor `newMigrateInstance` in `migrate.go` to select the migrate driver based on `cfg.Database.Driver`:
   - `postgres` → `postgres.WithInstance`
   - `sqlite` → `sqlite3.WithInstance`
   - unsupported → error
2. Provide SQLite-compatible migration files under `internal/db/migrations/sqlite/` that mirror the PostgreSQL versions but use SQLite-compatible types:
   - `JSONB` → `TEXT`
   - `BIGSERIAL` → `INTEGER PRIMARY KEY AUTOINCREMENT`
   - `TIMESTAMPTZ` → `TEXT`
   - Remove `CREATE EXTENSION IF NOT EXISTS "uuid-ossp";`
3. Update the embedded migration source selection so SQLite migrations are loaded when the driver is `sqlite`.
4. Add `internal/db/migrate_test.go` with SQLite-based tests for `MigrateUp`, `MigrateDown`, and `MigrateVersion`.

## Acceptance Criteria

- `go test -race ./internal/db/...` passes, including new migration tests.
- `MigrateUp`/`MigrateDown`/`MigrateVersion` work with `ACS_DATABASE_DRIVER=sqlite` against a temporary SQLite file.
- PostgreSQL behavior remains unchanged.
- All production code changes are covered by unit tests.

## Related Files

- `internal/db/migrate.go`
- `internal/db/migrations/*.sql`
- `internal/db/migrate_test.go` (to be created)
- `internal/db/db_test.go` (skipped tests to be enabled)

## Notes

- `golang.org/x/net` is already an indirect dependency; `github.com/mattn/go-sqlite3` is already present in `go.mod`.
- The `golang-migrate` SQLite driver must be imported with `_ "github.com/golang-migrate/migrate/v4/database/sqlite3"`.
- SQLite in-memory (`:memory:`) is not suitable for `golang-migrate` because `openRawDB` returns a new connection each call and `:memory:` databases are connection-scoped. Tests should use a temporary file database.
