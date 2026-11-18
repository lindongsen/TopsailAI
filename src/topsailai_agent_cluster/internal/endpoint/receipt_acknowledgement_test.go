package endpoint

import (
	"context"
	"database/sql"
	"path/filepath"
	"testing"

	"topsailai_agent_cluster/internal/channel"
	"topsailai_agent_cluster/internal/protocol"
	endpointstorage "topsailai_agent_cluster/internal/storage/endpoint"
)

// newSettlementServiceAtPath builds a Service over a database at a known path so
// a test can read the settlement table directly. The store exposes no settlement
// reader, and adding one only for tests would put a production method on the API
// with no caller.
func newSettlementServiceAtPath(t *testing.T) (*Service, *endpointstorage.Store, string) {
	t.Helper()
	path := filepath.Join(t.TempDir(), "endpoint.sqlite")
	store, err := endpointstorage.Open(context.Background(), path)
	if err != nil {
		t.Fatalf("open endpoint store: %v", err)
	}
	t.Cleanup(func() { _ = store.Close() })
	service := &Service{storage: store, pendingReceipts: make(map[string]protocol.ExecutionReceipt)}
	return service, store, path
}

// readSettlementOrigin returns the stored origin and reason for one command.
func readSettlementOrigin(t *testing.T, path, commandID string) (string, sql.NullString, bool) {
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

// TestBothTerminalOutcomesPersistASettlement drives the two handlers that end a
// receipt's resend obligation and asserts each one writes a durable row.
//
// The table is the point. Clearing the in-memory pending map is not enough,
// because the pending set is rebuilt from the journal on every reconnect: a
// handler that only deleted the map entry would leave the receipt re-sent for the
// lifetime of the Endpoint. Driving both handlers in one table makes the
// asymmetry visible, since a fix applied to only one of them fails here.
func TestBothTerminalOutcomesPersistASettlement(t *testing.T) {
	cases := []struct {
		name       string
		handle     func(*Service, context.Context, channel.Frame)
		frame      channel.Frame
		wantOrigin protocol.SettlementOrigin
		wantReason string
	}{
		{
			name:       "acknowledgement",
			handle:     func(s *Service, ctx context.Context, frame channel.Frame) { s.settleAcknowledgedReceipt(ctx, frame) },
			frame:      channel.Frame{Type: channel.FrameReceiptAck, FrameID: "cmd-a"},
			wantOrigin: protocol.SettlementOriginAcknowledgement,
			wantReason: "",
		},
		{
			name:       "rejection",
			handle:     func(s *Service, ctx context.Context, frame channel.Frame) { s.settleRejectedReceipt(ctx, frame) },
			frame:      channel.Frame{Type: channel.FrameReceiptRejected, FrameID: "cmd-a", ReceiptRejection: protocol.ReceiptRejectedUnknownCommand},
			wantOrigin: protocol.SettlementOriginRejection,
			wantReason: string(protocol.ReceiptRejectedUnknownCommand),
		},
	}
	for _, testCase := range cases {
		t.Run(testCase.name, func(t *testing.T) {
			ctx := context.Background()
			service, store, path := newSettlementServiceAtPath(t)
			seedPendingReceipt(t, service, store, "cmd-a")

			testCase.handle(service, ctx, testCase.frame)

			origin, reason, found := readSettlementOrigin(t, path, "cmd-a")
			if !found {
				t.Fatalf("a %s left no settlement row, so the next reconnect re-sends the receipt", testCase.name)
			}
			if origin != string(testCase.wantOrigin) {
				t.Fatalf("settled_by=%q, want %q", origin, testCase.wantOrigin)
			}
			if testCase.wantReason == "" {
				if reason.Valid {
					t.Fatalf("reason=%q, want NULL because an acknowledgement carries no rejection reason", reason.String)
				}
			} else if !reason.Valid || reason.String != testCase.wantReason {
				t.Fatalf("reason=%v, want %q", reason, testCase.wantReason)
			}
			if _, pending := service.pendingReceipts["cmd-a"]; pending {
				t.Fatalf("a %s left the receipt pending in memory", testCase.name)
			}
		})
	}
}

// TestAcknowledgedReceiptLeavesTheResendSet proves the settlement actually shrinks
// the set the Endpoint reloads on reconnect, which is the behaviour the operator
// observes.
func TestAcknowledgedReceiptLeavesTheResendSet(t *testing.T) {
	ctx := context.Background()
	service, store, _ := newSettlementServiceAtPath(t)
	seedPendingReceipt(t, service, store, "cmd-a")
	seedPendingReceipt(t, service, store, "cmd-b")

	service.settleAcknowledgedReceipt(ctx, channel.Frame{Type: channel.FrameReceiptAck, FrameID: "cmd-a"})

	receipts, err := store.ListRecordedReceipts(ctx)
	if err != nil {
		t.Fatalf("list recorded receipts: %v", err)
	}
	if len(receipts) != 1 || receipts[0].CommandID != "cmd-b" {
		t.Fatalf("recorded receipts = %#v, want only cmd-b", receipts)
	}
}

// TestAcknowledgedReceiptFallsBackToRequestID proves the handler still finds the
// receipt when the frame carries only a request ID, because an acknowledgement
// that silently did nothing would leave the resend loop running.
func TestAcknowledgedReceiptFallsBackToRequestID(t *testing.T) {
	ctx := context.Background()
	service, store, path := newSettlementServiceAtPath(t)
	seedPendingReceipt(t, service, store, "cmd-a")

	service.settleAcknowledgedReceipt(ctx, channel.Frame{Type: channel.FrameReceiptAck, RequestID: "cmd-a"})

	if _, _, found := readSettlementOrigin(t, path, "cmd-a"); !found {
		t.Fatal("an acknowledgement identified only by request id left no settlement row")
	}
}

// TestAcknowledgedReceiptIgnoresAFrameWithoutAnIdentity proves a malformed
// acknowledgement is refused rather than settling an empty command id.
func TestAcknowledgedReceiptIgnoresAFrameWithoutAnIdentity(t *testing.T) {
	ctx := context.Background()
	service, store, path := newSettlementServiceAtPath(t)
	seedPendingReceipt(t, service, store, "cmd-a")

	service.settleAcknowledgedReceipt(ctx, channel.Frame{Type: channel.FrameReceiptAck})

	if _, pending := service.pendingReceipts["cmd-a"]; !pending {
		t.Fatal("an acknowledgement without an identity cleared an unrelated receipt")
	}
	if _, _, found := readSettlementOrigin(t, path, "cmd-a"); found {
		t.Fatal("an acknowledgement without an identity settled an unrelated receipt")
	}
}
