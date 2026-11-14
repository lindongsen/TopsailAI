package main

import (
	"context"
	"path/filepath"
	"strings"
	"testing"

	"topsailai_agent_cluster/internal/adapter"
	"topsailai_agent_cluster/internal/controlaction"
	"topsailai_agent_cluster/internal/protocol"
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
// genericcli is the only accepted type. The in-process "topsailai" adapter and the
// legacy "fixture" and "command" adapters were removed, so configuring any of them
// must now fail loudly instead of silently registering nothing.
func TestRegisterAdapterTypeAcceptsEverySupportedProviderType(t *testing.T) {
	for _, providerType := range []string{"genericcli"} {
		t.Run(providerType, func(t *testing.T) {
			registry := adapter.NewRegistry()
			if err := registerAdapterType(registry, providerType, newFactoryStore(t)); err != nil {
				t.Fatalf("register %q: %v", providerType, err)
			}
		})
	}
}

// TestRegisterAdapterTypeRejectsUnknownProviderType proves an unconfigured
// provider type fails loudly instead of silently registering nothing.
//
// The removed types are included here on purpose: a configuration that still names
// "topsailai", "fixture" or "command" must be refused at startup rather than
// accepted and then fail on the first operation.
func TestRegisterAdapterTypeRejectsUnknownProviderType(t *testing.T) {
	for _, providerType := range []string{"not-a-provider", "topsailai", "fixture", "command"} {
		t.Run(providerType, func(t *testing.T) {
			registry := adapter.NewRegistry()
			err := registerAdapterType(registry, providerType, newFactoryStore(t))
			if err == nil {
				t.Fatalf("provider type %q was accepted", providerType)
			}
			if !strings.Contains(err.Error(), "unknown adapter provider type") {
				t.Fatalf("unexpected error: %v", err)
			}
		})
	}
}

// TestWithControlActionsMergesTheCatalogIntoTheDescriptor proves a configured
// control action reaches the effective capability descriptor.
//
// The catalog is Endpoint-local configuration and is not part of the
// operator-facing adapter document, so without this merge the adapter intersected
// the configured list with what the provider advertised, the catalog was not in
// that list, and no ctl. capability was published. Every control command was then
// refused as unsupported before the policy hook could authorize it, so a
// configured catalog had no effect at all.
func TestWithControlActionsMergesTheCatalogIntoTheDescriptor(t *testing.T) {
	set, err := controlaction.ParseControlActionSet([]byte(`{"actions":[{"name":"fixture_probe","permission":"control","command":["runtime","control","fixture_probe"]}]}`))
	if err != nil {
		t.Fatalf("parse control action set: %v", err)
	}
	configured := &protocol.CapabilityDescriptor{
		Revision:     "rev-1",
		Capabilities: []protocol.Capability{{Name: "message.send", Version: "v1", TargetKinds: []string{"session"}}},
	}
	merged := withControlActions(configured, set)
	if merged == nil {
		t.Fatal("merged descriptor is nil, want the catalog merged in")
	}
	if merged.Revision != "rev-1" {
		t.Fatalf("merged revision = %q, want the configured revision", merged.Revision)
	}
	names := make([]string, 0, len(merged.Capabilities))
	for _, capability := range merged.Capabilities {
		names = append(names, capability.Name)
	}
	if len(names) != 2 {
		t.Fatalf("merged capabilities = %v, want the operation and the control action", names)
	}
	if names[1] != "ctl.fixture_probe" {
		t.Fatalf("merged capabilities = %v, want the catalog action appended", names)
	}
	if merged.Capabilities[1].RequiredPermission != "control" {
		t.Fatalf("control action permission = %q, want the catalog permission", merged.Capabilities[1].RequiredPermission)
	}
	if merged.Capabilities[1].SafetyClass != protocol.SafetyClassMutating {
		t.Fatalf("control action safety class = %q, want mutating", merged.Capabilities[1].SafetyClass)
	}
}

// TestWithControlActionsLeavesTheDescriptorUntouchedWithoutACatalog is the
// fail-closed default.
//
// An Endpoint with no catalog must advertise no ctl. capability, because it cannot
// serve an action it was never told about. Without this case, merging an empty
// catalog could silently publish a control surface that has no backing action.
func TestWithControlActionsLeavesTheDescriptorUntouchedWithoutACatalog(t *testing.T) {
	configured := &protocol.CapabilityDescriptor{
		Revision:     "rev-1",
		Capabilities: []protocol.Capability{{Name: "message.send", Version: "v1", TargetKinds: []string{"session"}}},
	}
	merged := withControlActions(configured, nil)
	if merged != configured {
		t.Fatal("descriptor was replaced, want it untouched when no catalog is configured")
	}
	if len(merged.Capabilities) != 1 {
		t.Fatalf("capabilities = %v, want only the configured operation", merged.Capabilities)
	}
}

// TestRegisterAdapterTypeRequiresRegistryAndStore proves the factory refuses to
// register into a nil registry or with a nil store, because both are used by every
// factory it installs.
func TestRegisterAdapterTypeRequiresRegistryAndStore(t *testing.T) {
	if err := registerAdapterType(nil, "genericcli", newFactoryStore(t)); err == nil {
		t.Fatal("nil registry was accepted")
	}
	if err := registerAdapterType(adapter.NewRegistry(), "genericcli", nil); err == nil {
		t.Fatal("nil store was accepted")
	}
}
