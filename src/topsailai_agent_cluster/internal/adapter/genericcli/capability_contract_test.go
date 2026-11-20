package genericcli

import (
	"testing"

	"topsailai_agent_cluster/internal/protocol"
	"topsailai_agent_cluster/internal/providercli"
)

// readCapability builds one configured read capability with the metadata the
// Endpoint would publish for it.
func readCapability(name string) protocol.Capability {
	return protocol.Capability{
		Name:               name,
		Version:            "v1",
		TargetKinds:        []string{"session"},
		SafetyClass:        protocol.SafetyClassReadOnly,
		RequiredPermission: "view",
	}
}

// TestIntersectCapabilitiesKeepsAFunctionImplementedRead proves a configured
// output.read survives when the provider advertises read_output.
//
// The Cluster names a capability after what the operator asks for, while the
// Provider names the function after what it does. Comparing those two
// vocabularies directly matched nothing, so a configured read capability was
// dropped even though the provider implemented it. The Endpoint then advertised
// no output surface and refused the request as unsupported before the adapter was
// consulted, which reads as "this provider cannot read output" when it can.
func TestIntersectCapabilitiesKeepsAFunctionImplementedRead(t *testing.T) {
	configured := protocol.CapabilityDescriptor{
		Revision:     "rev-1",
		Capabilities: []protocol.Capability{readCapability(protocol.OperationOutputRead)},
	}
	descriptor := providercli.Descriptor{Functions: []string{providercli.FunctionReadOutput}}

	effective := intersectCapabilities(configured, descriptor)
	if len(effective.Capabilities) != 1 {
		t.Fatalf("effective capabilities = %v, want the configured read kept because the provider advertises %q",
			capabilityNames(effective), providercli.FunctionReadOutput)
	}
	if got := effective.Capabilities[0].Name; got != protocol.OperationOutputRead {
		t.Fatalf("effective capability = %q, want %q", got, protocol.OperationOutputRead)
	}
}

// TestIntersectCapabilitiesDropsAFunctionImplementedReadTheProviderDoesNotOffer
// is the reverse case.
//
// Without it, keeping every configured capability would pass the positive test
// while advertising a read the provider cannot serve. The operator would then see
// a provider error instead of a capability gap, which is the defect the
// intersection exists to prevent.
func TestIntersectCapabilitiesDropsAFunctionImplementedReadTheProviderDoesNotOffer(t *testing.T) {
	configured := protocol.CapabilityDescriptor{
		Revision:     "rev-1",
		Capabilities: []protocol.Capability{readCapability(protocol.OperationOutputRead)},
	}
	// The provider advertises the follow function only, so the read function is
	// genuinely absent rather than the whole function list being empty.
	descriptor := providercli.Descriptor{Functions: []string{providercli.FunctionFollowOutput}}

	effective := intersectCapabilities(configured, descriptor)
	if len(effective.Capabilities) != 0 {
		t.Fatalf("effective capabilities = %v, want none because the provider does not advertise %q",
			capabilityNames(effective), providercli.FunctionReadOutput)
	}
}

// TestIntersectCapabilitiesKeepsAFunctionImplementedFollow proves a configured
// output.follow survives when the provider advertises follow_output.
//
// Follow is the capability the issue was filed about: the Endpoint advertised no
// follow surface at all, so a follow request was refused as unsupported before
// the adapter was consulted.
func TestIntersectCapabilitiesKeepsAFunctionImplementedFollow(t *testing.T) {
	configured := protocol.CapabilityDescriptor{
		Revision:     "rev-1",
		Capabilities: []protocol.Capability{readCapability(protocol.OperationOutputFollow)},
	}
	descriptor := providercli.Descriptor{Functions: []string{providercli.FunctionFollowOutput}}

	effective := intersectCapabilities(configured, descriptor)
	if len(effective.Capabilities) != 1 {
		t.Fatalf("effective capabilities = %v, want the configured follow kept because the provider advertises %q",
			capabilityNames(effective), providercli.FunctionFollowOutput)
	}
	if got := effective.Capabilities[0].Name; got != protocol.OperationOutputFollow {
		t.Fatalf("effective capability = %q, want %q", got, protocol.OperationOutputFollow)
	}
}

// TestIntersectCapabilitiesDropsAFunctionImplementedFollowTheProviderDoesNotOffer
// is the reverse case for follow.
//
// A provider that cannot tail must report a capability gap, not an empty
// successful stream. Advertising follow on the strength of a configured entry
// would make the Endpoint accept a request it cannot serve.
func TestIntersectCapabilitiesDropsAFunctionImplementedFollowTheProviderDoesNotOffer(t *testing.T) {
	configured := protocol.CapabilityDescriptor{
		Revision:     "rev-1",
		Capabilities: []protocol.Capability{readCapability(protocol.OperationOutputFollow)},
	}
	descriptor := providercli.Descriptor{Functions: []string{providercli.FunctionReadOutput}}

	effective := intersectCapabilities(configured, descriptor)
	if len(effective.Capabilities) != 0 {
		t.Fatalf("effective capabilities = %v, want none because the provider does not advertise %q",
			capabilityNames(effective), providercli.FunctionFollowOutput)
	}
}

