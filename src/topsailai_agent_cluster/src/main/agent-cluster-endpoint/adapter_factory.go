package main

import (
	"context"
	"fmt"
	"time"

	"topsailai_agent_cluster/internal/adapter"
	"topsailai_agent_cluster/internal/adapter/genericcli"
	topsailaiadapter "topsailai_agent_cluster/internal/adapter/topsailai"
	"topsailai_agent_cluster/internal/controlaction"
	"topsailai_agent_cluster/internal/protocol"
	"topsailai_agent_cluster/internal/providercli"
	endpointstorage "topsailai_agent_cluster/internal/storage/endpoint"
)

// Generic CLI Adapter bounds are Endpoint-local limits on one Provider CLI
// invocation. They are declared here instead of being read from the adapter
// configuration because the operator-facing adapter document carries no limit
// fields, and genericcli.New rejects a zero limit rather than inventing one.
//
// The values match what the shipped Provider CLI advertises, so the effective
// concurrency is the provider's own bound and not an arbitrary local one. A
// provider that advertises a smaller bound still wins, because the adapter takes
// the minimum of the Endpoint, adapter and provider limits.
const (
	genericCLIMaxStdinBytes  = 1 << 20
	genericCLIMaxStdoutBytes = 1 << 20
	genericCLIMaxStderrBytes = 64 << 10
	genericCLIMaxRecords     = 128
)

// genericCLIConcurrency is the Endpoint-side concurrency ceiling for one Generic
// CLI Adapter. It is a value rather than a constant because the type is a struct.
var genericCLIConcurrency = providercli.ConcurrencyLimits{Total: 4, Discovery: 2, Mutation: 1, Follow: 2}

// registerAdapterType installs the factory for one provider type.
//
// The genericcli case exists so the Provider CLI adapter is reachable from
// Endpoint configuration at all. Without it the only adapters an Endpoint could
// build were the in-process TopsailAI adapter and the legacy command adapter,
// so no deployment could select a standalone Provider CLI and no activation
// could ever be exercised against one. The legacy command adapter has since been
// removed, so every configured adapter is now either the in-process TopsailAI
// adapter or a standalone Provider CLI.
func registerAdapterType(registry *adapter.Registry, providerType string, store *endpointstorage.Store, controlActions *controlaction.ControlActionSet) error {
	if registry == nil || store == nil {
		return fmt.Errorf("registry and store are required")
	}
	var factory adapter.Factory
	switch providerType {
	case "topsailai":
		factory = func(_ context.Context, local adapter.Config) (adapter.Adapter, error) {
			return topsailaiadapter.New(topsailaiadapter.Config{
				AdapterID: local.AdapterID, Executable: local.Command,
				Timeout:        time.Duration(local.TimeoutMS) * time.Millisecond,
				ResourceMapper: store,
				// The Endpoint-global control action set is passed explicitly rather
				// than read from the environment inside Describe, so the adapter has
				// no hidden configuration dependency and a test can supply its own.
				ControlActions: controlActions,
			})
		}
	case "genericcli":
		factory = func(ctx context.Context, local adapter.Config) (adapter.Adapter, error) {
			// A display name is required by the adapter and is not part of the
			// operator-facing adapter document, so the adapter ID is the fallback.
			// It is descriptive only and never an identity.
			displayName := local.DisplayName
			if displayName == "" {
				displayName = local.AdapterID
			}
			// The declared capabilities are the operator's allowlist. The adapter
			// intersects them with what the provider actually advertises, so an
			// operation the provider does not offer is unreachable even when it was
			// configured. The revision is carried through unchanged, which is what
			// makes a published effective revision meaningful.
			var capabilities protocol.CapabilityDescriptor
			if local.Capabilities != nil {
				capabilities = *local.Capabilities
			}
			return genericcli.New(ctx, genericcli.Config{
				AdapterID: local.AdapterID, DisplayName: displayName,
				Executable: local.Command, Args: local.Args,
				Timeout:        time.Duration(local.TimeoutMS) * time.Millisecond,
				MaxStdinBytes:  genericCLIMaxStdinBytes,
				MaxStdoutBytes: genericCLIMaxStdoutBytes,
				MaxStderrBytes: genericCLIMaxStderrBytes,
				MaxRecords:     genericCLIMaxRecords,
				EndpointLimits: genericCLIConcurrency,
				AdapterLimits:  genericCLIConcurrency,
				Capabilities:   capabilities,
				Mapper:         store,
			})
		}
	default:
		return fmt.Errorf("unknown adapter provider type %q", providerType)
	}
	return registry.RegisterType(providerType, factory)
}
