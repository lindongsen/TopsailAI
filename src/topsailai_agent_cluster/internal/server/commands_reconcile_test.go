package server

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"

	"topsailai_agent_cluster/internal/protocol"
)

// executingCommand drives one command to the executing state through a real receipt, matching the
// ERR-12 condition: the signal was sent but the exit was never confirmed.
func executingCommand(t *testing.T, store interface {
	AdmitCommand(context.Context, protocol.ImmutableIntent, string, int64) error
	ApplyReceipt(context.Context, protocol.ExecutionReceipt, int64) error
}, commandID string, deadlineAtMS int64) {
	t.Helper()
	ctx := context.Background()
	intent := protocol.ImmutableIntent{
		HashVersion:       "v1",
		CommandID:         commandID,
		EndpointID:        "endpoint-1",
		Operation:         protocol.OperationAgentStop,
		OperationVersion:  "v1",
		ExecuteBeforeAtMS: deadlineAtMS,
	}
	if err := store.AdmitCommand(ctx, intent, "hash-"+commandID, 1000); err != nil {
		t.Fatalf("admit: %v", err)
	}
	receipt := protocol.ExecutionReceipt{
		CommandID:          commandID,
		RequestHash:        "hash-" + commandID,
		CommandRevision:    1,
		EndpointInstanceID: "instance-1",
		Phase:              protocol.PhaseInvocationStarted,
		DeliveryBoundary:   protocol.DeliverySignalSent,
		EffectCertainty:    protocol.EffectUnknown,
		Outcome:            "signal_sent",
		ExitConfirmed:      false,
	}
	if err := store.ApplyReceipt(ctx, receipt, 1100); err != nil {
		t.Fatalf("receipt: %v", err)
	}
}

// commandStatusBody performs an authenticated GET and returns the decoded data object.
func commandStatusBody(t *testing.T, h http.Handler, path string) map[string]any {
	t.Helper()
	req := httptest.NewRequest(http.MethodGet, path, nil)
	req.Header.Set("Authorization", "Bearer secret")
	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, req)
	if rec.Code != http.StatusOK {
		t.Fatalf("GET %s status %d: %s", path, rec.Code, rec.Body.String())
	}
	var envelope struct {
		Data map[string]any `json:"data"`
	}
	if err := json.Unmarshal(rec.Body.Bytes(), &envelope); err != nil {
		t.Fatalf("decode %s: %v", path, err)
	}
	return envelope.Data
}

// TestSingleCommandReadConvergesOverdueExecutingCommand proves the ERR-12 operator path: polling one
// command ID must return the terminal unconfirmed state once the immutable deadline has passed.
func TestSingleCommandReadConvergesOverdueExecutingCommand(t *testing.T) {
	store := commandTestStore(t)
	defer store.Close()
	executingCommand(t, store, "cmd-overdue", 5000)
	svc := &CommandService{Store: store, Now: func() time.Time { return time.UnixMilli(6000) }}
	h := NewHandlerWithCommands(store, "secret", svc)

	data := commandStatusBody(t, h, "/api/v1/commands/cmd-overdue")
	if data["command_id"] != "cmd-overdue" {
		t.Fatalf("command_id=%v, want cmd-overdue: convergence must not mint a new identity", data["command_id"])
	}
	if data["status"] != string(protocol.StatusUnconfirmed) {
		t.Fatalf("status=%v, want unconfirmed", data["status"])
	}
	if data["effect_certainty"] != string(protocol.EffectUnknown) {
		t.Fatalf("effect_certainty=%v, want unknown", data["effect_certainty"])
	}
}

// TestCommandListConvergesOverdueExecutingCommand proves the list path converges the same row.
func TestCommandListConvergesOverdueExecutingCommand(t *testing.T) {
	store := commandTestStore(t)
	defer store.Close()
	executingCommand(t, store, "cmd-overdue", 5000)
	svc := &CommandService{Store: store, Now: func() time.Time { return time.UnixMilli(6000) }}
	h := NewHandlerWithCommands(store, "secret", svc)

	req := httptest.NewRequest(http.MethodGet, "/api/v1/commands", nil)
	req.Header.Set("Authorization", "Bearer secret")
	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, req)
	if rec.Code != http.StatusOK {
		t.Fatalf("list status %d: %s", rec.Code, rec.Body.String())
	}
	var envelope struct {
		Data []map[string]any `json:"data"`
	}
	if err := json.Unmarshal(rec.Body.Bytes(), &envelope); err != nil {
		t.Fatalf("decode list: %v", err)
	}
	if len(envelope.Data) != 1 {
		t.Fatalf("list length=%d, want 1", len(envelope.Data))
	}
	if envelope.Data[0]["status"] != string(protocol.StatusUnconfirmed) {
		t.Fatalf("status=%v, want unconfirmed", envelope.Data[0]["status"])
	}
}

// TestCommandReadKeepsLiveExecutingCommand proves reconciliation is bounded by the deadline: a
// command that still has time must keep reporting executing.
func TestCommandReadKeepsLiveExecutingCommand(t *testing.T) {
	store := commandTestStore(t)
	defer store.Close()
	executingCommand(t, store, "cmd-live", 9000)
	svc := &CommandService{Store: store, Now: func() time.Time { return time.UnixMilli(6000) }}
	h := NewHandlerWithCommands(store, "secret", svc)

	data := commandStatusBody(t, h, "/api/v1/commands/cmd-live")
	if data["status"] != string(protocol.StatusExecuting) {
		t.Fatalf("status=%v, want executing", data["status"])
	}
}

// TestReconcileExpiredNeverFailsTheRead proves the convergence helper cannot fail the operator
// read: it returns no error, tolerates a nil store, and tolerates a nil logger while still
// converging the durable row.
func TestReconcileExpiredNeverFailsTheRead(t *testing.T) {
	// A nil store must be a no-op rather than a panic.
	(&CommandService{}).ReconcileExpired(context.Background())

	store := commandTestStore(t)
	defer store.Close()
	executingCommand(t, store, "cmd-overdue", 5000)
	// Logger is intentionally nil: convergence must not depend on a logger being wired.
	svc := &CommandService{Store: store, Now: func() time.Time { return time.UnixMilli(6000) }}
	svc.ReconcileExpired(context.Background())

	record, err := store.GetCommand(context.Background(), "cmd-overdue")
	if err != nil {
		t.Fatal(err)
	}
	if record.Status != protocol.StatusUnconfirmed {
		t.Fatalf("status=%q, want unconfirmed", record.Status)
	}
}