// TestIntersectCapabilitiesKeepsAQueryImplementedCapability proves a configured
// agent.model.list survives when the provider advertises the model.catalog query.
//
// The model catalog is reached through a versioned query rather than a function,
// so it exercises the other translation kind. A query carries a version, and the
// version must match: the Cluster capability version and the Provider query
// version are the same contract version.
func TestIntersectCapabilitiesKeepsAQueryImplementedCapability(t *testing.T) {
	configured := protocol.CapabilityDescriptor{
		Revision:     "rev-1",
		Capabilities: []protocol.Capability{readCapability(protocol.OperationAgentModelList)},
	}
	descriptor := providercli.Descriptor{
		Queries: []providercli.NamedContract{{Name: providercli.QueryModelCatalog, Version: "v1"}},
	}

	effective := intersectCapabilities(configured, descriptor)
	if len(effective.Capabilities) != 1 {
		t.Fatalf("effective capabilities = %v, want the configured model list kept because the provider advertises %q",
			capabilityNames(effective), providercli.QueryModelCatalog)
	}
	if got := effective.Capabilities[0].Name; got != protocol.OperationAgentModelList {
		t.Fatalf("effective capability = %q, want %q", got, protocol.OperationAgentModelList)
	}
}

// TestIntersectCapabilitiesDropsAQueryImplementedCapabilityTheProviderDoesNotOffer
// is the reverse case for the query kind.
func TestIntersectCapabilitiesDropsAQueryImplementedCapabilityTheProviderDoesNotOffer(t *testing.T) {
	configured := protocol.CapabilityDescriptor{
		Revision:     "rev-1",
		Capabilities: []protocol.Capability{readCapability(protocol.OperationAgentModelList)},
	}
	descriptor := providercli.Descriptor{
		Queries: []providercli.NamedContract{{Name: providercli.QuerySessionMessages, Version: "v1"}},
	}

	effective := intersectCapabilities(configured, descriptor)
	if len(effective.Capabilities) != 0 {
		t.Fatalf("effective capabilities = %v, want none because the provider does not advertise %q",
			capabilityNames(effective), providercli.QueryModelCatalog)
	}
}

// TestIntersectCapabilitiesDropsAQueryImplementedCapabilityAtAnotherVersion
// proves the query match includes the version.
//
// A query is versioned, so a provider that advertises the same query name at a
// different version implements a different contract. Matching the name alone
// would advertise a capability whose request and result schemas the provider does
// not implement, and the operator would see a protocol failure instead of a
// capability gap.
func TestIntersectCapabilitiesDropsAQueryImplementedCapabilityAtAnotherVersion(t *testing.T) {
	configured := protocol.CapabilityDescriptor{
		Revision:     "rev-1",
		Capabilities: []protocol.Capability{readCapability(protocol.OperationAgentModelList)},
	}
	descriptor := providercli.Descriptor{
		Queries: []providercli.NamedContract{{Name: providercli.QueryModelCatalog, Version: "v2"}},
	}

	effective := intersectCapabilities(configured, descriptor)
	if len(effective.Capabilities) != 0 {
		t.Fatalf("effective capabilities = %v, want none because the provider advertises %q at another version",
			capabilityNames(effective), providercli.QueryModelCatalog)
	}
}

// TestIntersectCapabilitiesDropsAnUnknownCapability proves the intersection stays
// fail-closed for a name the translation table does not describe.
//
// The table is the only place that knows which Provider contract implements a
// Cluster capability. A name with no entry must be dropped rather than advertised
// on the strength of a guess, because advertising a capability nothing implements
// is exactly the false-capability condition the intersection exists to prevent.
func TestIntersectCapabilitiesDropsAnUnknownCapability(t *testing.T) {
	configured := protocol.CapabilityDescriptor{
		Revision:     "rev-1",
		Capabilities: []protocol.Capability{readCapability("fixture.unknown_read")},
	}
	// The provider advertises every function and query the table knows about, so
	// the capability is dropped because it has no table entry rather than because
	// the provider happens to be empty.
	descriptor := providercli.Descriptor{
		Functions: []string{providercli.FunctionReadOutput, providercli.FunctionFollowOutput},
		Queries:   []providercli.NamedContract{{Name: providercli.QueryModelCatalog, Version: "v1"}},
	}

	effective := intersectCapabilities(configured, descriptor)
	if len(effective.Capabilities) != 0 {
		t.Fatalf("effective capabilities = %v, want none because no Provider contract implements %q",
			capabilityNames(effective), "fixture.unknown_read")
	}
}

