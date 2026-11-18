package genericcli

// The published capability revision is the Provider's own descriptor revision.
//
// The column exists so an operator can tell whether the implementation behind an
// Endpoint changed. Only the Provider knows that: it is the party whose code
// actually serves the operations. A configured string cannot answer the question,
// because an operator writes it once and never updates it, which is why every
// Endpoint in a fleet published the same value while serving different surfaces.
//
// These tests pin the source rather than the value. Asserting only that some
// revision is published would pass for either source, so each case configures a
// different string from the one the Provider declares and asserts which one won.

import (
	"context"
	"testing"

	"topsailai_agent_cluster/internal/adapter"
	"topsailai_agent_cluster/internal/protocol"
	"topsailai_agent_cluster/internal/providercli"
)

// mustAdapterWithRevisions builds an Adapter whose configured revision and whose
// Provider descriptor revision are both supplied by the caller, so a test can
// tell which one the published descriptor carries.
func mustAdapterWithRevisions(t *testing.T, configuredRevision, providerRevision string) *Adapter {
	t.Helper()
	limits := providercli.ConcurrencyLimits{Total: 2, Discovery: 1, Mutation: 1, Follow: 1}
	provider := newFakeProvider(t)
	provider.invoke = func(request providercli.Request) (providercli.Response, error) {
		response := describeResponseWithFunctions(request)
		response.Descriptor.DescriptorRevision = providerRevision
		return response, nil
	}
	config := Config{
		AdapterID: "a", DisplayName: "A", Timeout: 0,
		MaxStdinBytes: 65536, MaxStdoutBytes: 65536, MaxStderrBytes: 4096, MaxRecords: 10,
		EndpointLimits: limits, AdapterLimits: limits,
		Mapper: &fakeMapper{mappings: map[string]adapter.ResourceMapping{}},
		Capabilities: protocol.CapabilityDescriptor{
			Revision:     configuredRevision,
			Capabilities: []protocol.Capability{{Name: "agent.start", Version: "v1", TargetKinds: []string{"session"}}},
		},
	}
	binding, err := newWithRunner(context.Background(), config, runnerAdapter{provider})
	if err != nil {
		t.Fatalf("new adapter: %v", err)
	}
	return binding
}

// TestPublishedRevisionComesFromTheProvider proves the Provider's descriptor
// revision is what reaches the published surface, not the configured string.
//
// The two values differ on purpose. If the implementation still copied the
// configured string, this test would report the configured value and fail.
func TestPublishedRevisionComesFromTheProvider(t *testing.T) {
	binding := mustAdapterWithRevisions(t, "configured-r1", "provider-r1")

	descriptor, err := binding.Describe(context.Background())
	if err != nil {
		t.Fatalf("describe: %v", err)
	}
	if descriptor.Capabilities.Revision != "provider-r1" {
		t.Fatalf("published revision = %q, want the Provider's descriptor revision %q", descriptor.Capabilities.Revision, "provider-r1")
	}
}

// TestPublishedRevisionDoesNotFallBackToTheConfiguration is the other half.
//
// A Provider that declares no revision must leave the published value empty
// rather than borrow the configured string. Falling back would restore the second
// source of truth this change removes, and it would do so silently: the column
// would look populated while reporting a value the Provider never claimed.
//
// The downstream reader already turns an empty revision into "unknown", so an
// empty value here is a supported state rather than a broken one.
func TestPublishedRevisionDoesNotFallBackToTheConfiguration(t *testing.T) {
	binding := mustAdapterWithRevisions(t, "configured-r1", "")

	descriptor, err := binding.Describe(context.Background())
	if err != nil {
		t.Fatalf("describe: %v", err)
	}
	if descriptor.Capabilities.Revision != "" {
		t.Fatalf("published revision = %q, want empty because the Provider declared none and the configured string must not be substituted", descriptor.Capabilities.Revision)
	}
}

// TestPublishedRevisionChangesWhenTheProviderChanges proves the value tracks the
// Provider rather than the configuration.
//
// This is the property the column exists for: an operator upgrades the Provider
// CLI, the Endpoint refreshes its descriptor, and the published revision moves.
// The configured string is held constant across both cases, so a value that
// stayed put would prove the configuration is still the source.
func TestPublishedRevisionChangesWhenTheProviderChanges(t *testing.T) {
	before := mustAdapterWithRevisions(t, "configured-r1", "provider-r1")
	after := mustAdapterWithRevisions(t, "configured-r1", "provider-r2")

	beforeDescriptor, err := before.Describe(context.Background())
	if err != nil {
		t.Fatalf("describe before: %v", err)
	}
	afterDescriptor, err := after.Describe(context.Background())
	if err != nil {
		t.Fatalf("describe after: %v", err)
	}
	if beforeDescriptor.Capabilities.Revision == afterDescriptor.Capabilities.Revision {
		t.Fatalf("published revision stayed %q across two Provider revisions, so it does not track the Provider", beforeDescriptor.Capabilities.Revision)
	}
	if afterDescriptor.Capabilities.Revision != "provider-r2" {
		t.Fatalf("published revision after the Provider changed = %q, want %q", afterDescriptor.Capabilities.Revision, "provider-r2")
	}
}
