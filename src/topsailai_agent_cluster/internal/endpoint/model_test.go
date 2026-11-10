package endpoint

import (
	"context"
	"errors"
	"testing"

	"topsailai_agent_cluster/internal/adapter"
	"topsailai_agent_cluster/internal/channel"
	"topsailai_agent_cluster/internal/protocol"
)

type modelCatalogAdapter struct {
	timeoutAdapter
	fail bool
}

// ModelCatalog supplies read-only model profile evidence for executor routing.
func (a modelCatalogAdapter) ModelCatalog(context.Context, protocol.ModelCatalogQuery) (protocol.ModelCatalog, error) {
	if a.fail {
		return protocol.ModelCatalog{}, errors.New("provider unavailable")
	}
	return protocol.ModelCatalog{
		Profiles:         []protocol.ModelProfile{{ModelProfileID: "mp-1", DisplayName: "fast", Available: true}},
		CurrentProfileID: "mp-1",
		ObservedAtMS:     1000,
	}, nil
}

// TestExecutorModelCatalogRouting validates live handler selection and provider
// failure.
func TestExecutorModelCatalogRouting(t *testing.T) {
	for _, fail := range []bool{false, true} {
		registry := adapter.NewRegistry()
		registry.RegisterType("test", func(context.Context, adapter.Config) (adapter.Adapter, error) {
			return modelCatalogAdapter{fail: fail}, nil
		})
		registry.Configure(context.Background(), adapter.Config{AdapterID: "a1", ProviderType: "test"})
		e := &Executor{registry: registry}
		result, err := e.ModelCatalog(context.Background(), protocol.ModelCatalogQuery{})
		if (err != nil) != fail {
			t.Fatalf("%#v %v", result, err)
		}
		if fail {
			if result.ErrorCode != protocol.ModelCatalogProviderError {
				t.Fatalf("failure code %q", result.ErrorCode)
			}
			continue
		}
		if len(result.Profiles) != 1 || result.Profiles[0].ModelProfileID != "mp-1" {
			t.Fatalf("%#v", result)
		}
		if result.CurrentProfileID != "mp-1" {
			t.Fatalf("current profile %q", result.CurrentProfileID)
		}
	}
}

// TestExecutorModelCatalogUnsupported verifies an adapter without the optional
// interface reports the capability as absent instead of an empty success.
func TestExecutorModelCatalogUnsupported(t *testing.T) {
	registry := adapter.NewRegistry()
	registry.RegisterType("test", func(context.Context, adapter.Config) (adapter.Adapter, error) {
		return timeoutAdapter{}, nil
	})
	registry.Configure(context.Background(), adapter.Config{AdapterID: "a1", ProviderType: "test"})
	e := &Executor{registry: registry}
	result, err := e.ModelCatalog(context.Background(), protocol.ModelCatalogQuery{})
	if !errors.Is(err, adapter.ErrUnsupported) || result.ErrorCode != protocol.ModelCatalogUnsupported {
		t.Fatalf("%#v %v", result, err)
	}
	if result.Profiles != nil {
		t.Fatal("unsupported capability returned profiles")
	}
}

// TestModelCatalogFrameResponses verifies unsupported and live response envelopes.
func TestModelCatalogFrameResponses(t *testing.T) {
	registry := adapter.NewRegistry()
	transport := newServiceChannel()
	service := &Service{channel: transport}
	service.modelCatalogFrame(context.Background(), channel.Frame{RequestID: "unsupported"})
	registry.RegisterType("test", func(context.Context, adapter.Config) (adapter.Adapter, error) {
		return modelCatalogAdapter{}, nil
	})
	registry.Configure(context.Background(), adapter.Config{AdapterID: "a1", ProviderType: "test"})
	service.executor = &Executor{registry: registry}
	service.modelCatalogFrame(context.Background(), channel.Frame{RequestID: "live", ModelCatalogQuery: &protocol.ModelCatalogQuery{}})
	if len(transport.frames) != 2 {
		t.Fatalf("%d frames", len(transport.frames))
	}
	if transport.frames[0].ModelCatalog == nil || transport.frames[0].ModelCatalog.ErrorCode != protocol.ModelCatalogUnsupported {
		t.Fatalf("%#v", transport.frames[0].ModelCatalog)
	}
	if transport.frames[1].RequestID != "live" || transport.frames[1].ModelCatalog == nil || len(transport.frames[1].ModelCatalog.Profiles) != 1 {
		t.Fatalf("%#v", transport.frames[1])
	}
}

// TestModelCatalogFrameWithoutQueryReportsUnsupported proves a frame that carries
// no query is answered as an absent capability rather than as an empty catalog.
func TestModelCatalogFrameWithoutQueryReportsUnsupported(t *testing.T) {
	registry := adapter.NewRegistry()
	registry.RegisterType("test", func(context.Context, adapter.Config) (adapter.Adapter, error) {
		return modelCatalogAdapter{}, nil
	})
	registry.Configure(context.Background(), adapter.Config{AdapterID: "a1", ProviderType: "test"})
	transport := newServiceChannel()
	service := &Service{channel: transport, executor: &Executor{registry: registry}}
	service.modelCatalogFrame(context.Background(), channel.Frame{RequestID: "no-query"})
	if len(transport.frames) != 1 {
		t.Fatalf("%d frames", len(transport.frames))
	}
	result := transport.frames[0].ModelCatalog
	if result == nil || result.ErrorCode != protocol.ModelCatalogUnsupported {
		t.Fatalf("%#v", result)
	}
	if len(result.Profiles) != 0 {
		t.Fatal("a missing query must not produce profiles")
	}
}
