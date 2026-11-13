package main

// topsailaiDescriptor reports only functions implemented by this executable.
func topsailaiDescriptor() descriptor {
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
		Functions:  []string{functionDescribe, functionDiscover, functionInspect, functionQuery, functionReadOutput},
		Operations: []namedContract{},
		Queries: []namedContract{
			{Name: queryLaunchOptions, Version: queryVersion},
			{Name: queryHistoryMessages, Version: queryVersion},
			{Name: queryModelCatalog, Version: queryVersion},
			{Name: querySessionMessages, Version: queryVersion},
		},
		ControlActions: []namedContract{},
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
