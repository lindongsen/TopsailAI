package genericcli

import (
	"context"
	"errors"
	"testing"
	"time"

	"topsailai_agent_cluster/internal/adapter"
	"topsailai_agent_cluster/internal/protocol"
	"topsailai_agent_cluster/internal/providercli"
)

// mustAdapterWithCapabilities builds an Adapter whose configured capability
// descriptor is supplied by the caller.
//
// The shared mustAdapter helper configures agent.start only, so it cannot express
// a read surface. This helper exists so a test can configure output.follow and
// then observe what the intersection actually publishes.
func mustAdapterWithCapabilities(t *testing.T, provider *fakeRunner, capabilities []protocol.Capability) *Adapter {
	t.Helper()
	limits := providercli.ConcurrencyLimits{Total: 2, Discovery: 1, Mutation: 1, Follow: 1}
	config := Config{
		AdapterID: "a", DisplayName: "A", Timeout: time.Second,
		MaxStdinBytes: 65536, MaxStdoutBytes: 65536, MaxStderrBytes: 4096, MaxRecords: 10,
		EndpointLimits: limits, AdapterLimits: limits,
		Mapper:       &fakeMapper{mappings: map[string]adapter.ResourceMapping{}},
		Capabilities: protocol.CapabilityDescriptor{Revision: "r", Capabilities: capabilities},
	}
	binding, err := newWithRunner(context.Background(), config, runnerAdapter{provider})
	if err != nil {
		t.Fatalf("new adapter: %v", err)
	}
	return binding
}

// TestAdvertisedFollowCapabilityMatchesTheImplementation proves the published
// output.follow surface and the FollowOutput implementation cannot disagree.
//
// This is the contract the issue asks for, and it is the property the protocol
// requires: a capability that is advertised must be reachable, and a capability
// that is not advertised must not be silently attempted. The two mechanisms are
// independent — the advertisement comes from the capability intersection, while
// the behaviour comes from a function check inside FollowOutput — so nothing
// except a test forces them to agree.
//
// Both directions are asserted. The positive case alone would pass if the
// intersection kept every configured capability, and the negative case alone
// would pass if the intersection dropped everything.
func TestAdvertisedFollowCapabilityMatchesTheImplementation(t *testing.T) {
	cases := []struct {
		name           string
		functions      []string
		wantAdvertised bool
	}{
		{
			// The provider implements the stream, so the configured capability
			// must survive the intersection and the call must reach the provider.
			name:           "provider implements the stream",
			functions:      []string{providercli.FunctionFollowOutput},
			wantAdvertised: true,
		},
		{
			// The provider cannot stream, so the capability must be dropped and
			// the call must report unsupported rather than an empty stream.
			name:           "provider cannot stream",
			functions:      nil,
			wantAdvertised: false,
		},
	}
	for _, test := range cases {
		t.Run(test.name, func(t *testing.T) {
			provider := newFakeProvider(t)
			provider.invoke = func(request providercli.Request) (providercli.Response, error) {
				return describeResponseWithFunctions(request, test.functions...), nil
			}
			binding := mustAdapterWithCapabilities(t, provider, []protocol.Capability{{
				Name: protocol.OperationOutputFollow, Version: "v1",
				TargetKinds: []string{"session"}, SafetyClass: protocol.SafetyClassReadOnly, RequiredPermission: "view",
			}})

			descriptor, err := binding.Describe(context.Background())
			if err != nil {
				t.Fatalf("describe: %v", err)
			}
			var advertised bool
			for _, capability := range descriptor.Capabilities.Capabilities {
				if capability.Name == protocol.OperationOutputFollow {
					advertised = true
				}
			}
			if advertised != test.wantAdvertised {
				t.Fatalf("advertised output.follow = %v, want %v; published capabilities = %v",
					advertised, test.wantAdvertised, capabilityNames(descriptor.Capabilities))
			}

			// The implementation must agree with the advertisement. No mapping is
			// registered, so a provider that implements the stream fails on the
			// lookup instead of returning unsupported, which is what makes the two
			// outcomes distinguishable.
			err = binding.FollowOutput(context.Background(), protocol.OutputFollowRequest{ResourceID: "session-1"}, func(protocol.OutputChunk) error { return nil })
			unsupported := errors.Is(err, adapter.ErrUnsupported)
			if unsupported == test.wantAdvertised {
				t.Fatalf("advertised output.follow = %v but FollowOutput reported unsupported = %v: the published surface and the implementation disagree",
					advertised, unsupported)
			}
		})
	}
}

