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

// TestExecutorLaunchHandler validates the handler catalog and an unknown handler.
func TestExecutorLaunchHandler(t *testing.T) {
	registry := adapter.NewRegistry()
	registry.RegisterType("test", func(context.Context, adapter.Config) (adapter.Adapter, error) { return timeoutAdapter{}, nil })
	registry.Configure(context.Background(), adapter.Config{AdapterID: "a1", ProviderType: "test"})
	e := &Executor{registry: registry}
	catalog, err := e.LaunchOptions(context.Background(), protocol.LaunchQuery{})
	if err != nil || len(catalog.Handlers) != 1 {
		t.Fatalf("%#v %v", catalog, err)
	}
	result, err := e.LaunchOptions(context.Background(), protocol.LaunchQuery{AdapterID: "missing"})
	if err != nil || result.ErrorCode != "unknown_launch_handler" {
		t.Fatalf("%#v %v", result, err)
	}
}

// describeBusyAdapter reproduces a capacity refusal on the descriptor read.
type describeBusyAdapter struct{ timeoutAdapter }

// Describe reports a capacity refusal instead of a descriptor.
func (a describeBusyAdapter) Describe(context.Context) (adapter.Descriptor, error) {
	return adapter.Descriptor{}, fmt.Errorf("%w: discovery", adapter.ErrBusy)
}

// TestExecutorLaunchDescribeBusyIsNotProviderFailure proves a capacity refusal on
// the descriptor read is not reported as a provider failure. This path previously
// set no code at all, so it fell through to the frame handler's provider default.
func TestExecutorLaunchDescribeBusyIsNotProviderFailure(t *testing.T) {
	registry := adapter.NewRegistry()
	registry.RegisterType("test", func(context.Context, adapter.Config) (adapter.Adapter, error) {
		return describeBusyAdapter{}, nil
	})
	registry.Configure(context.Background(), adapter.Config{AdapterID: "a1", ProviderType: "test"})
	e := &Executor{registry: registry}
	result, err := e.LaunchOptions(context.Background(), protocol.LaunchQuery{})
	if !errors.Is(err, adapter.ErrBusy) {
		t.Fatalf("err=%v", err)
	}
	if result.ErrorCode != protocol.AdapterBusy {
		t.Fatalf("busy code %q want %q", result.ErrorCode, protocol.AdapterBusy)
	}
}

// TestLaunchFrameResponses verifies unsupported and live handler response envelopes.
func TestLaunchFrameResponses(t *testing.T) {
	registry := adapter.NewRegistry()
	transport := newServiceChannel()
	service := &Service{channel: transport}
	service.launchFrame(context.Background(), channel.Frame{RequestID: "unsupported"})
	service.executor = &Executor{registry: registry}
	service.launchFrame(context.Background(), channel.Frame{RequestID: "catalog", LaunchQuery: &protocol.LaunchQuery{}})
	if len(transport.frames) != 2 || transport.frames[0].LaunchOptions.ErrorCode != "unsupported" || transport.frames[1].RequestID != "catalog" || transport.frames[1].LaunchOptions.ErrorCode != "" {
		t.Fatal(transport.frames)
	}
}
