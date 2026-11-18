package main

import (
	"context"
	"fmt"
	"os"
	"time"

	"topsailai_agent_cluster/internal/adapter"
	"topsailai_agent_cluster/internal/adapter/genericcli"
	"topsailai_agent_cluster/internal/protocol"
	"topsailai_agent_cluster/internal/providercli"
	endpointstorage "topsailai_agent_cluster/internal/storage/endpoint"
)

// Generic CLI Adapter bounds are Endpoint-local limits on one Provider CLI
// invocation. They are declared here instead of being read from the adapter
// configuration because the operator-facing adapter document carries no limit
// fields, and genericcli.New rejects a zero limit rather than inventing one.
//
// The byte limits equal what the shipped Provider CLI advertises, so the Endpoint
// does not narrow a provider that is willing to answer more. The record budget
// does not: it is smaller than the provider's advertised 10_000, and the Endpoint
// never counts records, because a count truncates a healthy stream whose only
// fault is being long. A live follow is bounded by bytes and by its deadline
// instead. The value survives only because genericcli.New and the wire schema both
// require a positive budget, so a provider that began enforcing it would truncate
// a long tail; the follow path must therefore never treat it as a bound.
//
// Concurrency is narrowed by the provider, because the adapter takes the minimum
// of the Endpoint, adapter and provider limits. The byte and record budgets are
// not narrowed that way: they are sent as the Endpoint's own values.
const (
	genericCLIMaxStdinBytes = 1 << 20
	// genericCLIMaxStdoutBytes bounds one provider response document, not one
	// provider payload. A detail document is carried inside a JSON envelope, so the
	// bytes on stdout are larger than the document itself: escaping alone measured
	// 1.114x on a real record, and a control character expands to six bytes as
	// \u00XX. A 1 MiB detail bound therefore needs headroom above 1 MiB here, or the
	// transport rejects the response before the document bound is ever consulted
	// and the operator reads a generic stdout-limit failure instead of the real
	// reason. 8 MiB covers the six-times worst case for the largest permitted
	// document.
	genericCLIMaxStdoutBytes = 8 << 20
	genericCLIMaxStderrBytes = 64 << 10
	genericCLIMaxRecords     = 128
)

// adapterProviderType is the one provider type this Endpoint ships an
// implementation for.
//
// It is a name, not a selector. The Endpoint has exactly one adapter
// implementation, so a configured provider type can only be checked against this
// name; it cannot choose between implementations, because there is nothing to
// choose between. Keeping the name here rather than in a switch is what makes that
// structural: adding a second implementation would require a deliberate change to
// this file instead of a new case that silently becomes reachable through
// configuration.
const adapterProviderType = "genericcli"

// genericCLIConcurrency is the Endpoint-side concurrency ceiling for one Generic
// CLI Adapter. It is a value rather than a constant because the type is a struct.
//
// Total is deliberately larger than the sum of the class limits. Each class owns
// its own channel, so a class can only be refused by the shared total channel when
// Total is smaller than the sum; keeping Total at or above the sum is what makes
// "one class can never starve another" structural rather than probabilistic. The
// sum here is Discovery 2 + Read 4 + Mutation 1 + Follow 2 = 9, so Total is 9.
var genericCLIConcurrency = providercli.ConcurrencyLimits{Total: 9, Discovery: 2, Mutation: 1, Follow: 2}

// genericCLIReadConcurrency bounds concurrent operator reads for one Adapter
// instance. It is Endpoint-local scheduling policy rather than a Provider
// capability, so it is not part of genericCLIConcurrency and not part of the wire
// descriptor. Reads are separated from discovery so the Endpoint's own periodic
// collection can never delay a command the operator is waiting for.
const genericCLIReadConcurrency = 4

// registerAdapter installs the single adapter implementation this Endpoint ships.
//
// It takes no provider type. A provider type used to select the factory through a
// switch, which meant the Endpoint held provider-specific code reachable only by
// configuration. There is one implementation, so the factory is registered once
// under adapterProviderType and the registry decides whether a configured name
// refers to it. A name that does not is refused by the registry, not by a branch
// here.
//
// The control action catalog is deliberately not a parameter: the operator's
// adapter document is the only source of ctl. capabilities, and the provider that
// implements an action declares what the action is. The factory therefore only
// builds the adapter from the document it is handed, so there is exactly one place
// with the authority to publish a ctl. capability.
func registerAdapter(registry *adapter.Registry, store *endpointstorage.Store) error {
	if registry == nil || store == nil {
		return fmt.Errorf("registry and store are required")
	}
	// The process environment is read once here, at the boundary, and passed down
	// as a value. Leaving it unset made every Provider CLI inherit the Endpoint's
	// own environment implicitly, so a Provider that resolves its home from HOME
	// silently depended on an inheritance it never declared: an Endpoint started
	// with a scrubbed environment would make the Provider resolve a different home
	// and report zero rows, with no error to explain it. Reading it here keeps one
	// boundary read and makes the dependency explicit.
	environment := os.Environ()
	factory := func(ctx context.Context, local adapter.Config) (adapter.Adapter, error) {
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
			Executable: local.Command, Args: local.Args, Environment: environment,
			Timeout:        time.Duration(local.TimeoutMS) * time.Millisecond,
			MaxStdinBytes:  genericCLIMaxStdinBytes,
			MaxStdoutBytes: genericCLIMaxStdoutBytes,
			MaxStderrBytes: genericCLIMaxStderrBytes,
			MaxRecords:     genericCLIMaxRecords,
			EndpointLimits: genericCLIConcurrency,
			AdapterLimits:  genericCLIConcurrency,
			ReadLimit:      genericCLIReadConcurrency,
			Capabilities:   capabilities,
			Mapper:         store,
		})
	}
	return registry.RegisterType(adapterProviderType, factory)
}

// validateProviderType reports whether a configured provider type names the
// implementation this Endpoint registered.
//
// The check is a name comparison, not a dispatch. It exists so a configuration
// that still names a removed adapter fails at startup with a message that says
// what this node implements, instead of failing later on the first operation with
// a provider error that looks like a provider defect. The registry would refuse the
// same name on Configure; validating here only moves the failure earlier and makes
// the message actionable.
func validateProviderType(providerType string) error {
	if providerType == adapterProviderType {
		return nil
	}
	return fmt.Errorf("provider type %q is not registered; this Endpoint implements %q", providerType, adapterProviderType)
}