// TestAdvertisedReadCapabilityMatchesTheImplementation is the same contract for
// output.read.
//
// ReadOutput does not check the function list itself, so the advertisement is the
// only thing that keeps a request from reaching a provider that cannot serve it.
// The test therefore asserts the advertisement follows the provider's function
// list, which is the property the intersection now provides.
func TestAdvertisedReadCapabilityMatchesTheImplementation(t *testing.T) {
	cases := []struct {
		name           string
		functions      []string
		wantAdvertised bool
	}{
		{name: "provider implements the read", functions: []string{providercli.FunctionReadOutput}, wantAdvertised: true},
		{name: "provider cannot read", functions: nil, wantAdvertised: false},
	}
	for _, test := range cases {
		t.Run(test.name, func(t *testing.T) {
			provider := newFakeProvider(t)
			provider.invoke = func(request providercli.Request) (providercli.Response, error) {
				return describeResponseWithFunctions(request, test.functions...), nil
			}
			binding := mustAdapterWithCapabilities(t, provider, []protocol.Capability{{
				Name: protocol.OperationOutputRead, Version: "v1",
				TargetKinds: []string{"session"}, SafetyClass: protocol.SafetyClassReadOnly, RequiredPermission: "view",
			}})

			descriptor, err := binding.Describe(context.Background())
			if err != nil {
				t.Fatalf("describe: %v", err)
			}
			var advertised bool
			for _, capability := range descriptor.Capabilities.Capabilities {
				if capability.Name == protocol.OperationOutputRead {
					advertised = true
				}
			}
			if advertised != test.wantAdvertised {
				t.Fatalf("advertised output.read = %v, want %v; published capabilities = %v",
					advertised, test.wantAdvertised, capabilityNames(descriptor.Capabilities))
			}
		})
	}
}

// TestAdvertisedModelCatalogCapabilityMatchesTheImplementation is the same
// contract for agent.model.list.
//
// The model catalog is reached through a versioned query, so this case also
// proves the query translation reaches the published surface rather than only the
// intersection unit.
func TestAdvertisedModelCatalogCapabilityMatchesTheImplementation(t *testing.T) {
	cases := []struct {
		name           string
		queries        []providercli.NamedContract
		wantAdvertised bool
	}{
		{
			name:           "provider implements the catalog",
			queries:        []providercli.NamedContract{{Name: providercli.QueryModelCatalog, Version: "v1"}},
			wantAdvertised: true,
		},
		{name: "provider cannot list models", queries: nil, wantAdvertised: false},
	}
	for _, test := range cases {
		t.Run(test.name, func(t *testing.T) {
			provider := newFakeProvider(t)
			provider.invoke = func(request providercli.Request) (providercli.Response, error) {
				response := describeResponseWithFunctions(request, providercli.FunctionQuery)
				response.Descriptor.Queries = test.queries
				return response, nil
			}
			binding := mustAdapterWithCapabilities(t, provider, []protocol.Capability{{
				Name: protocol.OperationAgentModelList, Version: "v1",
				TargetKinds: []string{"session"}, SafetyClass: protocol.SafetyClassReadOnly, RequiredPermission: "view",
			}})

			descriptor, err := binding.Describe(context.Background())
			if err != nil {
				t.Fatalf("describe: %v", err)
			}
			var advertised bool
			for _, capability := range descriptor.Capabilities.Capabilities {
				if capability.Name == protocol.OperationAgentModelList {
					advertised = true
				}
			}
			if advertised != test.wantAdvertised {
				t.Fatalf("advertised agent.model.list = %v, want %v; published capabilities = %v",
					advertised, test.wantAdvertised, capabilityNames(descriptor.Capabilities))
			}
		})
	}
}
