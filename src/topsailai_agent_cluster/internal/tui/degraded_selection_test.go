package tui

import (
	"context"
	"errors"
	"io"
	"strings"
	"testing"

	"topsailai_agent_cluster/internal/protocol"
)

// degradedSelectionExpiresAtMS is the deletion deadline the selection fixtures
// report. It is a fixed value so an assertion can compare against the same
// formatter the refusal message uses.
const degradedSelectionExpiresAtMS int64 = 1797000000000

// degradedSelectionEndpoint builds one endpoint record in the given state. Only a
// degraded endpoint carries a deadline, because a live endpoint has no scheduled
// deletion.
func degradedSelectionEndpoint(id, hostname, state string) protocol.Endpoint {
	endpoint := protocol.Endpoint{EndpointID: id, Hostname: hostname, ConnectionState: state}
	if state == "degraded" {
		endpoint.ExpiresAtMS = degradedSelectionExpiresAtMS
	}
	return endpoint
}

// requireDegradedSelectionRefusal asserts the error names the degraded state and
// the deletion date, so the operator learns which of the two disconnected
// situations they are in.
func requireDegradedSelectionRefusal(t *testing.T, err error) {
	t.Helper()
	if err == nil {
		t.Fatal("selection of a degraded endpoint unexpectedly succeeded")
	}
	message := err.Error()
	if !strings.Contains(message, "degraded") {
		t.Fatalf("error=%q, want the degraded state named", message)
	}
	if want := formatDateTime(degradedSelectionExpiresAtMS, nil); !strings.Contains(message, want) {
		t.Fatalf("error=%q, want the deletion date %q", message, want)
	}
}

// TestStartWizardOffersOnlyOnlineEndpoints proves the numbered endpoint list the
// start wizard prints never offers a machine the launch query cannot reach.
//
// The list is asserted rather than only the selection, because the wizard exists
// to be chosen from: offering a row that is refused afterwards makes the operator
// pick a machine that cannot work. The offline and degraded identifiers are
// asserted absent by name, because a row is identified by its identifier in the
// printed label.
func TestStartWizardOffersOnlyOnlineEndpoints(t *testing.T) {
	stub := &launchEndpointStub{
		launchStub: &launchStub{interactiveStub: startupStub()},
		endpoints: []protocol.Endpoint{
			degradedSelectionEndpoint("deg-ep", "host-deg", "degraded"),
			degradedSelectionEndpoint("off-ep", "host-off", "offline"),
			degradedSelectionEndpoint("live-ep", "host-live", "online"),
		},
	}
	lines, done, stop := startInputReader(strings.NewReader("cancel\n"), 8192)
	defer func() { stop(); done.Wait() }()
	var out strings.Builder
	if err := projectLaunch(context.Background(), stub, stub, &interactiveState{}, "", lines, &out, io.Discard, InteractiveOptions{}); err != nil {
		t.Fatalf("projectLaunch: %v", err)
	}
	text := out.String()
	if strings.Contains(text, "deg-ep") {
		t.Fatalf("start wizard offered a degraded endpoint: %q", text)
	}
	if strings.Contains(text, "off-ep") {
		t.Fatalf("start wizard offered an offline endpoint: %q", text)
	}
	if !strings.Contains(text, "1. host-live / live-ep / live-ep") {
		t.Fatalf("start wizard did not offer the online endpoint as row 1: %q", text)
	}
}

