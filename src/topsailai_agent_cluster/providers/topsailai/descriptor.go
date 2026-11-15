package main

// topsailaiDescriptor reports only functions implemented by this executable.
//
// The advertised operation list is derived from the same table dispatch uses, so a
// capability cannot be advertised without a handler and a handler cannot exist
// without being advertised. The control actions come from the Provider-local
// catalog, so an unconfigured deployment advertises none.
//
// The advertised function list is narrower than the dispatch switch on purpose:
// resolve has a handler but is not advertised yet, because the frozen request
// schema does not carry the name. Advertising a function the wire contract rejects
// would make the descriptor claim a capability no caller can reach, so the name is
// added here only together with the schema enum that admits it.
func topsailaiDescriptor(control controlCatalog) descriptor {
	return descriptor{
		ProviderType:       "topsailai",
		ProviderVersion:    providerVersion,
		DescriptorRevision: "topsailai-provider-v1",
		ProtocolRange: protocolRange{
			Protocol: protocolName,
			Major:    protocolMajor,
			Minimum:  protocolMinor,
			Maximum:  protocolMinor,
		},
		Functions:  []string{functionDescribe, functionDiscover, functionInspect, functionExecute, functionQuery, functionReadOutput, functionFollowOutput},
		Operations: mutationOperations(),
		Queries: []namedContract{
			{Name: queryLaunchOptions, Version: queryVersion},
			{Name: queryHistoryMessages, Version: queryVersion},
			{Name: queryModelCatalog, Version: queryVersion},
			{Name: querySessionMessages, Version: queryVersion},
		},
		ControlActions: control.contracts(),
		Limits: budget{
			MaxStdoutBytes: 1 << 20,
			MaxStderrBytes: 64 << 10,
			MaxRecords:     10_000,
		},
		Concurrency: concurrencyLimits{
			Total:     8,
			Discovery: 1,
			Mutation:  1,
			Follow:    4,
		},
	}
}
