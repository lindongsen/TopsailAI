package main

// topsailaiDescriptor reports only functions implemented by this executable.
//
// The advertised operation list is derived from the same table dispatch uses, so a
// capability cannot be advertised without a handler and a handler cannot exist
// without being advertised. The control actions come from the Provider-local
// catalog, so an unconfigured deployment advertises none.
//
// The advertised operation list is also narrowed by the host: agent.stop is
// advertised only where the platform probe proved the process can be stopped
// safely, so the descriptor never claims a capability this host cannot honour.
//
// The advertised function list is narrower than the dispatch switch on purpose:
// every advertised name must also be admitted by the wire contract, because
// advertising a function the request schema rejects would claim a capability no
// caller can reach. resolve is advertised here only because the schema enum admits
// it; the two sides change together or not at all.
func topsailaiDescriptor(control controlCatalog, platform platformCapabilities) descriptor {
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
		Functions:  []string{functionDescribe, functionDiscover, functionInspect, functionResolve, functionExecute, functionQuery, functionReadOutput, functionFollowOutput},
		Operations: mutationOperations(platform),
		Queries: []namedContract{
			{Name: queryLaunchOptions, Version: queryVersion},
			{Name: queryHistoryMessages, Version: queryVersion},
			{Name: queryModelCatalog, Version: queryVersion},
			{Name: querySessionMessages, Version: queryVersion},
			{Name: querySessionMetrics, Version: queryVersion},
			{Name: querySessionDetail, Version: queryVersion},
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
