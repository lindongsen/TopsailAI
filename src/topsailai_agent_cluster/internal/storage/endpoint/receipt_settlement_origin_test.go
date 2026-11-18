package endpointstorage

import (
	"context"
	"database/sql"
	"path/filepath"
	"testing"

	"topsailai_agent_cluster/internal/protocol"
)

// openSettlementStore opens a store at a known path so a test can read the
// settlement table directly. The store does not expose a settlement reader, and
// adding one only for tests would put a production method on the API with no
// caller.
func openSettlementStore(t *testing.T) (*Store, string) {
	t.Helper()
	path := filepath.Join(t.TempDir(), "endpoint.sqlite")
	store, err := Open(context.Background(), path)
	if err != nil {
		t.Fatalf("open endpoint store: %v", err)
	}
	t.Cleanup(func() { _ = store.Close() })
	return store, path
}

// readSettlement returns the stored origin and reason for one command.
func readSettlement(t *testing.T, path, commandID string) (string, sql.NullString, bool) {
	t.Helper()
	db, err := sql.Open("sqlite", path+"?_pragma=busy_timeout(5000)")
	if err != nil {
		t.Fatalf("open endpoint database: %v", err)
	}
	defer func() { _ = db.Close() }()
	var origin string
	var reason sql.NullString
	err = db.QueryRow(`SELECT settled_by, reason FROM receipt_settlement WHERE command_id = ?`, commandID).Scan(&origin, &reason)
	if err == sql.ErrNoRows {
		return "", sql.NullString{}, false
	}
	if err != nil {
		t.Fatalf("read settlement for %q: %v", commandID, err)
	}
	return origin, reason, true
}

// TestSettleReceiptRecordsTheAcknowledgementOrigin proves an acknowledgement is
// stored as its own terminal outcome rather than as a rejection.
//
// The two outcomes are different facts: a rejection says the receipt can never be
// applied, an acknowledgement says the Server already holds it. Collapsing them
// into one column would make a reader unable to tell a delivery confirmation from
// an integrity refusal.
func TestSettleReceiptRecordsTheAcknowledgementOrigin(t *testing.T) {
	ctx := context.Background()
	store, path := openSettlementStore(t)
	recordReceipt(t, store, "cmd-a")

	if err := store.SettleReceipt(ctx, "cmd-a", protocol.SettlementOriginAcknowledgement, "", 3); err != nil {
		t.Fatalf("settle acknowledged receipt: %v", err)
	}

	origin, reason, found := readSettlement(t, path, "cmd-a")
	if !found {
		t.Fatal("an acknowledged receipt left no settlement row, so the next reconnect re-sends it")
	}
	if origin != string(protocol.SettlementOriginAcknowledgement) {
		t.Fatalf("settled_by=%q, want %q", origin, protocol.SettlementOriginAcknowledgement)
	}
	if reason.Valid {
		t.Fatalf("reason=%q for an acknowledgement, want NULL because an acknowledgement carries no rejection reason", reason.String)
	}
}

// TestSettleReceiptRecordsTheRejectionOrigin proves the rejection path still
// stores its reason under the rejection origin.
func TestSettleReceiptRecordsTheRejectionOrigin(t *testing.T) {
	ctx := context.Background()
	store, path := openSettlementStore(t)
	recordReceipt(t, store, "cmd-a")

	if err := store.SettleReceipt(ctx, "cmd-a", protocol.SettlementOriginRejection, protocol.ReceiptRejectedUnknownCommand, 3); err != nil {
		t.Fatalf("settle rejected receipt: %v", err)
	}

	origin, reason, found := readSettlement(t, path, "cmd-a")
	if !found {
		t.Fatal("a rejected receipt left no settlement row")
	}
	if origin != string(protocol.SettlementOriginRejection) {
		t.Fatalf("settled_by=%q, want %q", origin, protocol.SettlementOriginRejection)
	}
	if !reason.Valid || reason.String != string(protocol.ReceiptRejectedUnknownCommand) {
		t.Fatalf("reason=%v, want %q", reason, protocol.ReceiptRejectedUnknownCommand)
	}
}

