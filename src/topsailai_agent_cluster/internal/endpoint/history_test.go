package endpoint

import (
	"context"
	"errors"
	"fmt"
	"testing"

	"topsailai_agent_cluster/internal/adapter"
	"topsailai_agent_cluster/internal/channel"
	"topsailai_agent_cluster/internal/protocol"
)

type historyAdapter struct {
	timeoutAdapter
	fail bool
}

// History supplies read-only provider history evidence for executor routing.
func (a historyAdapter) History(context.Context, protocol.HistoryQuery) (protocol.HistoryResult, error) {
	if a.fail {
		return protocol.HistoryResult{}, errors.New("provider unavailable")
	}
	return protocol.HistoryResult{Rows: []protocol.HistoryRow{{ProviderSessionID: "wa-1", Resumable: true}}}, nil
}

// TestExecutorHistoryRouting validates live handler selection and provider failure.
func TestExecutorHistoryRouting(t *testing.T) {
	for _, fail := range []bool{false, true} {
		registry := adapter.NewRegistry()
		registry.RegisterType("test", func(context.Context, adapter.Config) (adapter.Adapter, error) { return historyAdapter{fail: fail}, nil })
		registry.Configure(context.Background(), adapter.Config{AdapterID: "a1", ProviderType: "test"})
		e := &Executor{registry: registry}
		result, err := e.History(context.Background(), protocol.HistoryQuery{})
		if (err != nil) != fail {
			t.Fatalf("%#v %v", result, err)
		}
		if fail {
			if result.ErrorCode != protocol.HistoryProviderError {
				t.Fatalf("failure code %q", result.ErrorCode)
			}
			continue
		}
		if len(result.Rows) != 1 || result.Rows[0].ProviderSessionID != "wa-1" {
			t.Fatalf("%#v", result)
		}
	}
}

// TestExecutorHistoryUnsupported verifies an adapter without the optional
// interface reports the capability as absent instead of an empty success.
func TestExecutorHistoryUnsupported(t *testing.T) {
	registry := adapter.NewRegistry()
	registry.RegisterType("test", func(context.Context, adapter.Config) (adapter.Adapter, error) { return timeoutAdapter{}, nil })
	registry.Configure(context.Background(), adapter.Config{AdapterID: "a1", ProviderType: "test"})
	e := &Executor{registry: registry}
	result, err := e.History(context.Background(), protocol.HistoryQuery{})
	if !errors.Is(err, adapter.ErrUnsupported) || result.ErrorCode != protocol.HistoryUnsupported {
		t.Fatalf("%#v %v", result, err)
	}
	if result.Rows != nil {
		t.Fatal("unsupported capability returned rows")
	}
}

// historyBusyAdapter reproduces a capacity refusal: the adapter never reached the
// provider because another invocation of the same Adapter instance held the slot.
type historyBusyAdapter struct{ timeoutAdapter }

// History reports a capacity refusal instead of provider evidence.
func (a historyBusyAdapter) History(context.Context, protocol.HistoryQuery) (protocol.HistoryResult, error) {
	return protocol.HistoryResult{}, fmt.Errorf("%w: discovery", adapter.ErrBusy)
}

// TestExecutorHistoryBusyIsNotProviderFailure proves a capacity refusal is not
// reported as a provider failure. The provider was never invoked, so telling the
// operator that the provider failed sends them to investigate the wrong thing;
// the same read may succeed unchanged once the competing invocation finishes.
func TestExecutorHistoryBusyIsNotProviderFailure(t *testing.T) {
	registry := adapter.NewRegistry()
	registry.RegisterType("test", func(context.Context, adapter.Config) (adapter.Adapter, error) { return historyBusyAdapter{}, nil })
	registry.Configure(context.Background(), adapter.Config{AdapterID: "a1", ProviderType: "test"})
	e := &Executor{registry: registry}
	result, err := e.History(context.Background(), protocol.HistoryQuery{})
	if !errors.Is(err, adapter.ErrBusy) {
		t.Fatalf("err=%v", err)
	}
	if result.ErrorCode != protocol.AdapterBusy {
		t.Fatalf("busy code %q want %q", result.ErrorCode, protocol.AdapterBusy)
	}
	if result.ErrorCode == protocol.HistoryProviderError {
		t.Fatal("capacity refusal was reported as a provider failure")
	}
}

// TestHistoryFrameResponses verifies unsupported and live response envelopes.
func TestHistoryFrameResponses(t *testing.T) {
	registry := adapter.NewRegistry()
	transport := newServiceChannel()
	service := &Service{channel: transport}
	service.historyFrame(context.Background(), channel.Frame{RequestID: "unsupported"})
	registry.RegisterType("test", func(context.Context, adapter.Config) (adapter.Adapter, error) { return historyAdapter{}, nil })
	registry.Configure(context.Background(), adapter.Config{AdapterID: "a1", ProviderType: "test"})
	service.executor = &Executor{registry: registry}
	service.historyFrame(context.Background(), channel.Frame{RequestID: "live", HistoryQuery: &protocol.HistoryQuery{}})
	if len(transport.frames) != 2 {
		t.Fatalf("%d frames", len(transport.frames))
	}
	if transport.frames[0].HistoryResult == nil || transport.frames[0].HistoryResult.ErrorCode != protocol.HistoryUnsupported {
		t.Fatalf("%#v", transport.frames[0].HistoryResult)
	}
	if transport.frames[1].RequestID != "live" || transport.frames[1].HistoryResult == nil || len(transport.frames[1].HistoryResult.Rows) != 1 {
		t.Fatalf("%#v", transport.frames[1])
	}
}
