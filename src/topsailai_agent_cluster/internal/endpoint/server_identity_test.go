package endpoint

import (
	"context"
	"path/filepath"
	"testing"

	"topsailai_agent_cluster/internal/channel"
	"topsailai_agent_cluster/internal/protocol"
	endpointstorage "topsailai_agent_cluster/internal/storage/endpoint"
)

// identityChannel is the minimum channel that can report a Server database
// identity. It exists so the reconciliation decision can be tested without a
// transport, because the decision is about identity rather than delivery.
type identityChannel struct {
	identity string
}

func (c *identityChannel) ServerDatabaseIdentity() string { return c.identity }

// The remaining methods satisfy ChannelClient. They are unreachable here
// because these tests exercise the identity decision, not delivery.
func (c *identityChannel) Read(context.Context) (channel.Frame, error)    { return channel.Frame{}, nil }
func (c *identityChannel) SendFrame(context.Context, channel.Frame) error { return nil }
func (c *identityChannel) Close() error                                   { return nil }

// newIdentityService builds a Service whose channel reports the given identity.
func newIdentityService(t *testing.T, identity string) (*Service, *endpointstorage.Store) {
	t.Helper()
	store, err := endpointstorage.Open(context.Background(), filepath.Join(t.TempDir(), "endpoint.sqlite"))
	if err != nil {
		t.Fatalf("open endpoint store: %v", err)
	}
	t.Cleanup(func() { _ = store.Close() })
	service := &Service{storage: store, channel: &identityChannel{identity: identity}, pendingReceipts: make(map[string]protocol.ExecutionReceipt)}
	return service, store
}

// TestReconcileSettlesReceiptsWhenTheServerChanges proves the re-home case: a
// different Server database settles every recorded receipt, because a Server
// that never admitted a command can never apply its receipt.
func TestReconcileSettlesReceiptsWhenTheServerChanges(t *testing.T) {
	ctx := context.Background()
	service, store := newIdentityService(t, "server-a")
	seedPendingReceipt(t, service, store, "cmd-a")
	seedPendingReceipt(t, service, store, "cmd-b")

	// The first observation establishes the baseline and must settle nothing.
	service.reconcileServerIdentity(ctx)
	if receipts, err := store.ListRecordedReceipts(ctx); err != nil || len(receipts) != 2 {
		t.Fatalf("recorded receipts after first observation = %d (err %v), want 2", len(receipts), err)
	}

	// A different Server is the only case that makes receipts inapplicable.
	service.channel = &identityChannel{identity: "server-b"}
	service.reconcileServerIdentity(ctx)

	receipts, err := store.ListRecordedReceipts(ctx)
	if err != nil {
		t.Fatalf("list recorded receipts: %v", err)
	}
	if len(receipts) != 0 {
		t.Fatalf("recorded receipts after server change = %d, want 0", len(receipts))
	}
}

// TestReconcileKeepsReceiptsWhenTheSameServerRestarts proves the restart case: a
// restarted Server keeps its database identity, so its receipts must still be
// re-sent because it can still apply them.
func TestReconcileKeepsReceiptsWhenTheSameServerRestarts(t *testing.T) {
	ctx := context.Background()
	service, store := newIdentityService(t, "server-a")
	seedPendingReceipt(t, service, store, "cmd-a")

	service.reconcileServerIdentity(ctx)
	// A restart is a new connection to the same database, so the identity is
	// unchanged and nothing may be discarded.
	service.reconcileServerIdentity(ctx)

	receipts, err := store.ListRecordedReceipts(ctx)
	if err != nil {
		t.Fatalf("list recorded receipts: %v", err)
	}
	if len(receipts) != 1 {
		t.Fatalf("recorded receipts after same-server restart = %d, want 1", len(receipts))
	}
}

// TestReconcileIgnoresAnAbsentIdentity proves that an older Server which does not
// report an identity cannot be mistaken for a new Server, because that would
// discard receipts the same Server still holds.
func TestReconcileIgnoresAnAbsentIdentity(t *testing.T) {
	ctx := context.Background()
	service, store := newIdentityService(t, "server-a")
	seedPendingReceipt(t, service, store, "cmd-a")
	service.reconcileServerIdentity(ctx)

	service.channel = &identityChannel{identity: ""}
	service.reconcileServerIdentity(ctx)

	receipts, err := store.ListRecordedReceipts(ctx)
	if err != nil {
		t.Fatalf("list recorded receipts: %v", err)
	}
	if len(receipts) != 1 {
		t.Fatalf("recorded receipts after an absent identity = %d, want 1", len(receipts))
	}
}

// TestReconcileSurvivesAnEndpointRestart proves the observation is durable: a
// restarted Endpoint must still recognise the Server it was talking to, or it
// would treat its first connection as a first observation and never detect a
// re-home.
func TestReconcileSurvivesAnEndpointRestart(t *testing.T) {
	ctx := context.Background()
	path := filepath.Join(t.TempDir(), "endpoint.sqlite")
	store, err := endpointstorage.Open(ctx, path)
	if err != nil {
		t.Fatalf("open endpoint store: %v", err)
	}
	service := &Service{storage: store, channel: &identityChannel{identity: "server-a"}, pendingReceipts: make(map[string]protocol.ExecutionReceipt)}
	seedPendingReceipt(t, service, store, "cmd-a")
	service.reconcileServerIdentity(ctx)
	if err := store.Close(); err != nil {
		t.Fatalf("close endpoint store: %v", err)
	}

	reopened, err := endpointstorage.Open(ctx, path)
	if err != nil {
		t.Fatalf("reopen endpoint store: %v", err)
	}
	t.Cleanup(func() { _ = reopened.Close() })
	restarted := &Service{storage: reopened, channel: &identityChannel{identity: "server-b"}, pendingReceipts: make(map[string]protocol.ExecutionReceipt)}
	restarted.reconcileServerIdentity(ctx)

	receipts, err := reopened.ListRecordedReceipts(ctx)
	if err != nil {
		t.Fatalf("list recorded receipts: %v", err)
	}
	if len(receipts) != 0 {
		t.Fatalf("recorded receipts after a re-home across restart = %d, want 0", len(receipts))
	}
}
