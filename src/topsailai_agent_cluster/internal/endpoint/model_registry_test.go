package endpoint

import (
	"context"
	"errors"
	"fmt"
	"testing"

	"topsailai_agent_cluster/internal/adapter"
	"topsailai_agent_cluster/internal/protocol"
)

// registryAdapter supplies one model registry for executor routing.
type registryAdapter struct {
	timeoutAdapter
	registry protocol.ModelRegistry
	fail     error
}

// ModelRegistry returns the configured registry or the configured failure.
func (a registryAdapter) ModelRegistry(context.Context, protocol.ModelRegistryQuery) (protocol.ModelRegistry, error) {
	if a.fail != nil {
		return protocol.ModelRegistry{}, a.fail
	}
	return a.registry, nil
}

// registryExecutor builds an Executor holding one configured adapter of the given
// provider type.
func registryExecutor(t *testing.T, providerType string, factory func() adapter.Adapter) *Executor {
	t.Helper()
	registry := adapter.NewRegistry()
	registry.RegisterType(providerType, func(context.Context, adapter.Config) (adapter.Adapter, error) {
		return factory(), nil
	})
	if _, err := registry.Configure(context.Background(), adapter.Config{AdapterID: "a1", ProviderType: providerType}); err != nil {
		t.Fatalf("configure adapter: %v", err)
	}
	return &Executor{registry: registry}
}

// TestExecutorModelRegistry validates a live registry read and a provider failure.
func TestExecutorModelRegistry(t *testing.T) {
	for _, failure := range []error{nil, errors.New("provider unavailable")} {
		executor := registryExecutor(t, "test", func() adapter.Adapter {
			return registryAdapter{
				registry: protocol.ModelRegistry{
					Entries:          []protocol.ModelRegistryEntry{{ModelProfileID: "mp-1", Available: true}},
					CurrentProfileID: "mp-1",
					CurrentSource:    protocol.ModelSourceWorkspace,
					ObservedAtMS:     1,
				},
				fail: failure,
			}
		})
		result, err := executor.ModelRegistry(context.Background(), protocol.ModelRegistryQuery{})
		if (err != nil) != (failure != nil) {
			t.Fatalf("failure=%v result=%#v err=%v", failure, result, err)
		}
		if failure == nil && (len(result.Entries) != 1 || result.CurrentProfileID != "mp-1" || result.CurrentSource != protocol.ModelSourceWorkspace) {
			t.Fatalf("result=%#v", result)
		}
	}
}

// TestExecutorModelRegistryBusyIsNotProviderFailure proves capacity is classified
// separately, so an operator is told to retry rather than to investigate a provider.
func TestExecutorModelRegistryBusyIsNotProviderFailure(t *testing.T) {
	executor := registryExecutor(t, "test", func() adapter.Adapter {
		return registryAdapter{fail: fmt.Errorf("%w: discovery", adapter.ErrBusy)}
	})
	result, err := executor.ModelRegistry(context.Background(), protocol.ModelRegistryQuery{})
	if !errors.Is(err, adapter.ErrBusy) || result.ErrorCode != protocol.AdapterBusy {
		t.Fatalf("result=%#v err=%v", result, err)
	}
}

// TestExecutorModelRegistryUnsupportedIsNotAnEmptyRegistry proves an Endpoint with
// no capable adapter reports a capability gap rather than "this machine has no
// model". The two claims are different, and collapsing them would tell an operator
// to configure a model when the real problem is a missing adapter.
func TestExecutorModelRegistryUnsupportedIsNotAnEmptyRegistry(t *testing.T) {
	executor := registryExecutor(t, "test", func() adapter.Adapter {
		return registryAdapter{fail: adapter.ErrUnsupported}
	})
	result, err := executor.ModelRegistry(context.Background(), protocol.ModelRegistryQuery{})
	if !errors.Is(err, adapter.ErrUnsupported) || result.ErrorCode != protocol.ModelRegistryUnsupported {
		t.Fatalf("result=%#v err=%v", result, err)
	}
}

