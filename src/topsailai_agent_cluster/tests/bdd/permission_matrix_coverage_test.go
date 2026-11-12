package bdd

import (
	"os"
	"path/filepath"
	"sort"
	"strconv"
	"strings"
	"testing"

	"topsailai_agent_cluster/internal/endpoint"
	"topsailai_agent_cluster/internal/protocol"
	"topsailai_agent_cluster/internal/security"
)

// operationScenarioMarkers maps one production operation onto the step text that
// must appear in the feature files for that operation.
//
// The map is deliberately keyed by the production operation name, and the guard
// fails when production serves an operation this map does not name. That
// direction is what makes the guard meaningful: adding an operation to
// knownAccessOperations without adding a scenario fails the build, instead of
// leaving the matrix silently one row short while the suite stays green.
//
// The value is the step text rather than the operation name because the feature
// files are written for a reader, so the operation name does not appear in them.
// A marker is the shortest phrase that identifies the operation's own steps and
// cannot be satisfied by another operation's steps.
var operationScenarioMarkers = map[string]string{
	protocolOperationMessageSend:        "the message send command is submitted",
	protocolOperationContextInject:      "the context inject command is submitted",
	protocolOperationExecutionInterrupt: "the execution interrupt command is submitted",
	protocolOperationAgentStart:         "the agent start command is submitted",
	protocolOperationAgentResume:        "the agent resume command is submitted",
	protocolOperationAgentStop:          "the agent stop command is submitted",
	protocolOperationWorkspaceClean:     "the workspace clean command is submitted",
	protocolOperationAgentDriveStart:    "the agent drive start command is submitted",
	protocolOperationAgentDriveStop:     "the agent drive stop command is submitted",
	protocolOperationAgentModelList:     "the model catalog is read with the",
	protocolOperationAgentModelSelect:   "the agent model select command is submitted",
	protocolOperationOutputRead:         "the output snapshot is read with the",
	protocolOperationOutputFollow:       "the output follow is read with the",
	protocolOperationCommandExec:        "the command exec operation is submitted",
	protocolOperationLaunchQuery:        "the launch options is read with the",
	protocolOperationHistoryRead:        "the history is read with the",
	protocolOperationMessagesRead:       "the messages is read with the",
}

// The production operation names the markers are keyed by.
//
// They are aliases of the protocol and policy constants rather than string
// literals, so a renamed constant breaks this file at compile time instead of
// leaving a stale key that silently matches nothing.
const (
	protocolOperationMessageSend        = protocol.OperationMessageSend
	protocolOperationContextInject      = protocol.OperationContextInject
	protocolOperationExecutionInterrupt = protocol.OperationExecutionInterrupt
	protocolOperationAgentStart         = protocol.OperationAgentStart
	protocolOperationAgentResume        = protocol.OperationAgentResume
	protocolOperationAgentStop          = protocol.OperationAgentStop
	protocolOperationWorkspaceClean     = protocol.OperationWorkspaceClean
	protocolOperationAgentDriveStart    = protocol.OperationAgentDriveStart
	protocolOperationAgentDriveStop     = protocol.OperationAgentDriveStop
	protocolOperationAgentModelList     = protocol.OperationAgentModelList
	protocolOperationAgentModelSelect   = protocol.OperationAgentModelSelect
	protocolOperationOutputRead         = protocol.OperationOutputRead
	protocolOperationOutputFollow       = protocol.OperationOutputFollow
	protocolOperationCommandExec        = protocol.OperationCommandExec
	protocolOperationLaunchQuery        = endpoint.OperationLaunchQuery
	protocolOperationHistoryRead        = endpoint.OperationHistoryRead
	protocolOperationMessagesRead       = endpoint.OperationMessagesRead
)

// permissionMatrixFeatureFiles are the two feature files that together must
// cover the whole closed set.
var permissionMatrixFeatureFiles = []string{
	"../../features/endpoint_permission_matrix.feature",
	"../../features/endpoint_query_permission_matrix.feature",
}

// TestPermissionMatrixCoversEveryKnownOperation fails when the production closed
// set contains an operation that no feature scenario exercises.
//
// This is the guard for the silent-loss case: an operation added to
// knownAccessOperations without a matching scenario leaves the matrix one row
// short, and every other test in the suite still passes because nothing compares
// the two.
func TestPermissionMatrixCoversEveryKnownOperation(t *testing.T) {
	corpus := readPermissionMatrixCorpus(t)
	known := endpoint.KnownAccessOperations()
	if len(known) == 0 {
		t.Fatal("the production closed set is empty; the guard cannot verify anything")
	}

	var unmapped, uncovered []string
	for _, operation := range known {
		marker, ok := operationScenarioMarkers[operation]
		if !ok {
			unmapped = append(unmapped, operation)
			continue
		}
		// Two occurrences are required: one scenario that allows the operation
		// and one that refuses it. A single occurrence would let a matrix that
		// only proves the refusal direction pass this guard.
		if count := strings.Count(corpus, marker); count < 2 {
			uncovered = append(uncovered, operation+" (marker "+marker+" appears "+strconv.Itoa(count)+" time(s), want 2)")
		}
	}
	sort.Strings(unmapped)
	sort.Strings(uncovered)

	if len(unmapped) > 0 {
		t.Fatalf("%d operation(s) are served by this build but have no scenario marker registered, so the matrix cannot cover them: %v", len(unmapped), unmapped)
	}
	if len(uncovered) > 0 {
		t.Fatalf("%d operation(s) have fewer than two scenarios, so one direction is unproven: %v", len(uncovered), uncovered)
	}
}

