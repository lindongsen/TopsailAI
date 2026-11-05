package endpoint

import (
	"context"
	"errors"
	"testing"
	"topsailai_agent_cluster/internal/adapter"
	"topsailai_agent_cluster/internal/channel"
	"topsailai_agent_cluster/internal/protocol"
)

type projectAdapter struct {
	timeoutAdapter
	fail bool
}

// Projects supplies read-only project evidence for executor routing.
func (a projectAdapter) Projects(context.Context) ([]protocol.Project, error) {
	if a.fail {
		return nil, errors.New("provider unavailable")
	}
	return []protocol.Project{{Name: "one", Path: "/work/one"}}, nil
}

// TestExecutorLaunchHandler validates live catalog, unknown handler and provider failure.
func TestExecutorLaunchHandler(t *testing.T) {
	for _, fail := range []bool{false, true} {
		registry := adapter.NewRegistry()
		registry.RegisterType("test", func(context.Context, adapter.Config) (adapter.Adapter, error) { return projectAdapter{fail: fail}, nil })
		registry.Configure(context.Background(), adapter.Config{AdapterID: "a1", ProviderType: "test"})
		e := &Executor{registry: registry}
		catalog, err := e.LaunchOptions(context.Background(), protocol.LaunchQuery{})
		if err != nil || len(catalog.Handlers) != 1 || len(catalog.Projects) != 0 {
			t.Fatalf("%#v %v", catalog, err)
		}
		result, err := e.LaunchOptions(context.Background(), protocol.LaunchQuery{AdapterID: "a1"})
		if (err != nil) != fail || (!fail && len(result.Projects) != 1) {
			t.Fatalf("%#v %v", result, err)
		}
		result, err = e.LaunchOptions(context.Background(), protocol.LaunchQuery{AdapterID: "missing"})
		if err != nil || result.ErrorCode != "unknown_launch_handler" {
			t.Fatalf("%#v %v", result, err)
		}
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