// TestExecutorModelRegistryCombinesEveryCapableAdapter proves a machine with two
// Adapter instances reports both sets of models. Reporting only the first would make
// the answer describe one adapter instead of the machine.
func TestExecutorModelRegistryCombinesEveryCapableAdapter(t *testing.T) {
	registry := adapter.NewRegistry()
	registry.RegisterType("first", func(context.Context, adapter.Config) (adapter.Adapter, error) {
		return registryAdapter{registry: protocol.ModelRegistry{
			Entries:          []protocol.ModelRegistryEntry{{ModelProfileID: "mp-a", Available: true}},
			CurrentProfileID: "mp-a",
			CurrentSource:    protocol.ModelSourceWorkspace,
			ObservedAtMS:     1,
		}}, nil
	})
	registry.RegisterType("second", func(context.Context, adapter.Config) (adapter.Adapter, error) {
		return registryAdapter{registry: protocol.ModelRegistry{
			Entries:          []protocol.ModelRegistryEntry{{ModelProfileID: "mp-b", Available: true}},
			CurrentProfileID: "mp-b",
			CurrentSource:    protocol.ModelSourceProject,
			ObservedAtMS:     2,
		}}, nil
	})
	if _, err := registry.Configure(context.Background(), adapter.Config{AdapterID: "first", ProviderType: "first"}); err != nil {
		t.Fatal(err)
	}
	if _, err := registry.Configure(context.Background(), adapter.Config{AdapterID: "second", ProviderType: "second"}); err != nil {
		t.Fatal(err)
	}
	result, err := (&Executor{registry: registry}).ModelRegistry(context.Background(), protocol.ModelRegistryQuery{})
	if err != nil || len(result.Entries) != 2 {
		t.Fatalf("result=%#v err=%v", result, err)
	}
	// The first adapter that reports a selection wins, so the answer never depends
	// on configuration order.
	if result.CurrentProfileID != "mp-a" || result.CurrentSource != protocol.ModelSourceWorkspace {
		t.Fatalf("selection=%q source=%q", result.CurrentProfileID, result.CurrentSource)
	}
	// Freshness is the newest observation, because the combined answer is as fresh
	// as its freshest part.
	if result.ObservedAtMS != 2 {
		t.Fatalf("observed_at_ms=%d want 2", result.ObservedAtMS)
	}
}

// TestExecutorModelRegistryRejectsCombinedAdapterOverflow proves the public entry
// bound applies after Adapter aggregation, not only to each Provider.
func TestExecutorModelRegistryRejectsCombinedAdapterOverflow(t *testing.T) {
	registry := adapter.NewRegistry()
	registry.RegisterType("bounded", func(context.Context, adapter.Config) (adapter.Adapter, error) {
		entries := make([]protocol.ModelRegistryEntry, protocol.MaxModelRegistryEntries/2+1)
		for index := range entries {
			entries[index] = protocol.ModelRegistryEntry{ModelProfileID: fmt.Sprintf("mp-%d", index), Available: true}
		}
		return registryAdapter{registry: protocol.ModelRegistry{Entries: entries, CurrentSource: protocol.ModelSourceWorkspace, ObservedAtMS: 1}}, nil
	})
	if _, err := registry.Configure(context.Background(), adapter.Config{AdapterID: "first", ProviderType: "bounded"}); err != nil {
		t.Fatal(err)
	}
	if _, err := registry.Configure(context.Background(), adapter.Config{AdapterID: "second", ProviderType: "bounded"}); err != nil {
		t.Fatal(err)
	}
	result, err := (&Executor{registry: registry}).ModelRegistry(context.Background(), protocol.ModelRegistryQuery{})
	if err == nil || result.ErrorCode != protocol.ModelRegistryTooLarge || len(result.Entries) != 0 {
		t.Fatalf("result=%#v err=%v", result, err)
	}
}