// TestStartNumberCannotSelectAnUnlistedEndpoint proves a bare number resolves
// against the list the wizard printed, not against every record.
//
// Resolving against every record would make the same number mean two different
// machines: the wizard would print "1. live-ep" while "start 1" selected an
// offline endpoint that was never shown. The assertion is on the admitted intent,
// because that is the machine the command actually reaches.
func TestStartNumberCannotSelectAnUnlistedEndpoint(t *testing.T) {
	stub := &launchEndpointStub{
		launchStub: &launchStub{interactiveStub: startupStub()},
		endpoints: []protocol.Endpoint{
			degradedSelectionEndpoint("off-ep", "host-off", "offline"),
			degradedSelectionEndpoint("live-ep", "host-live", "online"),
		},
	}
	lines, done, stop := startInputReader(strings.NewReader("1\ndo work\n"), 8192)
	defer func() { stop(); done.Wait() }()
	if err := projectLaunch(context.Background(), stub, stub, &interactiveState{}, "1", lines, io.Discard, io.Discard, InteractiveOptions{}); err != nil {
		t.Fatalf("projectLaunch: %v", err)
	}
	if len(stub.intents) != 1 {
		t.Fatalf("intents=%#v, want exactly one admitted command", stub.intents)
	}
	if got := stub.intents[0].EndpointID; got != "live-ep" {
		t.Fatalf("start 1 selected %q, want the only listed endpoint live-ep", got)
	}
}

// TestStartNamedDegradedEndpointReportsItsState proves a degraded endpoint named
// explicitly is refused with its real state instead of being described as absent.
//
// The record still exists, so "was not found" would tell the operator the machine
// is gone when it is only scheduled for deletion. The refusal must also name the
// deletion date, because that date is the only fact that distinguishes a degraded
// endpoint from a merely offline one.
func TestStartNamedDegradedEndpointReportsItsState(t *testing.T) {
	stub := &launchEndpointStub{
		launchStub: &launchStub{interactiveStub: startupStub()},
		endpoints: []protocol.Endpoint{
			degradedSelectionEndpoint("deg-ep", "host-deg", "degraded"),
			degradedSelectionEndpoint("live-ep", "host-live", "online"),
		},
	}
	lines, done, stop := startInputReader(strings.NewReader(""), 8192)
	defer func() { stop(); done.Wait() }()
	err := projectLaunch(context.Background(), stub, stub, &interactiveState{}, "host-deg", lines, io.Discard, io.Discard, InteractiveOptions{})
	requireDegradedSelectionRefusal(t, err)
	if strings.Contains(err.Error(), "was not found") {
		t.Fatalf("error=%q, want the degraded state rather than absence", err.Error())
	}
	if stub.admit != 0 {
		t.Fatalf("degraded endpoint admitted %d commands", stub.admit)
	}
}

// TestCDRefusesDegradedEndpointByName proves navigation refuses a degraded
// endpoint named by identifier.
//
// Entering the scope would be a dead end: the inventory is deleted by design, so
// every command inside it is refused. The refusal is asserted through the
// diagnostic stream, because a silent scope change would leave the operator
// believing the navigation succeeded.
func TestCDRefusesDegradedEndpointByName(t *testing.T) {
	stub := scopeStub()
	stub.endpoints[1] = degradedSelectionEndpoint("endpoint-2", "host-two", "degraded")
	delete(stub.reports, "endpoint-2")

	_, diagnostics := runScope(t, stub, "cd endpoint-2\nexit\n", ColorPolicy{})
	requireDegradedSelectionRefusal(t, errors.New(strings.TrimSpace(diagnostics)))
	if !strings.Contains(diagnostics, "degraded") {
		t.Fatalf("cd of a degraded endpoint reported %q, want the degraded state", diagnostics)
	}
}

// TestCDStillEntersOfflineEndpoint proves the degraded refusal does not widen into
// a refusal of every disconnected endpoint.
//
// Navigation sends no frame to the machine, so an offline endpoint stays
// enterable: its retained inventory is still readable and is often exactly what
// the operator wants to inspect. Without this control the degraded refusal could
// be satisfied by refusing everything that is not online, which would remove a
// capability the operator relies on.
func TestCDStillEntersOfflineEndpoint(t *testing.T) {
	stub := scopeStub()
	stub.endpoints[1] = degradedSelectionEndpoint("endpoint-2", "host-two", "offline")

	output, diagnostics := runScope(t, stub, "cd endpoint-2\nexit\n", ColorPolicy{})
	if diagnostics != "" {
		t.Fatalf("cd of an offline endpoint reported %q, want it to enter", diagnostics)
	}
	if !strings.Contains(output, "endpoint-2") {
		t.Fatalf("cd of an offline endpoint did not render its scope: %q", output)
	}
}

