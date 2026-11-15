package main

import (
	"context"
	"testing"
)

// advertisedOperations returns the operation names one descriptor advertises.
func advertisedOperations(platform platformCapabilities) []string {
	names := make([]string, 0, len(supportedMutationOperations))
	for _, contract := range mutationOperations(platform) {
		names = append(names, contract.Name)
	}
	return names
}

// containsOperation reports whether one name appears in a list.
func containsOperation(names []string, want string) bool {
	for _, name := range names {
		if name == want {
			return true
		}
	}
	return false
}

// TestAgentStopIsAdvertisedOnlyWhereTheHostCanStop proves the descriptor reports
// the host rather than a compiled-in list.
//
// agent.stop terminates a provider process, so a host that cannot prove a readable
// process table and a working pidfd must not advertise it. Advertising it would
// claim a capability the executable cannot honour, and the operator would learn
// about the gap only after the operation failed.
func TestAgentStopIsAdvertisedOnlyWhereTheHostCanStop(t *testing.T) {
	if !containsOperation(advertisedOperations(supportedPlatform), operationAgentStop) {
		t.Fatal("agent.stop is missing on a host that can stop a provider process")
	}
	if containsOperation(advertisedOperations(unsupportedPlatform), operationAgentStop) {
		t.Fatal("agent.stop is advertised on a host that cannot stop a provider process")
	}
}

// TestEveryOtherOperationSurvivesAnUnsupportedHost proves the gate is narrow.
//
// Only agent.stop has a host requirement. Dropping another operation on the same
// host would silently remove a capability that works everywhere.
func TestEveryOtherOperationSurvivesAnUnsupportedHost(t *testing.T) {
	advertised := advertisedOperations(unsupportedPlatform)
	for _, operation := range supportedMutationOperations {
		if operation == operationAgentStop {
			continue
		}
		if !containsOperation(advertised, operation) {
			t.Fatalf("%s is missing on a host that cannot stop a provider process", operation)
		}
	}
	if len(advertised) != len(supportedMutationOperations)-1 {
		t.Fatalf("advertised=%v", advertised)
	}
}

// TestAgentStopIsRefusedBeforeAnyReadOnAnUnsupportedHost proves the refusal happens
// before the authority read and before any argv exists.
//
// The runner is given a complete set of answers, so a provider without the gate
// would succeed and the assertion would name the real defect. An empty runner would
// abort inside the runner on the first unexpected call, which would make the test
// pass for the wrong reason: it would prove the runner was strict, not that the gate
// refused. The call count is asserted as well, because a refusal that happened after
// the read would still satisfy a "did it fail" assertion.
func TestAgentStopIsRefusedBeforeAnyReadOnAnUnsupportedHost(t *testing.T) {
	runner := &scriptedRunner{t: t, answers: map[string][]runnerAnswer{
		authorityCall: answer(liveWorkspaceDocument("7")),
		"workspace\x00kill\x00s-1\x00-g\x007\x00--json": answer(`{"ok":true}`),
	}}
	provider := &provider{runner: runner, now: fixedProvider(runner).now, platform: unsupportedPlatform}
	response := provider.dispatch(context.Background(), mutationRequest(operationAgentStop, liveSessionTarget(t, "7"), `{}`))
	if response.OK || response.Error == nil {
		t.Fatalf("an unsupported host served agent.stop: %+v", response)
	}
	if response.Error.Code != "unsupported" {
		t.Fatalf("error code=%q want unsupported", response.Error.Code)
	}
	if len(runner.calls) != 0 {
		t.Fatalf("an unsupported operation reached the provider: %v", runner.calls)
	}
}

// TestAgentStopStillRunsOnASupportedHost proves the gate does not disable the
// operation where the host supports it.
//
// Without this half, a gate that refused everywhere would pass the refusal test.
func TestAgentStopStillRunsOnASupportedHost(t *testing.T) {
	runner := &scriptedRunner{t: t, answers: map[string][]runnerAnswer{
		authorityCall: answer(liveWorkspaceDocument("7")),
		"workspace\x00kill\x00s-1\x00-g\x007\x00--json": answer(`{"ok":true}`),
	}}
	response := fixedProvider(runner).dispatch(context.Background(), mutationRequest(operationAgentStop, liveSessionTarget(t, "7"), `{}`))
	if !response.OK {
		t.Fatalf("response=%+v", response)
	}
	if len(runner.calls) != 2 {
		t.Fatalf("calls=%v", runner.calls)
	}
}

// TestPlatformGateIsNotAPackageGlobal proves the platform value travels with the
// provider rather than through process state.
//
// Two providers built with different values must disagree in the same process. A
// package-level switch would make the second construction overwrite the first.
func TestPlatformGateIsNotAPackageGlobal(t *testing.T) {
	supported := newProvider(stubCommandRunner{}, controlCatalog{}, supportedPlatform)
	unsupported := newProvider(stubCommandRunner{}, controlCatalog{}, unsupportedPlatform)
	supportedNames := advertisedOperations(supported.platform)
	unsupportedNames := advertisedOperations(unsupported.platform)
	if !containsOperation(supportedNames, operationAgentStop) {
		t.Fatal("the supported provider lost agent.stop")
	}
	if containsOperation(unsupportedNames, operationAgentStop) {
		t.Fatal("the unsupported provider gained agent.stop")
	}
}
