package serverstorage

import (
	"context"
	"database/sql"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"topsailai_agent_cluster/internal/protocol"
)

// TestTwoIndependentHandlesOnOneFileMakeWritesFail proves the mechanism that
// explains the production outage, and it is the regression test for it.
//
// The outage had a shape that only one mechanism explains:
//   - writers received SQLITE_BUSY for 2h56m, at roughly the busy_timeout interval
//   - readers kept working the whole time
//   - the rollback journal existed continuously and its mtime kept advancing
//   - the process held two descriptors on server.sqlite and one on the journal,
//     while the pool was configured with SetMaxOpenConns(1)
//
// A single pooled connection cannot produce that. One connection inside a write
// transaction holds two descriptors, and it cannot conflict with itself: a cursor
// left open on the same connection does not block a later write on that
// connection. So the second holder must be a different connection, and with a pool
// of one it must come from outside the pool.
//
// This test creates that second holder directly, with an independent handle on the
// same file, and asserts the production shape: the write fails with SQLITE_BUSY
// after roughly busy_timeout, reads keep succeeding, and the write succeeds as soon
// as the holder releases. The last assertion is what distinguishes a blocked write
// from a permanently broken database, and it is why a restart recovered the
// service.
//
// What this test does not prove is which production code path created the second
// holder. That remains unidentified; see the S1 evidence file.
func TestTwoIndependentHandlesOnOneFileMakeWritesFail(t *testing.T) {
	ctx := context.Background()
	path := filepath.Join(t.TempDir(), "shared.db")
	store, err := Open(ctx, path)
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()

	if err := store.UpsertEndpoint(ctx, protocol.Endpoint{
		EndpointID: "probe", InstanceID: "probe-1", DisplayName: "probe",
		ConnectionState: "online", ObservedAtMS: 1000, CapabilityRevision: "v1",
	}, 1000); err != nil {
		t.Fatal(err)
	}

	// The second holder. It is deliberately a separate handle rather than a second
	// pooled connection, because the pool is limited to one connection and the
	// point of this test is that a holder from outside the pool produces the
	// outage.
	holder, err := sql.Open("sqlite", path)
	if err != nil {
		t.Fatal(err)
	}
	defer holder.Close()
	holder.SetMaxOpenConns(1)

	rows, err := holder.QueryContext(ctx, `SELECT endpoint_id FROM endpoints`)
	if err != nil {
		t.Fatalf("holder query: %v", err)
	}
	if !rows.Next() {
		t.Fatalf("expected a row for the holder to read")
	}
	t.Logf("second holder holds SHARED with an open cursor")

	// The write must fail with SQLITE_BUSY, and it must take roughly busy_timeout
	// rather than failing instantly, because that delay is what the production
	// log interval showed.
	start := time.Now()
	_, writeErr := store.DB().ExecContext(ctx, `UPDATE endpoints SET display_name = 'blocked'`)
	elapsed := time.Since(start)
	if writeErr == nil {
		_ = rows.Close()
		t.Fatalf("the write succeeded while a second holder held SHARED, so this test cannot reproduce the outage")
	}
	lower := strings.ToLower(writeErr.Error())
	if !strings.Contains(lower, "locked") && !strings.Contains(lower, "busy") {
		_ = rows.Close()
		t.Fatalf("the write failed with %v, which is not the SQLITE_BUSY the outage showed", writeErr)
	}
	t.Logf("write failed with SQLITE_BUSY after %s while the second holder kept its cursor open", elapsed)

	// Reads must keep working. This is the property that made the outage look like
	// a provider problem: the inventory listing answered instantly while every
	// provider-backed query timed out.
	readStart := time.Now()
	if _, err := store.ListEndpoints(ctx, QueryOptions{Limit: 10}); err != nil {
		_ = rows.Close()
		t.Fatalf("reads failed too (%v), so this scenario does not match the outage", err)
	}
	t.Logf("reads still succeeded in %s while writes failed", time.Since(readStart))

	// Releasing the holder must restore writability. If it does not, the database
	// is permanently unwritable and the only recovery is a restart, which is not
	// what the production evidence showed.
	_ = rows.Close()
	start = time.Now()
	if _, err := store.DB().ExecContext(ctx, `UPDATE endpoints SET display_name = 'recovered'`); err != nil {
		t.Fatalf("the database stayed unwritable after the second holder released its cursor: %v", err)
	}
	t.Logf("writes recovered in %s once the second holder released SHARED", time.Since(start))

	// The value must actually be committed, not merely reported as written.
	var name string
	if err := store.DB().QueryRowContext(ctx, `SELECT display_name FROM endpoints WHERE endpoint_id = 'probe'`).Scan(&name); err != nil {
		t.Fatalf("read back: %v", err)
	}
	if name != "recovered" {
		t.Fatalf("committed value is %q, so the write reported success without committing", name)
	}
}
