package main

import (
	"context"
	"path/filepath"
	"strings"
	"testing"

	"topsailai_agent_cluster/internal/adapter"
	endpointstorage "topsailai_agent_cluster/internal/storage/endpoint"
)

// newFactoryStore opens a throwaway Endpoint database for a factory test.
func newFactoryStore(t *testing.T) *endpointstorage.Store {
	t.Helper()
	store, err := endpointstorage.Open(context.Background(), filepath.Join(t.TempDir(), "endpoint.sqlite"))
	if err != nil {
		t.Fatalf("open endpoint store: %v", err)
	}
	t.Cleanup(func() { _ = store.Close() })
	return store
}

// TestRegisterAdapterInstallsTheOnlyImplementation proves the Endpoint registers
// exactly one adapter implementation, under the name it validates against.
//
// The registration takes no provider type, so there is no configuration value that
// can reach a different factory. This test pins that: it registers once and then
// proves the registry accepts the shipped name and refuses every other name. If a
// second implementation were ever added behind a configuration switch, the
// refusal assertion would fail, because the extra name would become acceptable.
func TestRegisterAdapterInstallsTheOnlyImplementation(t *testing.T) {
	registry := adapter.NewRegistry()
	if err := registerAdapter(registry, newFactoryStore(t)); err != nil {
		t.Fatalf("register adapter: %v", err)
	}
	if err := registry.RegisterType(adapterProviderType, func(context.Context, adapter.Config) (adapter.Adapter, error) {
		return nil, nil
	}); err == nil {
		t.Fatalf("provider type %q was registered twice, so registration is not a single fixed name", adapterProviderType)
	}
	// A removed name must be unreachable through the registry, not merely
	// rejected by the startup check. If a second factory existed, Configure would
	// find it and this would fail.
	for _, providerType := range []string{"topsailai", "fixture", "command"} {
		_, err := registry.Configure(context.Background(), adapter.Config{AdapterID: "probe-" + providerType, ProviderType: providerType})
		if err == nil {
			t.Fatalf("provider type %q reached a factory, so configuration can still select an implementation", providerType)
		}
		// The registry must refuse the name itself. A factory error would mean the
		// name reached an implementation, which is the regression this guards.
		if !strings.Contains(err.Error(), "is not registered") {
			t.Fatalf("provider type %q reached a factory instead of being refused by name: %v", providerType, err)
		}
	}
}

// TestValidateProviderTypeAcceptsOnlyTheShippedName proves a configured provider
// type is checked against the one implementation and never used to select code.
//
// The removed types are included on purpose: a configuration that still names
// "topsailai", "fixture" or "command" must be refused at startup rather than
// accepted and then fail on the first operation. The message must name what this
// node implements, because an operator reading it needs to know the replacement
// value, not only that the old one is wrong.
func TestValidateProviderTypeAcceptsOnlyTheShippedName(t *testing.T) {
	if err := validateProviderType(adapterProviderType); err != nil {
		t.Fatalf("shipped provider type %q was refused: %v", adapterProviderType, err)
	}
	for _, providerType := range []string{"", "not-a-provider", "topsailai", "fixture", "command", "GENERICCLI"} {
		t.Run(providerType, func(t *testing.T) {
			err := validateProviderType(providerType)
			if err == nil {
				t.Fatalf("provider type %q was accepted", providerType)
			}
			if !strings.Contains(err.Error(), adapterProviderType) {
				t.Fatalf("error does not name the implemented type: %v", err)
			}
		})
	}
}

// TestRegisterAdapterRequiresRegistryAndStore proves the factory refuses to
// register into a nil registry or with a nil store, because both are used by the
// factory it installs.
func TestRegisterAdapterRequiresRegistryAndStore(t *testing.T) {
	if err := registerAdapter(nil, newFactoryStore(t)); err == nil {
		t.Fatal("nil registry was accepted")
	}
	if err := registerAdapter(adapter.NewRegistry(), nil); err == nil {
		t.Fatal("nil store was accepted")
	}
}