// TestIntersectCapabilitiesKeepsEveryTranslatedKindTogether proves the four
// contract lists are read independently in one call.
//
// The first version of this function took the operation and control action lists
// as separate arguments, so a caller that passed both still dropped every
// capability served by a function or a query. Taking the descriptor makes that
// omission impossible, and this test asserts the four kinds survive together
// rather than one at a time.
func TestIntersectCapabilitiesKeepsEveryTranslatedKindTogether(t *testing.T) {
	configured := protocol.CapabilityDescriptor{
		Revision: "rev-1",
		Capabilities: []protocol.Capability{
			{Name: "message.send", Version: "v1", TargetKinds: []string{"session"}},
			{Name: "ctl.fixture_probe", Version: "v1", TargetKinds: []string{"session"}},
			readCapability(protocol.OperationOutputRead),
			readCapability(protocol.OperationOutputFollow),
			readCapability(protocol.OperationAgentModelList),
		},
	}
	descriptor := providercli.Descriptor{
		Operations:     []providercli.NamedContract{{Name: "message.send", Version: "v1"}},
		ControlActions: []providercli.NamedContract{{Name: "ctl.fixture_probe", Version: "v1"}},
		Functions:      []string{providercli.FunctionReadOutput, providercli.FunctionFollowOutput},
		Queries:        []providercli.NamedContract{{Name: providercli.QueryModelCatalog, Version: "v1"}},
	}

	effective := intersectCapabilities(configured, descriptor)
	if len(effective.Capabilities) != 5 {
		t.Fatalf("effective capabilities = %v, want all five configured capabilities kept", capabilityNames(effective))
	}
}

// capabilityNames renders the effective capability names for a failure message.
func capabilityNames(descriptor protocol.CapabilityDescriptor) []string {
	names := make([]string, 0, len(descriptor.Capabilities))
	for _, capability := range descriptor.Capabilities {
		names = append(names, capability.Name)
	}
	return names
}

// TestEveryContractMappedOperationIsAdvertisedWhenTheProviderOffersIt proves the
// capability contract map is complete in both directions.
//
// The map is the only place that says which provider contract implements a Cluster
// operation. An operation missing from it is never advertised, and a capability that
// is never advertised is invisible: no error is logged, because nothing is attempted,
// and the operator reads the absent command as "not implemented". Enumerating the map
// rather than sampling it means a newly added operation cannot be forgotten here.
func TestEveryContractMappedOperationIsAdvertisedWhenTheProviderOffersIt(t *testing.T) {
	for operation, contract := range capabilityProviderContract {
		t.Run(operation, func(t *testing.T) {
			configured := protocol.CapabilityDescriptor{
				Revision:     "rev-1",
				Capabilities: []protocol.Capability{readCapability(operation)},
			}
			descriptor := providercli.Descriptor{}
			switch contract.kind {
			case contractQuery:
				descriptor.Queries = []providercli.NamedContract{{Name: contract.name, Version: "v1"}}
			case contractFunction:
				descriptor.Functions = []string{contract.name}
			default:
				t.Fatalf("operation %q has an unknown contract kind", operation)
			}
			effective := intersectCapabilities(configured, descriptor)
			if len(effective.Capabilities) != 1 || effective.Capabilities[0].Name != operation {
				t.Fatalf("effective capabilities = %v, want %q kept because the provider offers %q",
					capabilityNames(effective), operation, contract.name)
			}
		})
	}
}

// TestModelRegistryIsAdvertisedOnlyWhenTheProviderOffersTheRegistryQuery proves the
// registry capability is gated on its own query rather than on the model catalog.
//
// The two are separate contracts, so a provider that can answer a session catalog
// must not be credited with a machine registry it cannot answer.
func TestModelRegistryIsAdvertisedOnlyWhenTheProviderOffersTheRegistryQuery(t *testing.T) {
	configured := protocol.CapabilityDescriptor{
		Revision:     "rev-1",
		Capabilities: []protocol.Capability{readCapability(protocol.OperationAgentModelRegistry)},
	}
	catalogOnly := providercli.Descriptor{
		Queries: []providercli.NamedContract{{Name: providercli.QueryModelCatalog, Version: "v1"}},
	}
	if effective := intersectCapabilities(configured, catalogOnly); len(effective.Capabilities) != 0 {
		t.Fatalf("registry advertised from the catalog query: %v", capabilityNames(effective))
	}
	registry := providercli.Descriptor{
		Queries: []providercli.NamedContract{{Name: providercli.QueryModelRegistry, Version: "v1"}},
	}
	effective := intersectCapabilities(configured, registry)
	if len(effective.Capabilities) != 1 || effective.Capabilities[0].Name != protocol.OperationAgentModelRegistry {
		t.Fatalf("effective capabilities = %v, want %q", capabilityNames(effective), protocol.OperationAgentModelRegistry)
	}
}