// TestCDHostnameSharedWithDegradedEndpointResolvesToTheOnlineOne proves a hostname
// conflict is decided after the degraded candidates are dropped.
//
// Asking the operator to choose between a usable row and an unusable one would
// present a choice where only one answer can work. Dropping the degraded candidate
// before the count is decided makes the hostname resolve to the machine that can
// actually be used.
func TestCDHostnameSharedWithDegradedEndpointResolvesToTheOnlineOne(t *testing.T) {
	stub := scopeStub()
	stub.endpoints[1] = degradedSelectionEndpoint("endpoint-2", "host-one", "degraded")
	delete(stub.reports, "endpoint-2")

	output, diagnostics := runScope(t, stub, "cd host-one\nexit\n", ColorPolicy{})
	if diagnostics != "" {
		t.Fatalf("cd of a shared hostname reported %q, want it to resolve", diagnostics)
	}
	if strings.Contains(output, "multiple endpoints match") {
		t.Fatalf("cd asked the operator to choose a degraded endpoint: %q", output)
	}
	if !strings.Contains(output, "endpoint-1") {
		t.Fatalf("cd did not enter the online endpoint: %q", output)
	}
}

// soleDegradedEndpointStub serves one degraded endpoint and fails every endpoint
// listing after the first.
//
// The second listing is the read the shared queryable gate performs. Failing it
// reproduces the window the gate deliberately fails open on, which is the only
// situation where refusing inside the resolver changes the outcome.
type soleDegradedEndpointStub struct {
	*degradedGateStub
	listCalls int
}

// ListEndpoints returns the degraded record once and then fails, so the gate
// cannot re-read the state it is meant to check.
func (s *soleDegradedEndpointStub) ListEndpoints(context.Context) ([]protocol.Endpoint, error) {
	s.listCalls++
	if s.listCalls > 1 {
		return nil, errors.New("temporary list failure")
	}
	return s.degradedGateStub.endpoints, nil
}

// TestMessagesSoleDegradedEndpointRefusedWithoutASecondRead proves the sole-endpoint
// fallback refuses a degraded machine at the point where its state is already known.
//
// The shared gate re-reads the endpoint list and fails open when that read fails, so
// a fallback that returned the degraded endpoint would let the conversation read
// reach the machine. Asserting the read count rather than only the message is what
// distinguishes a refusal from a refusal that happened after the frame was sent.
func TestMessagesSoleDegradedEndpointRefusedWithoutASecondRead(t *testing.T) {
	stub := &soleDegradedEndpointStub{degradedGateStub: &degradedGateStub{interactiveStub: &interactiveStub{
		endpoints: []protocol.Endpoint{degradedSelectionEndpoint("deg-ep", "host-deg", "degraded")},
		reports:   map[string]protocol.InventoryReport{},
	}}}
	err := interactiveMessages(context.Background(), stub, &interactiveState{}, "provider-unknown", &strings.Builder{}, &strings.Builder{}, ColorPolicy{})
	requireDegradedSelectionRefusal(t, err)
	if stub.messagesCalls != 0 {
		t.Fatalf("degraded endpoint still received a conversation read: calls=%d", stub.messagesCalls)
	}
}

// degradedFanOutStub serves one online endpoint with a report and one degraded
// endpoint whose inventory is gone, which is the state degradation leaves behind.
func degradedFanOutStub() *interactiveStub {
	return &interactiveStub{
		endpoints: []protocol.Endpoint{
			degradedSelectionEndpoint("endpoint-1", "host-one", "online"),
			degradedSelectionEndpoint("deg-ep", "host-deg", "degraded"),
		},
		reports: map[string]protocol.InventoryReport{
			"endpoint-1": scopeInventory("res-1", "generation-1"),
		},
	}
}

