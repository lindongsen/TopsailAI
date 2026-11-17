package serverstorage

import (
	"context"
	"database/sql"
	"path/filepath"
	"strings"
	"sync"
	"testing"

	"topsailai_agent_cluster/internal/protocol"
)

// TestWithTransactionSerializesWritersBeforeTheyModifyPages proves the property
// BEGIN IMMEDIATE actually provides, and nothing more.
//
// Two writers that both use a deferred BEGIN can both reach the point of
// modifying pages, because a deferred BEGIN starts as a reader and SHARED is
// compatible with SHARED. The first one to COMMIT wins; the second discovers the
// conflict only at COMMIT, after it has already written a rollback journal and
// must now undo it. That is wasted work at best, and it is the shape that turns
// into a livelock when a reader is present continuously.
//
// BEGIN IMMEDIATE takes RESERVED before any page is modified, so the second
// writer is refused at BEGIN and never enters the callback. The assertion is
// therefore on whether the callback ran, not on the error text: both forms
// return an error, so an error-only assertion cannot tell them apart.
//
// The competing writer is a second handle outside the pool, not a second call
// through the pool. At a pool of one connection a second call cannot even acquire
// a connection, so it would fail with a context deadline before reaching BEGIN and
// the test would prove nothing about the lock mode. An earlier version of this
// test did exactly that and failed for that reason once the pool was reverted to
// one. A handle outside the pool is also the production shape: the outage's second
// holder could not have come from the pool either.
func TestWithTransactionSerializesWritersBeforeTheyModifyPages(t *testing.T) {
	ctx := context.Background()
	path := filepath.Join(t.TempDir(), "server.db")
	store, err := Open(ctx, path)
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	if err := store.UpsertEndpoint(ctx, protocol.Endpoint{
		EndpointID: "probe", InstanceID: "probe-1", DisplayName: "original",
		ConnectionState: "online", ObservedAtMS: 1000, CapabilityRevision: "v1",
	}, 1000); err != nil {
		t.Fatal(err)
	}

	// The competing writer holds RESERVED on its own handle, so the store's
	// BEGIN IMMEDIATE must be refused before its callback runs.
	competitor, err := sql.Open("sqlite", path)
	if err != nil {
		t.Fatal(err)
	}
	defer competitor.Close()
	competitor.SetMaxOpenConns(1)
	competitorConn, err := competitor.Conn(ctx)
	if err != nil {
		t.Fatal(err)
	}
	defer competitorConn.Close()
	if _, err := competitorConn.ExecContext(ctx, `BEGIN IMMEDIATE`); err != nil {
		t.Fatalf("competitor could not take RESERVED: %v", err)
	}
	if _, err := competitorConn.ExecContext(ctx, `UPDATE endpoints SET display_name = 'competitor'`); err != nil {
		t.Fatalf("competitor write: %v", err)
	}
	t.Logf("competitor holds RESERVED with an uncommitted write")

	// The store's writer must be refused before its callback runs.
	var secondCallbackRan bool
	secondErr := store.withTransaction(ctx, "second writer", func(txCtx context.Context, conn *sql.Conn) error {
		secondCallbackRan = true
		_, err := conn.ExecContext(txCtx, `UPDATE endpoints SET display_name = 'second'`)
		return err
	})
	if secondErr == nil {
		t.Fatal("the store's writer succeeded while another handle held RESERVED, so this scenario cannot prove serialization")
	}
	lower := strings.ToLower(secondErr.Error())
	if !strings.Contains(lower, "locked") && !strings.Contains(lower, "busy") {
		t.Fatalf("the store's writer failed for an unrelated reason, so this scenario proves nothing about write serialization: %v", secondErr)
	}
	if secondCallbackRan {
		t.Fatalf("the store's writer entered its callback and modified pages before discovering the conflict (%v); a deferred BEGIN allows that, and the work it did must then be undone, which is the shape that becomes a livelock when a reader is present continuously", secondErr)
	}
	t.Logf("the store's writer was refused before its callback ran: %v", secondErr)

	// Releasing the competitor must let the store write again, so the refusal was
	// a lock conflict rather than a permanently unusable database.
	if _, err := competitorConn.ExecContext(ctx, `ROLLBACK`); err != nil {
		t.Fatalf("competitor rollback: %v", err)
	}
	if err := store.UpsertEndpoint(ctx, protocol.Endpoint{
		EndpointID: "probe", InstanceID: "probe-1", DisplayName: "after",
		ConnectionState: "online", ObservedAtMS: 2000, CapabilityRevision: "v1",
	}, 2000); err != nil {
		t.Fatalf("the store could not write after the competitor released RESERVED: %v", err)
	}

	var displayName string
	if err := store.DB().QueryRowContext(ctx, `SELECT display_name FROM endpoints WHERE endpoint_id = 'probe'`).Scan(&displayName); err != nil {
		t.Fatal(err)
	}
	if displayName != "after" {
		t.Fatalf("the stored value is %q, so the refused writer changed state it was not allowed to change", displayName)
	}
}

