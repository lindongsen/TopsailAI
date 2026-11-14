package endpointstorage

import (
	"context"
	"database/sql"
	"path/filepath"
	"regexp"
	"strings"
	"testing"
)

// migrationText reads one embedded migration so a guard can inspect the
// transaction boundary the file declares rather than restate it.
func migrationText(t *testing.T, name string) string {
	t.Helper()
	data, err := migrationFS.ReadFile("internal/migrations/" + name)
	if err != nil {
		t.Fatalf("read %s: %v", name, err)
	}
	return string(data)
}

// tableNames returns the tables present in the database file.
func tableNames(t *testing.T, path string) map[string]bool {
	t.Helper()
	db, err := sql.Open("sqlite", path)
	if err != nil {
		t.Fatal(err)
	}
	defer db.Close()
	rows, err := db.Query(`SELECT name FROM sqlite_master WHERE type='table'`)
	if err != nil {
		t.Fatal(err)
	}
	defer rows.Close()
	names := make(map[string]bool)
	for rows.Next() {
		var name string
		if err := rows.Scan(&name); err != nil {
			t.Fatal(err)
		}
		names[name] = true
	}
	if err := rows.Err(); err != nil {
		t.Fatal(err)
	}
	return names
}

// columnNames returns the columns of one table.
func columnNames(t *testing.T, path, table string) map[string]bool {
	t.Helper()
	db, err := sql.Open("sqlite", path)
	if err != nil {
		t.Fatal(err)
	}
	defer db.Close()
	rows, err := db.Query(`PRAGMA table_info(` + table + `)`)
	if err != nil {
		t.Fatal(err)
	}
	defer rows.Close()
	columns := make(map[string]bool)
	for rows.Next() {
		var cid, notNull, primaryKey int
		var name, columnType string
		var defaultValue any
		if err := rows.Scan(&cid, &name, &columnType, &notNull, &defaultValue, &primaryKey); err != nil {
			t.Fatal(err)
		}
		columns[name] = true
	}
	if err := rows.Err(); err != nil {
		t.Fatal(err)
	}
	return columns
}

// legacyRows returns the resource IDs stored in the legacy table shape.
func legacyRows(t *testing.T, path string) []string {
	t.Helper()
	db, err := sql.Open("sqlite", path)
	if err != nil {
		t.Fatal(err)
	}
	defer db.Close()
	rows, err := db.Query(`SELECT resource_id FROM resource_mapping ORDER BY resource_id`)
	if err != nil {
		t.Fatal(err)
	}
	defer rows.Close()
	var ids []string
	for rows.Next() {
		var id string
		if err := rows.Scan(&id); err != nil {
			t.Fatal(err)
		}
		ids = append(ids, id)
	}
	if err := rows.Err(); err != nil {
		t.Fatal(err)
	}
	return ids
}

// writeLegacyDatabase creates a database in the pre-002 shape and returns its
// path. The caller decides which rows to insert so a test can force a specific
// failure point.
func writeLegacyDatabase(t *testing.T, schema string, rows [][2]string) string {
	t.Helper()
	path := filepath.Join(t.TempDir(), "legacy.db")
	db, err := sql.Open("sqlite", path)
	if err != nil {
		t.Fatal(err)
	}
	defer db.Close()
	if _, err := db.Exec(schema); err != nil {
		t.Fatal(err)
	}
	for _, row := range rows {
		if _, err := db.Exec(`INSERT INTO resource_mapping(adapter_id, provider_key, resource_id, created_at_ms, update_at_ms) VALUES('adapter-a', ?, ?, 1, 1)`, row[0], row[1]); err != nil {
			t.Fatal(err)
		}
	}
	return path
}

// legacySchema is the pre-002 table shape the migration must replace.
const legacySchema = `CREATE TABLE resource_mapping (
	adapter_id TEXT NOT NULL,
	provider_key TEXT NOT NULL,
	resource_id TEXT NOT NULL,
	created_at_ms BIGINT NOT NULL,
	update_at_ms BIGINT NOT NULL,
	PRIMARY KEY (adapter_id, provider_key)
);`

