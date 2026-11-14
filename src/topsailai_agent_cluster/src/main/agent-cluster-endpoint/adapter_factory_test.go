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

// TestRegisterAdapterTypeAcceptsEverySupportedProviderType proves each provider
// type the Endpoint can be configured with actually has a factory.
//
// The genericcli case is the one that matters: without it no deployment could
// select a standalone Provider CLI, so no Provider CLI version could ever be
// activated. A missing case is invisible at compile time because the switch has a
// default that returns an error only when a node is configured that way, which is
// exactly the configuration a Provider CLI deployment uses.
//
// The legacy "fixture" and "command" types are deliberately absent: their factory
// branch and the in-process command adapter behind it were removed, so configuring
// either type must now fail loudly instead of silently registering nothing.
func TestRegisterAdapterTypeAcceptsEverySupportedProviderType(t *testing.T) {
	for _, providerType := range []string{"topsailai", "genericcli"} {
		t.Run(providerType, func(t *testing.T) {
			registry := adapter.NewRegistry()
			if err := registerAdapterType(registry, providerType, newFactoryStore(t), nil); err != nil {
				t.Fatalf("register %q: %v", providerType, err)
			}
		})
	}
}

// TestRegisterAdapterTypeRejectsUnknownProviderType proves an unconfigured
// provider type fails loudly instead of silently registering nothing.
//
// The removed legacy types are included here on purpose: a configuration that
// still names "fixture" or "command" must be refused at startup rather than
// accepted and then fail on the first operation.
func TestRegisterAdapterTypeRejectsUnknownProviderType(t *testing.T) {
	for _, providerType := range []string{"not-a-provider", "fixture", "command"} {
		t.Run(providerType, func(t *testing.T) {
			registry := adapter.NewRegistry()
			err := registerAdapterType(registry, providerType, newFactoryStore(t), nil)
			if err == nil {
				t.Fatalf("provider type %q was accepted", providerType)
			}
			if !strings.Contains(err.Error(), "unknown adapter provider type") {
				t.Fatalf("unexpected error: %v", err)
			}
		})
	}
}

// TestRegisterAdapterTypeRequiresRegistryAndStore proves the factory refuses to
// register into a nil registry or with a nil store, because both are used by every
// factory it installs.
func TestRegisterAdapterTypeRequiresRegistryAndStore(t *testing.T) {
	if err := registerAdapterType(nil, "genericcli", newFactoryStore(t), nil); err == nil {
		t.Fatal("nil registry was accepted")
	}
	if err := registerAdapterType(adapter.NewRegistry(), "genericcli", nil, nil); err == nil {
		t.Fatal("nil store was accepted")
	}
}