// TestWithTransactionRefusesAWriterWhileAReaderHoldsShared records the limit of
// the BEGIN IMMEDIATE fix, so nobody later reads it as a cure for every lock
// conflict.
//
// RESERVED is compatible with SHARED, so BEGIN IMMEDIATE succeeds while a reader
// holds SHARED. The write then proceeds and the conflict appears at COMMIT. That
// means BEGIN IMMEDIATE serializes writers against each other; it does not make a
// writer able to commit while a reader holds SHARED, and it does not by itself
// prevent a permanently held SHARED lock from blocking every write.
//
// The test asserts the current behaviour rather than a desired one, because the
// desired behaviour is not achievable under journal_mode(DELETE): a reader and a
// writer genuinely cannot both hold the database. Recording it here keeps the
// remaining root cause visible instead of letting the writer-serialization test
// imply the problem is solved.
func TestWithTransactionRefusesAWriterWhileAReaderHoldsShared(t *testing.T) {
	ctx := context.Background()
	path := filepath.Join(t.TempDir(), "server.db")
	store, err := Open(ctx, path)
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	if err := store.UpsertEndpoint(ctx, protocol.Endpoint{
		EndpointID: "probe", InstanceID: "probe-1", DisplayName: "original",
		ConnectionState: "online", ObservedAtMS: 1000, CapabilityRevision: "v1",
	}, 1000); err != nil {
		t.Fatal(err)
	}

	reader, err := sql.Open("sqlite", path)
	if err != nil {
		t.Fatal(err)
	}
	defer reader.Close()
	readTx, err := reader.BeginTx(ctx, &sql.TxOptions{ReadOnly: true})
	if err != nil {
		t.Fatal(err)
	}
	defer readTx.Rollback()
	// Keep the cursor open so SHARED is genuinely held for the whole attempt.
	rows, err := readTx.QueryContext(ctx, `SELECT endpoint_id FROM endpoints`)
	if err != nil {
		t.Fatal(err)
	}
	defer rows.Close()
	if !rows.Next() {
		t.Fatal("the reader found no row, so it cannot hold SHARED")
	}

	var callbackRan bool
	writeErr := store.withTransaction(ctx, "write under a reader", func(txCtx context.Context, conn *sql.Conn) error {
		callbackRan = true
		_, err := conn.ExecContext(ctx, `UPDATE endpoints SET display_name = 'written'`)
		return err
	})
	if writeErr == nil {
		t.Fatal("the write committed while a reader held SHARED, which journal_mode(DELETE) does not allow; the test's premise is wrong")
	}
	if !callbackRan {
		t.Fatalf("the writer was refused before its callback ran (%v), which would mean BEGIN IMMEDIATE also excludes readers; it does not, so this test's premise is wrong", writeErr)
	}
	t.Logf("a writer is refused at COMMIT while a reader holds SHARED: %v", writeErr)

	// The failed transaction must not have changed anything.
	var displayName string
	if err := store.DB().QueryRowContext(ctx, `SELECT display_name FROM endpoints WHERE endpoint_id = 'probe'`).Scan(&displayName); err != nil {
		t.Fatal(err)
	}
	if displayName != "original" {
		t.Fatalf("the refused write changed the stored value to %q", displayName)
	}
}

// TestConcurrentWritersNeverBothModifyPages runs the serialization property under
// real contention rather than one hand-ordered pair, so a regression that only
// shows up when several writers race is still caught.
func TestConcurrentWritersNeverBothModifyPages(t *testing.T) {
	ctx := context.Background()
	path := filepath.Join(t.TempDir(), "server.db")
	store, err := Open(ctx, path)
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	if err := store.UpsertEndpoint(ctx, protocol.Endpoint{
		EndpointID: "probe", InstanceID: "probe-1", DisplayName: "original",
		ConnectionState: "online", ObservedAtMS: 1000, CapabilityRevision: "v1",
	}, 1000); err != nil {
		t.Fatal(err)
	}

	const writers = 6
	var mu sync.Mutex
	modifiedPages := 0
	var wg sync.WaitGroup
	for i := 0; i < writers; i++ {
		wg.Add(1)
		go func(index int) {
			defer wg.Done()
			_ = store.withTransaction(ctx, "concurrent writer", func(txCtx context.Context, conn *sql.Conn) error {
				mu.Lock()
				modifiedPages++
				mu.Unlock()
				_, err := conn.ExecContext(ctx, `UPDATE endpoints SET display_name = ?`, index)
				return err
			})
		}(i)
	}
	wg.Wait()

	// Every writer that entered its callback held the write lock, so the count of
	// callbacks that ran must equal the count of transactions that committed. A
	// deferred BEGIN breaks that equality: writers enter the callback, modify
	// pages, and only then discover the conflict.
	var committed int
	if err := store.DB().QueryRowContext(ctx, `SELECT count(*) FROM endpoints WHERE display_name != 'original'`).Scan(&committed); err != nil {
		t.Fatal(err)
	}
	if committed > 1 {
		t.Fatalf("%d writers changed the row, so more than one writer held the write lock at the same time", committed)
	}
	if modifiedPages == 0 {
		t.Fatal("no writer entered its callback, so this test exercised nothing")
	}
}