// TestMigrationTransactionBoundaryIsSingle verifies that the migration file
// declares exactly one transaction and nothing outside it.
//
// A second COMMIT would make the migration partially durable, and a statement
// outside the transaction would survive a rollback. Both defeat the atomicity
// this row claims, so the boundary is read from the file rather than assumed.
func TestMigrationTransactionBoundaryIsSingle(t *testing.T) {
	text := migrationText(t, "002_resource_mapping_kind.sql")
	lines := strings.Split(strings.TrimSpace(text), "\n")
	if len(lines) < 2 {
		t.Fatalf("migration has %d lines, want a transaction around at least one statement", len(lines))
	}
	first := strings.TrimSpace(lines[0])
	last := strings.TrimSpace(lines[len(lines)-1])
	if first != "BEGIN IMMEDIATE;" {
		t.Fatalf("first line=%q, want BEGIN IMMEDIATE;", first)
	}
	if last != "COMMIT;" {
		t.Fatalf("last line=%q, want COMMIT;", last)
	}
	beginPattern := regexp.MustCompile(`(?i)\bBEGIN\b`)
	commitPattern := regexp.MustCompile(`(?i)\bCOMMIT\b`)
	rollbackPattern := regexp.MustCompile(`(?i)\bROLLBACK\b`)
	for index, line := range lines {
		trimmed := strings.TrimSpace(line)
		if index != 0 && beginPattern.MatchString(trimmed) {
			t.Fatalf("line %d opens a second transaction: %q", index+1, trimmed)
		}
		if index != len(lines)-1 && commitPattern.MatchString(trimmed) {
			t.Fatalf("line %d commits before the end, so the migration is partially durable: %q", index+1, trimmed)
		}
		if rollbackPattern.MatchString(trimmed) {
			t.Fatalf("line %d rolls back inside the file, so the boundary is not a single transaction: %q", index+1, trimmed)
		}
	}
}

// TestMigrationHasNoPragmaStatement verifies that the migration contains no
// PRAGMA.
//
// A PRAGMA is not transactional in SQLite: it takes effect immediately and is
// not undone by a rollback. A PRAGMA inside this file would therefore leave a
// half-applied configuration behind even when the schema rolls back.
func TestMigrationHasNoPragmaStatement(t *testing.T) {
	text := migrationText(t, "002_resource_mapping_kind.sql")
	if regexp.MustCompile(`(?i)\bPRAGMA\b`).MatchString(text) {
		t.Fatalf("migration contains a PRAGMA, which a rollback cannot undo:\n%s", text)
	}
}

// TestFailedMigrationLeavesNoLegacyTableBehind verifies that a failed copy
// removes the renamed legacy table instead of leaving it as debris.
//
// The rename at the start of the migration creates resource_mapping_legacy. If
// the rollback only restored resource_mapping and left the legacy table behind,
// the next Open would find two tables holding the same rows and the schema
// inspection would still report the legacy shape, hiding the debris.
func TestFailedMigrationLeavesNoLegacyTableBehind(t *testing.T) {
	ctx := context.Background()
	path := writeLegacyDatabase(t, legacySchema, [][2]string{
		{"session-one", "res_duplicate"},
		{"session-two", "res_duplicate"},
	})
	if store, err := Open(ctx, path); err == nil {
		_ = store.Close()
		t.Fatal("migration with duplicate resource IDs succeeded")
	}
	tables := tableNames(t, path)
	if tables["resource_mapping_legacy"] {
		t.Fatalf("failed migration left resource_mapping_legacy behind: %#v", tables)
	}
	if !tables["resource_mapping"] {
		t.Fatalf("failed migration removed resource_mapping: %#v", tables)
	}
}

// TestFailedMigrationRestoresTheLegacySchema verifies that the columns return
// to the pre-migration shape.
//
// Asserting only that Open returned an error would accept a database whose
// table had already been replaced by the new shape, because the error alone
// says nothing about what survived.
func TestFailedMigrationRestoresTheLegacySchema(t *testing.T) {
	ctx := context.Background()
	path := writeLegacyDatabase(t, legacySchema, [][2]string{
		{"session-one", "res_duplicate"},
		{"session-two", "res_duplicate"},
	})
	if store, err := Open(ctx, path); err == nil {
		_ = store.Close()
		t.Fatal("migration with duplicate resource IDs succeeded")
	}
	columns := columnNames(t, path, "resource_mapping")
	if !columns["provider_key"] {
		t.Fatalf("legacy column provider_key is gone after a failed migration: %#v", columns)
	}
	if columns["provider_resource_key"] || columns["resource_kind"] {
		t.Fatalf("failed migration left the new columns in place: %#v", columns)
	}
}

