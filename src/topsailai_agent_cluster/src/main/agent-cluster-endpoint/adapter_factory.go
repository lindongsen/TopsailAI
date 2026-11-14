package main

import (
	"context"
	"fmt"
	"time"

	"topsailai_agent_cluster/internal/adapter"
	"topsailai_agent_cluster/internal/adapter/genericcli"
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

// withControlActions merges the Endpoint-local control action catalog into the
// configured capability descriptor.
//
// The catalog is the only source of ctl. actions, and it is Endpoint-local
// administrative configuration rather than part of the operator-facing adapter
// document. Without this merge the catalog never reached the effective
// descriptor: the adapter intersected the configured list with what the provider
// advertised, the catalog was not in that list, so no ctl. capability was
// published and every control command was refused as unsupported before the
// policy hook could authorize it. A configured catalog therefore had no effect.
//
// The revision is preserved because it is the operator's declared value and the
// adapter carries it through unchanged. A nil catalog leaves the descriptor
// untouched, which is the fail-closed default: no catalog, no ctl. capability.
func withControlActions(configured *protocol.CapabilityDescriptor, set *controlaction.ControlActionSet) *protocol.CapabilityDescriptor {
	actions := controlaction.Capabilities(set)
	if len(actions) == 0 {
		return configured
	}
	merged := protocol.CapabilityDescriptor{Capabilities: actions}
	if configured != nil {
		merged.Revision = configured.Revision
		merged.Capabilities = append(append([]protocol.Capability(nil), configured.Capabilities...), actions...)
	}
	return &merged
}

// registerAdapterType installs the factory for one provider type.
//
// The control action catalog is deliberately not a parameter: the catalog is
// merged into the configured capability descriptor before the adapter is
// configured (see withControlActions), so the factory only has to build the
// adapter from the document it is handed. Passing the catalog here as well
// would give two places the authority to publish a ctl. capability, and the
// second one would be the one nobody reads.
//
// genericcli is the only provider type an Endpoint can be configured with. The
// in-process TopsailAI adapter and the legacy command adapter were removed, so a
// configuration that still names either of them is refused here instead of being
// accepted and then failing on the first operation. Refusing loudly is the point:
// a silent fallback to genericcli would run a provider CLI against a command line
// that was written for a different adapter, and the operator would see a provider
// error rather than a configuration error.
func registerAdapterType(registry *adapter.Registry, providerType string, store *endpointstorage.Store) error {
	if registry == nil || store == nil {
		return fmt.Errorf("registry and store are required")
	}
	var factory adapter.Factory
	switch providerType {
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