// TestSettleReceiptRefusesAnAcknowledgementWithAReason proves the two axes
// cannot be mixed. An acknowledgement that carries a rejection reason would
// store a row whose origin and reason contradict each other.
func TestSettleReceiptRefusesAnAcknowledgementWithAReason(t *testing.T) {
	ctx := context.Background()
	store, path := openSettlementStore(t)
	recordReceipt(t, store, "cmd-a")

	err := store.SettleReceipt(ctx, "cmd-a", protocol.SettlementOriginAcknowledgement, protocol.ReceiptRejectedUnknownCommand, 3)
	if err == nil {
		t.Fatal("an acknowledgement carrying a rejection reason was accepted")
	}
	if _, _, found := readSettlement(t, path, "cmd-a"); found {
		t.Fatal("a refused settlement still wrote a row")
	}
}

// TestSettleReceiptRefusesARejectionWithoutAReason proves a rejection must name
// why the receipt can never be applied, because that reason is the only record
// of the decision.
func TestSettleReceiptRefusesARejectionWithoutAReason(t *testing.T) {
	ctx := context.Background()
	store, path := openSettlementStore(t)
	recordReceipt(t, store, "cmd-a")

	err := store.SettleReceipt(ctx, "cmd-a", protocol.SettlementOriginRejection, "", 3)
	if err == nil {
		t.Fatal("a rejection without a reason was accepted")
	}
	if _, _, found := readSettlement(t, path, "cmd-a"); found {
		t.Fatal("a refused settlement still wrote a row")
	}
}

// TestSettleReceiptRefusesAnEmptyOrigin proves an unclassified settlement is
// refused rather than stored with an empty origin, which no reader could
// interpret.
func TestSettleReceiptRefusesAnEmptyOrigin(t *testing.T) {
	ctx := context.Background()
	store, path := openSettlementStore(t)
	recordReceipt(t, store, "cmd-a")

	err := store.SettleReceipt(ctx, "cmd-a", "", protocol.ReceiptRejectedUnknownCommand, 3)
	if err == nil {
		t.Fatal("a settlement without an origin was accepted")
	}
	if _, _, found := readSettlement(t, path, "cmd-a"); found {
		t.Fatal("a refused settlement still wrote a row")
	}
}

// TestSettleAllRecordedReceiptsStoresTheRejectionOrigin proves the bulk re-home
// path writes the rejection origin, so a bulk settlement is never mistaken for
// an acknowledgement.
func TestSettleAllRecordedReceiptsStoresTheRejectionOrigin(t *testing.T) {
	ctx := context.Background()
	store, path := openSettlementStore(t)
	recordReceipt(t, store, "cmd-a")

	if _, err := store.SettleAllRecordedReceipts(ctx, protocol.ReceiptRejectedUnknownCommand, 5); err != nil {
		t.Fatalf("settle all: %v", err)
	}

	origin, reason, found := readSettlement(t, path, "cmd-a")
	if !found {
		t.Fatal("a bulk settlement left no row")
	}
	if origin != string(protocol.SettlementOriginRejection) {
		t.Fatalf("settled_by=%q, want %q", origin, protocol.SettlementOriginRejection)
	}
	if !reason.Valid || reason.String != string(protocol.ReceiptRejectedUnknownCommand) {
		t.Fatalf("reason=%v, want %q", reason, protocol.ReceiptRejectedUnknownCommand)
	}
}

// legacySettlementSchema is the pre-003 shape: no origin column and a NOT NULL
// reason, so an acknowledgement could not be stored at all.
const legacySettlementSchema = `CREATE TABLE receipt_settlement (
	command_id TEXT PRIMARY KEY,
	reason TEXT NOT NULL,
	settled_at_ms BIGINT NOT NULL
);`