// TestStopFanOutReportsDegradedStateNotMissingInventory proves a workspace-scope
// session search names the degraded endpoint's known state.
//
// A degraded endpoint's inventory is removed by design, so reporting it as an
// inventory that failed to answer describes a known state as an unknown fault and
// hides the only recovery step. The assertion rejects the inventory wording
// explicitly, because that wording is what the defect produced.
func TestStopFanOutReportsDegradedStateNotMissingInventory(t *testing.T) {
	stub := degradedFanOutStub()
	_, diagnostics := runScope(t, stub, "stop res-missing\nexit\n", ColorPolicy{})
	if !strings.Contains(diagnostics, "degraded") {
		t.Fatalf("stop reported %q, want the degraded state named", diagnostics)
	}
	if strings.Contains(diagnostics, "inventory is unavailable") || strings.Contains(diagnostics, "inventories are unavailable") {
		t.Fatalf("stop reported a known state as a failed inventory read: %q", diagnostics)
	}
	if stub.admit != 0 {
		t.Fatalf("degraded fan-out admitted %d commands", stub.admit)
	}
}

// TestCleanFanOutReportsDegradedStateNotMissingInventory proves the cleanup search
// reports the same known state as the stop search.
//
// Cleanup is destructive, so a misleading diagnostic is worse here than elsewhere:
// an operator told the inventory is unavailable would retry a read that cannot
// succeed instead of re-registering the endpoint.
func TestCleanFanOutReportsDegradedStateNotMissingInventory(t *testing.T) {
	stub := cleanInteractiveStub{interactiveStub: degradedFanOutStub()}
	_, diagnostics := runScope(t, stub, "clean res-missing\nexit\n", ColorPolicy{})
	if !strings.Contains(diagnostics, "degraded") {
		t.Fatalf("clean reported %q, want the degraded state named", diagnostics)
	}
	if strings.Contains(diagnostics, "inventory is unavailable") || strings.Contains(diagnostics, "inventories are unavailable") {
		t.Fatalf("clean reported a known state as a failed inventory read: %q", diagnostics)
	}
	if stub.admit != 0 {
		t.Fatalf("degraded fan-out admitted %d commands", stub.admit)
	}
}

// TestCDPairRefusesDegradedEndpoint proves the two-part path refuses a degraded
// endpoint before it enters the scope.
//
// The pair path resolves the endpoint from the hostname and identifier together, so
// it never passes through the single-target resolver. A gate placed only there
// would leave this path able to enter a scope whose inventory no longer exists.
func TestCDPairRefusesDegradedEndpoint(t *testing.T) {
	stub := scopeStub()
	stub.endpoints[1] = degradedSelectionEndpoint("endpoint-2", "host-two", "degraded")
	delete(stub.reports, "endpoint-2")

	_, diagnostics := runScope(t, stub, "cd host-two/endpoint-2\nexit\n", ColorPolicy{})
	if !strings.Contains(diagnostics, "degraded") {
		t.Fatalf("cd pair of a degraded endpoint reported %q, want the degraded state", diagnostics)
	}
	if want := formatDateTime(degradedSelectionExpiresAtMS, nil); !strings.Contains(diagnostics, want) {
		t.Fatalf("cd pair reported %q, want the deletion date %q", diagnostics, want)
	}
}

// TestCDTripleRefusesDegradedEndpoint proves the three-part path refuses a degraded
// endpoint before it resolves a session inside it.
//
// The triple path is the most specific form, so it is the one an operator reaches
// for after reading a row from an older list. Refusing it is what keeps a stale row
// from entering a scope that cannot answer.
func TestCDTripleRefusesDegradedEndpoint(t *testing.T) {
	stub := scopeStub()
	stub.endpoints[1] = degradedSelectionEndpoint("endpoint-2", "host-two", "degraded")
	delete(stub.reports, "endpoint-2")

	_, diagnostics := runScope(t, stub, "cd host-two/endpoint-2/res-2\nexit\n", ColorPolicy{})
	if !strings.Contains(diagnostics, "degraded") {
		t.Fatalf("cd triple of a degraded endpoint reported %q, want the degraded state", diagnostics)
	}
	if want := formatDateTime(degradedSelectionExpiresAtMS, nil); !strings.Contains(diagnostics, want) {
		t.Fatalf("cd triple reported %q, want the deletion date %q", diagnostics, want)
	}
}
