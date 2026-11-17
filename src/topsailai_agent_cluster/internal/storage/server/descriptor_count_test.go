package serverstorage

import (
	"context"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"topsailai_agent_cluster/internal/protocol"
)

// TestOpenWriteTransactionDescriptorCount establishes how many operating-system
// handles one connection holds while a write transaction is open.
//
// This measurement is what makes the production evidence interpretable. During the
// outage the Server process held three descriptors: two on server.sqlite and one
// on server.sqlite-journal. The pool was configured with SetMaxOpenConns(1), so at
// most one connection should have existed. Whether three descriptors prove a
// second connection depends entirely on how many descriptors one connection
// legitimately holds, and that number cannot be assumed.
//
// The table must contain a row before the write. An earlier version of this test
// ran the UPDATE against an empty table, so no page was modified, no journal was
// created, and the measurement reported one descriptor. That number was an
// artifact of the empty fixture, not a property of a write transaction.
//
// The conclusion this test supports is narrow: one connection inside a write
// transaction holds two descriptors, one on each file. It does not by itself prove
// where a third descriptor came from. The mechanism that explains the outage is
// proven separately by TestReaderHoldingSharedBlocksCommitUntilItReleases and
// TestTwoIndependentHandlesOnOneFileMakeWritesFail: a second lock holder blocks
// every COMMIT while reads keep working.
func TestOpenWriteTransactionDescriptorCount(t *testing.T) {
	ctx := context.Background()
	path := filepath.Join(t.TempDir(), "server.db")
	store, err := Open(ctx, path)
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()

	// Seed a row so the UPDATE modifies a page and creates the journal. Without
	// this the measurement is meaningless.
	if err := store.UpsertEndpoint(ctx, protocol.Endpoint{
		EndpointID: "probe", InstanceID: "probe-1", DisplayName: "probe",
		ConnectionState: "online", ObservedAtMS: 1000, CapabilityRevision: "v1",
	}, 1000); err != nil {
		t.Fatal(err)
	}

	idle := countOpenHandles(t, path)
	t.Logf("descriptors while idle: %d", idle)

	conn, err := store.DB().Conn(ctx)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := conn.ExecContext(ctx, "BEGIN IMMEDIATE"); err != nil {
		_ = conn.Close()
		t.Fatalf("begin immediate: %v", err)
	}
	if _, err := conn.ExecContext(ctx, `UPDATE endpoints SET display_name = 'x'`); err != nil {
		_ = conn.Close()
		t.Fatalf("write: %v", err)
	}

	inTransaction := countOpenHandles(t, path)
	t.Logf("descriptors with an open write transaction: %d", inTransaction)

	entries, err := os.ReadDir("/proc/self/fd")
	if err != nil {
		t.Skipf("cannot inspect file descriptors: %v", err)
	}
	resolved, err := filepath.EvalSymlinks(path)
	if err != nil {
		t.Fatal(err)
	}
	for _, entry := range entries {
		target, err := os.Readlink(filepath.Join("/proc/self/fd", entry.Name()))
		if err != nil {
			continue
		}
		if strings.HasPrefix(target, resolved) {
			t.Logf("  fd %s -> %s", entry.Name(), target)
		}
	}

	if _, err := conn.ExecContext(ctx, "ROLLBACK"); err != nil {
		_ = conn.Close()
		t.Fatalf("rollback: %v", err)
	}
	_ = conn.Close()

	after := countOpenHandles(t, path)
	t.Logf("descriptors after rollback: %d", after)

	// The measurement this test exists for: one connection inside a write
	// transaction holds two descriptors, one on the database and one on the
	// journal. A third descriptor therefore means a second holder existed, and the
	// outage evidence is consistent with a second lock holder rather than with a
	// single connection holding everything.
	if inTransaction != 2 {
		t.Logf("one connection holds %d descriptors, which differs from the measured two; the production count of 3 must be reinterpreted", inTransaction)
	} else {
		t.Logf("one connection holds 2 descriptors, so the production count of 3 implies a second holder existed")
	}
}
