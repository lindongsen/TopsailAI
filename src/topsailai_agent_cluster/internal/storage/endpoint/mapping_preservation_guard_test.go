package endpointstorage

import (
	"context"
	"path/filepath"
	"regexp"
	"strings"
	"testing"

	"topsailai_agent_cluster/internal/protocol"
)

// migrationTableBody returns the text between the parentheses of the CREATE TABLE
// statement that declares resource_mapping in the named migration. The guard reads
// the schema text instead of restating a column list, so a migration that changes
// the table fails here rather than silently changing what is preserved.
func migrationTableBody(t *testing.T, fileName string) string {
	t.Helper()
	document, err := migrationFS.ReadFile("internal/migrations/" + fileName)
	if err != nil {
		t.Fatalf("read %s: %v", fileName, err)
	}
	pattern := regexp.MustCompile(`(?s)CREATE TABLE (?:IF NOT EXISTS )?resource_mapping\s*\((.*?)\n\);`)
	match := pattern.FindStringSubmatch(string(document))
	if match == nil {
		t.Fatalf("%s no longer declares resource_mapping, so this guard checked nothing", fileName)
	}
	return match[1]
}

// migrationColumnNames lists the column names declared in a CREATE TABLE body and
// skips the table constraints, which are not columns.
func migrationColumnNames(t *testing.T, fileName string) []string {
	t.Helper()
	names := []string{}
	for _, line := range strings.Split(migrationTableBody(t, fileName), "\n") {
		trimmed := strings.TrimSpace(line)
		if trimmed == "" {
			continue
		}
		upper := strings.ToUpper(trimmed)
		if strings.HasPrefix(upper, "PRIMARY KEY") || strings.HasPrefix(upper, "UNIQUE") {
			continue
		}
		names = append(names, strings.Fields(trimmed)[0])
	}
	if len(names) == 0 {
		t.Fatalf("%s declares no columns, so this guard checked nothing", fileName)
	}
	return names
}

// splitSQLList splits a comma separated SQL list and trims each entry. The lists
// this guard reads contain no nested parentheses or commas inside expressions.
func splitSQLList(list string) []string {
	entries := []string{}
	for _, entry := range strings.Split(list, ",") {
		entries = append(entries, strings.TrimSpace(entry))
	}
	return entries
}

// TestResourceMappingMigrationKeepsTheFreshSchema proves a migrated database and a
// freshly created database end up with the same resource_mapping columns. The
// migration recreates the table, so a column added to the initial schema but not to
// the migration would leave every existing database permanently behind.
func TestResourceMappingMigrationKeepsTheFreshSchema(t *testing.T) {
	fresh := migrationColumnNames(t, "001_initial.sql")
	migrated := migrationColumnNames(t, "002_resource_mapping_kind.sql")
	if len(fresh) != len(migrated) {
		t.Fatalf("fresh columns=%v migrated columns=%v", fresh, migrated)
	}
	for index := range fresh {
		if fresh[index] != migrated[index] {
			t.Fatalf("fresh columns=%v migrated columns=%v", fresh, migrated)
		}
	}
}

// TestResourceMappingMigrationCopiesResourceIDPositionally proves the migration
// carries the existing Cluster resource ID across instead of minting a new one.
// The INSERT column list and the SELECT value list are compared position by
// position, so a reordered SELECT fails here even when the fixture rows happen to
// survive the reordering.
func TestResourceMappingMigrationCopiesResourceIDPositionally(t *testing.T) {
	document, err := migrationFS.ReadFile("internal/migrations/002_resource_mapping_kind.sql")
	if err != nil {
		t.Fatalf("read the resource mapping migration: %v", err)
	}
	pattern := regexp.MustCompile(`(?s)INSERT INTO resource_mapping\s*\(([^)]*)\)\s*SELECT\s*(.*?)\s*FROM resource_mapping_legacy`)
	match := pattern.FindStringSubmatch(string(document))
	if match == nil {
		t.Fatal("the migration no longer copies resource_mapping through INSERT ... SELECT, so this guard checked nothing")
	}
	targets := splitSQLList(match[1])
	sources := splitSQLList(match[2])
	if len(targets) != len(sources) {
		t.Fatalf("insert columns=%v select values=%v", targets, sources)
	}
	position := -1
	for index, target := range targets {
		if target == "resource_id" {
			position = index
		}
	}
	if position < 0 {
		t.Fatalf("the migration does not copy resource_id, insert columns=%v", targets)
	}
	if sources[position] != "resource_id" {
		t.Fatalf("resource_id is filled from %q, so existing Cluster resource IDs are not preserved", sources[position])
	}
}

// TestResourceMappingMigrationPreservesSessionIDForward proves the forward path
// keeps the legacy Session ID. The existing migration test resolves the Session row
// by resource ID and only exercises the forward path for a model profile, so a
// caller asking for the Session after migration was never covered.
func TestResourceMappingMigrationPreservesSessionIDForward(t *testing.T) {
	ctx := context.Background()
	path := filepath.Join(t.TempDir(), "legacy.db")
	createLegacyResourceMappings(t, path)
	store, err := Open(ctx, path)
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	mapping, err := store.GetOrCreateResourceID(ctx, "adapter-a", protocol.ResourceSession, "session-row:opaque", 300)
	if err != nil {
		t.Fatal(err)
	}
	if mapping.ResourceID != "res_session_existing" {
		t.Fatalf("session resource ID changed to %q, want res_session_existing", mapping.ResourceID)
	}
}