// TestPermissionMatrixMarkersAreLive fails when a marker names an operation the
// build no longer serves, or a phrase no feature file contains.
//
// It is the reverse direction of the guard above. Without it, a removed
// operation would leave a dead marker behind, and the next reader would believe
// the matrix covers something that no longer exists.
func TestPermissionMatrixMarkersAreLive(t *testing.T) {
	corpus := readPermissionMatrixCorpus(t)
	known := make(map[string]struct{}, len(endpoint.KnownAccessOperations()))
	for _, operation := range endpoint.KnownAccessOperations() {
		known[operation] = struct{}{}
	}

	var stale []string
	for operation, marker := range operationScenarioMarkers {
		if _, ok := known[operation]; !ok {
			stale = append(stale, operation+" is no longer served by this build")
			continue
		}
		if !strings.Contains(corpus, marker) {
			stale = append(stale, operation+" marker "+marker+" appears in no feature file")
		}
	}
	sort.Strings(stale)

	if len(stale) > 0 {
		t.Fatalf("%d stale matrix marker(s): %v", len(stale), stale)
	}
}

// TestEveryKnownOperationIsReachableThroughAScope fails when an operation in the
// closed set is covered by no scope.
//
// A permission can still grant such an operation directly, so this is not a
// correctness defect on its own. It is a coverage defect: the scope-based
// scenarios in the matrix grant scopes, so an operation outside every scope can
// only be reached by a permission line, and the matrix would need a row that
// grants it that way.
func TestEveryKnownOperationIsReachableThroughAScope(t *testing.T) {
	covered := make(map[string]struct{})
	for _, operations := range endpoint.ScopeOperations() {
		for _, operation := range operations {
			covered[operation] = struct{}{}
		}
	}

	var unreachable []string
	for _, operation := range endpoint.KnownAccessOperations() {
		if _, ok := covered[operation]; !ok {
			unreachable = append(unreachable, operation)
		}
	}
	sort.Strings(unreachable)

	if len(unreachable) > 0 {
		t.Fatalf("%d operation(s) are served but covered by no scope, so a scope-granting scenario cannot reach them: %v", len(unreachable), unreachable)
	}
}

// TestScopeOperationsAreKnown fails when a scope covers an operation outside the
// closed set.
//
// A scope that names an unknown operation grants nothing for it, so the scope
// silently covers less than it claims. The load-time warning reports the same
// defect for a policy file; this guard reports it for the built-in mapping, which
// no policy file can reveal.
func TestScopeOperationsAreKnown(t *testing.T) {
	known := make(map[string]struct{}, len(endpoint.KnownAccessOperations()))
	for _, operation := range endpoint.KnownAccessOperations() {
		known[operation] = struct{}{}
	}

	var unknown []string
	for scope, operations := range endpoint.ScopeOperations() {
		for _, operation := range operations {
			if _, ok := known[operation]; !ok {
				unknown = append(unknown, scope+" covers "+operation)
			}
		}
	}
	sort.Strings(unknown)

	if len(unknown) > 0 {
		t.Fatalf("%d scope entry(ies) name an operation outside the closed set: %v", len(unknown), unknown)
	}
}

// TestControlActionFamilyHasBothDirections fails when the provider control family
// loses one of its two scenarios.
//
// The ctl. family is a pattern rather than a closed-set member, so the guards
// above cannot see it. It is still a standard operation family with its own
// permission, so it needs the same two directions, and this guard is the only
// thing that notices if one is deleted.
func TestControlActionFamilyHasBothDirections(t *testing.T) {
	corpus := readPermissionMatrixCorpus(t)
	markers := []string{
		"the control action is accepted and the provider is invoked once",
		"the control action is refused with policy denied and the provider is not invoked",
	}
	for _, marker := range markers {
		if !strings.Contains(corpus, marker) {
			t.Fatalf("the provider control family lost a direction: %q appears in no feature file", marker)
		}
	}
	if !strings.Contains(corpus, security.ProviderControlPrefix) {
		t.Fatalf("the provider control family is not named in any feature file, so the ctl. prefix %q is unproven", security.ProviderControlPrefix)
	}
}

// readPermissionMatrixCorpus returns the concatenated text of every feature file
// the matrix owns.
//
// The files are concatenated because a marker may legitimately live in either
// file: the command matrix owns the command operations and the query matrix owns
// the reads, and the guard must not care which file a scenario was written in.
func readPermissionMatrixCorpus(t *testing.T) string {
	t.Helper()
	var builder strings.Builder
	for _, path := range permissionMatrixFeatureFiles {
		data, err := os.ReadFile(filepath.Clean(path))
		if err != nil {
			t.Fatalf("read feature file %q: %v", path, err)
		}
		builder.Write(data)
		builder.WriteString("\n")
	}
	return builder.String()
}
