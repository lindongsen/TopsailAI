package endpointstorage

import (
	"context"
	"os"
	"path/filepath"
	"testing"
)

// requireMode fails when path does not carry exactly the wanted permission bits.
// The full mode is compared rather than only the world-readable bit, because a
// group-readable file would still be readable by a container that shares the
// Endpoint's group.
func requireMode(t *testing.T, path string, want os.FileMode) {
	t.Helper()
	info, err := os.Stat(path)
	if err != nil {
		t.Fatalf("stat %q: %v", path, err)
	}
	if got := info.Mode().Perm(); got != want {
		t.Fatalf("%s mode=%04o want=%04o", path, got, want)
	}
}

// TestDatabaseFileIsNotWorldReadable proves a freshly created Endpoint database
// and its directory are not readable by another local account.
//
// This is the property the runbook claims and the Server container probe checks.
// Ownership alone does not provide it: the container runs as a different uid but
// can still read a world-readable file, so the permission bits are the layer that
// enforces the boundary.
func TestDatabaseFileIsNotWorldReadable(t *testing.T) {
	ctx := context.Background()
	dir := filepath.Join(t.TempDir(), "ac.topsail")
	path := filepath.Join(dir, "endpoint.sqlite")

	store, err := Open(ctx, path)
	if err != nil {
		t.Fatalf("open endpoint database: %v", err)
	}
	t.Cleanup(func() { _ = store.Close() })

	requireMode(t, path, 0o600)
	requireMode(t, dir, 0o750)
}

// TestExistingPermissiveDatabaseIsRestricted proves the upgrade path.
//
// Every deployed Endpoint already holds a 0644 database inside a 0755 directory,
// created by SQLite from the process umask. A fix that only affected new installs
// would leave the whole fleet exposed, so an existing permissive file and
// directory must be corrected when the database is opened.
func TestExistingPermissiveDatabaseIsRestricted(t *testing.T) {
	ctx := context.Background()
	dir := filepath.Join(t.TempDir(), "ac.topsail")
	if err := os.MkdirAll(dir, 0o755); err != nil {
		t.Fatalf("create permissive directory: %v", err)
	}
	path := filepath.Join(dir, "endpoint.sqlite")
	if err := os.WriteFile(path, nil, 0o644); err != nil {
		t.Fatalf("create permissive database file: %v", err)
	}
	// WriteFile applies the umask, so the mode is set explicitly to model the
	// deployed state rather than whatever this host's umask happens to produce.
	if err := os.Chmod(path, 0o644); err != nil {
		t.Fatalf("set permissive file mode: %v", err)
	}
	if err := os.Chmod(dir, 0o755); err != nil {
		t.Fatalf("set permissive directory mode: %v", err)
	}
	requireMode(t, path, 0o644)
	requireMode(t, dir, 0o755)

	store, err := Open(ctx, path)
	if err != nil {
		t.Fatalf("open endpoint database: %v", err)
	}
	t.Cleanup(func() { _ = store.Close() })

	requireMode(t, path, 0o600)
	requireMode(t, dir, 0o750)
}

// TestDatabaseStaysRestrictedAfterWrite proves the mode survives real SQLite
// activity. SQLite creates the rollback journal beside the database, so a mode
// applied only at open time could be lost once the database is written.
func TestDatabaseStaysRestrictedAfterWrite(t *testing.T) {
	ctx := context.Background()
	dir := filepath.Join(t.TempDir(), "ac.topsail")
	path := filepath.Join(dir, "endpoint.sqlite")

	store, err := Open(ctx, path)
	if err != nil {
		t.Fatalf("open endpoint database: %v", err)
	}
	t.Cleanup(func() { _ = store.Close() })

	if _, err := store.GetOrCreateResourceID(ctx, "adapter-a", "session", "provider-key", 100); err != nil {
		t.Fatalf("write to endpoint database: %v", err)
	}

	requireMode(t, path, 0o600)
	requireMode(t, dir, 0o750)
}

// TestInMemoryDatabaseSkipsFilePreparation proves the in-memory form still opens.
// It has no path on disk, so file preparation must not reject it.
func TestInMemoryDatabaseSkipsFilePreparation(t *testing.T) {
	ctx := context.Background()
	store, err := Open(ctx, ":memory:")
	if err != nil {
		t.Fatalf("open in-memory endpoint database: %v", err)
	}
	t.Cleanup(func() { _ = store.Close() })

	if _, err := store.GetOrCreateResourceID(ctx, "adapter-a", "session", "provider-key", 100); err != nil {
		t.Fatalf("write to in-memory endpoint database: %v", err)
	}
}