// buildLegacySettlementDatabase writes a pre-003 database holding one settled
// rejection.
func buildLegacySettlementDatabase(t *testing.T, path string) {
	t.Helper()
	db, err := sql.Open("sqlite", path)
	if err != nil {
		t.Fatalf("open legacy database: %v", err)
	}
	defer func() { _ = db.Close() }()
	if _, err := db.Exec(legacySettlementSchema); err != nil {
		t.Fatalf("create legacy settlement schema: %v", err)
	}
	if _, err := db.Exec(`INSERT INTO receipt_settlement(command_id, reason, settled_at_ms) VALUES('cmd-legacy','unknown_command',1)`); err != nil {
		t.Fatalf("insert legacy settlement: %v", err)
	}
}

// TestMigrationAddsTheSettlementOriginToALegacyDatabase proves an existing
// database is converted: the origin column appears, the stored row is classified
// as a rejection, and the reason column becomes nullable.
//
// The nullable check is the point of rebuilding the table instead of adding a
// column. ALTER TABLE cannot relax NOT NULL, so a database that only gained the
// origin column would still refuse to store an acknowledgement.
func TestMigrationAddsTheSettlementOriginToALegacyDatabase(t *testing.T) {
	path := filepath.Join(t.TempDir(), "legacy.db")
	buildLegacySettlementDatabase(t, path)

	store, err := Open(context.Background(), path)
	if err != nil {
		t.Fatalf("open legacy database: %v", err)
	}
	defer func() { _ = store.Close() }()

	origin, reason, found := readSettlement(t, path, "cmd-legacy")
	if !found {
		t.Fatal("the migration lost the existing settlement row")
	}
	if origin != string(protocol.SettlementOriginRejection) {
		t.Fatalf("settled_by=%q for a converted row, want %q", origin, protocol.SettlementOriginRejection)
	}
	if !reason.Valid || reason.String != string(protocol.ReceiptRejectedUnknownCommand) {
		t.Fatalf("reason=%v for a converted row, want %q", reason, protocol.ReceiptRejectedUnknownCommand)
	}

	db, err := sql.Open("sqlite", path+"?_pragma=busy_timeout(5000)")
	if err != nil {
		t.Fatalf("open converted database: %v", err)
	}
	defer func() { _ = db.Close() }()
	if _, err := db.Exec(`INSERT INTO receipt_settlement(command_id, reason, settled_by, settled_at_ms) VALUES('cmd-null', NULL, 'acknowledgement', 2)`); err != nil {
		t.Fatalf("the converted table still refuses a NULL reason, so an acknowledgement cannot be stored: %v", err)
	}
}

// TestLegacyThreeColumnInsertStillSucceeds proves an older binary can keep
// writing the table after the migration.
//
// The downgrade guard pins command_journal and source_cache, so an older binary
// is expected to run against this database. That binary inserts only
// (command_id, reason, settled_at_ms); without a DEFAULT on settled_by its insert
// would fail and the older Endpoint could not settle anything.
func TestLegacyThreeColumnInsertStillSucceeds(t *testing.T) {
	path := filepath.Join(t.TempDir(), "legacy.db")
	buildLegacySettlementDatabase(t, path)

	store, err := Open(context.Background(), path)
	if err != nil {
		t.Fatalf("open legacy database: %v", err)
	}
	defer func() { _ = store.Close() }()

	db, err := sql.Open("sqlite", path+"?_pragma=busy_timeout(5000)")
	if err != nil {
		t.Fatalf("open converted database: %v", err)
	}
	defer func() { _ = db.Close() }()
	if _, err := db.Exec(`INSERT INTO receipt_settlement(command_id, reason, settled_at_ms) VALUES('cmd-older','unknown_command',3)`); err != nil {
		t.Fatalf("an older binary's three-column insert failed against the migrated table: %v", err)
	}
	origin, _, found := readSettlement(t, path, "cmd-older")
	if !found {
		t.Fatal("the older binary's insert left no row")
	}
	if origin != string(protocol.SettlementOriginRejection) {
		t.Fatalf("settled_by=%q for an older binary's insert, want the %q default", origin, protocol.SettlementOriginRejection)
	}
}