// TestFailedMigrationKeepsLegacyRowsByteForByte verifies that the stored rows
// survive unchanged.
//
// A rollback that restored the schema but lost rows would still pass a
// column-only check, and the operator would silently lose every mapping.
func TestFailedMigrationKeepsLegacyRowsByteForByte(t *testing.T) {
	ctx := context.Background()
	path := writeLegacyDatabase(t, legacySchema, [][2]string{
		{"session-one", "res_duplicate"},
		{"session-two", "res_duplicate"},
	})
	if store, err := Open(ctx, path); err == nil {
		_ = store.Close()
		t.Fatal("migration with duplicate resource IDs succeeded")
	}
	ids := legacyRows(t, path)
	if len(ids) != 2 {
		t.Fatalf("legacy rows=%v, want the two original rows", ids)
	}
	if ids[0] != "res_duplicate" || ids[1] != "res_duplicate" {
		t.Fatalf("legacy rows=%v, want both original resource IDs", ids)
	}
}

// TestFailedMigrationAtRenameLeavesSchemaIntact verifies a failure that happens
// before the copy, not during it.
//
// The existing rollback test fails inside INSERT ... SELECT. A failure at the
// rename is a different point in the transaction: nothing has been copied yet,
// so the rollback must restore a table that was only renamed.
func TestFailedMigrationAtRenameLeavesSchemaIntact(t *testing.T) {
	ctx := context.Background()
	path := writeLegacyDatabase(t, legacySchema, [][2]string{
		{"session-one", "res_one"},
	})
	db, err := sql.Open("sqlite", path)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := db.Exec(`CREATE TABLE resource_mapping_legacy (placeholder TEXT)`); err != nil {
		db.Close()
		t.Fatal(err)
	}
	if err := db.Close(); err != nil {
		t.Fatal(err)
	}

	if store, err := Open(ctx, path); err == nil {
		_ = store.Close()
		t.Fatal("migration succeeded even though the rename target already existed")
	}
	columns := columnNames(t, path, "resource_mapping")
	if !columns["provider_key"] || columns["provider_resource_key"] || columns["resource_kind"] {
		t.Fatalf("a failure at the rename changed the schema: %#v", columns)
	}
	ids := legacyRows(t, path)
	if len(ids) != 1 || ids[0] != "res_one" {
		t.Fatalf("a failure at the rename lost the legacy row: %v", ids)
	}
}

// TestFailedMigrationIsRetriedNotAccepted verifies that a database left in the
// legacy shape is rejected again on the next Open rather than being accepted as
// migrated.
//
// A migration that rolled back but recorded success would let the Endpoint run
// against the old schema, and every later mapping call would fail at runtime
// instead of at startup.
func TestFailedMigrationIsRetriedNotAccepted(t *testing.T) {
	ctx := context.Background()
	path := writeLegacyDatabase(t, legacySchema, [][2]string{
		{"session-one", "res_duplicate"},
		{"session-two", "res_duplicate"},
	})
	for attempt := 1; attempt <= 2; attempt++ {
		store, err := Open(ctx, path)
		if err == nil {
			_ = store.Close()
			t.Fatalf("attempt %d accepted a database the migration could not convert", attempt)
		}
	}
	columns := columnNames(t, path, "resource_mapping")
	if !columns["provider_key"] || columns["provider_resource_key"] || columns["resource_kind"] {
		t.Fatalf("repeated failed attempts changed the schema: %#v", columns)
	}
}

// TestMigrationFailureLeavesNoNewSchemaTable verifies that the new table shape
// never becomes visible after a failed migration.
//
// The migration creates the new table before copying. If the rollback were
// incomplete, the new empty table would remain and the next Open would see the
// new columns and skip the migration, permanently losing every mapping.
func TestMigrationFailureLeavesNoNewSchemaTable(t *testing.T) {
	ctx := context.Background()
	path := writeLegacyDatabase(t, legacySchema, [][2]string{
		{"session-one", "res_duplicate"},
		{"session-two", "res_duplicate"},
	})
	if store, err := Open(ctx, path); err == nil {
		_ = store.Close()
		t.Fatal("migration with duplicate resource IDs succeeded")
	}
	columns := columnNames(t, path, "resource_mapping")
	if columns["resource_kind"] || columns["provider_resource_key"] {
		t.Fatalf("the new table shape survived a failed migration: %#v", columns)
	}
	if !columns["provider_key"] {
		t.Fatalf("the legacy table shape is gone after a failed migration: %#v", columns)
	}
}
