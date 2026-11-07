package tui

import (
	"context"
	"errors"
	"io"
	"strings"
	"testing"

	"topsailai_agent_cluster/internal/protocol"
)

// launchEndpointStub supplies a multi-endpoint inventory for numbered selection.
type launchEndpointStub struct {
	*launchStub
	endpoints []protocol.Endpoint
	listErr   error
}

// ListEndpoints returns the detached endpoint inventory or the injected failure.
func (s *launchEndpointStub) ListEndpoints(context.Context) ([]protocol.Endpoint, error) {
	if s.listErr != nil {
		return nil, s.listErr
	}
	return s.endpoints, nil
}

// TestProjectLaunchEndpointNumberSelectsEndpoint proves a bare number replaces the identifier.
func TestProjectLaunchEndpointNumberSelectsEndpoint(t *testing.T) {
	stub := &launchEndpointStub{
		launchStub: &launchStub{interactiveStub: startupStub()},
		endpoints: []protocol.Endpoint{
			{EndpointID: "endpoint-1", Hostname: "ai-dev"},
			{EndpointID: "endpoint-2", Hostname: "ai-dev-2", DisplayName: "second"},
		},
	}
	lines, done, stop := startInputReader(strings.NewReader("2\n1\ndo work\n"), 8192)
	defer func() { stop(); done.Wait() }()
	var out strings.Builder
	if err := projectLaunch(context.Background(), stub, stub, &interactiveState{}, "", lines, &out, &out, InteractiveOptions{}); err != nil {
		t.Fatal(err)
	}
	if stub.admit != 1 || stub.calls != 2 {
		t.Fatalf("admit=%d calls=%d", stub.admit, stub.calls)
	}
	if len(stub.intents) != 1 || stub.intents[0].EndpointID != "endpoint-2" {
		t.Fatalf("intents=%#v", stub.intents)
	}
	text := out.String()
	if !strings.Contains(text, "1. ai-dev / endpoint-1 / endpoint-1") {
		t.Fatalf("missing first endpoint row: %q", text)
	}
	if !strings.Contains(text, "2. ai-dev-2 / endpoint-2 / second") {
		t.Fatalf("missing second endpoint row: %q", text)
	}
	if !strings.Contains(text, "Choose an endpoint number or enter an endpoint ID") {
		t.Fatalf("missing numbered prompt: %q", text)
	}
}

// TestProjectLaunchEndpointNumberRejectsOutOfRange proves a bad number never reaches the API.
func TestProjectLaunchEndpointNumberRejectsOutOfRange(t *testing.T) {
	stub := &launchEndpointStub{
		launchStub: &launchStub{interactiveStub: startupStub()},
		endpoints:  []protocol.Endpoint{{EndpointID: "endpoint-1", Hostname: "ai-dev"}},
	}
	lines, done, stop := startInputReader(strings.NewReader("9\n"), 8192)
	defer func() { stop(); done.Wait() }()
	err := projectLaunch(context.Background(), stub, stub, &interactiveState{}, "", lines, io.Discard, io.Discard, InteractiveOptions{})
	if err == nil || !strings.Contains(err.Error(), "endpoint number 9 is out of range; valid numbers are 1-1") {
		t.Fatalf("err=%v", err)
	}
	if stub.admit != 0 || stub.calls != 0 {
		t.Fatalf("admit=%d calls=%d", stub.admit, stub.calls)
	}
}

// TestProjectLaunchEndpointIdentifierStillAccepted proves the literal identifier path is unchanged.
func TestProjectLaunchEndpointIdentifierStillAccepted(t *testing.T) {
	stub := &launchEndpointStub{
		launchStub: &launchStub{interactiveStub: startupStub()},
		endpoints:  []protocol.Endpoint{{EndpointID: "endpoint-1", Hostname: "ai-dev"}},
	}
	lines, done, stop := startInputReader(strings.NewReader("endpoint-1\n1\ndo work\n"), 8192)
	defer func() { stop(); done.Wait() }()
	if err := projectLaunch(context.Background(), stub, stub, &interactiveState{}, "", lines, io.Discard, io.Discard, InteractiveOptions{}); err != nil {
		t.Fatal(err)
	}
	if stub.admit != 1 || len(stub.intents) != 1 || stub.intents[0].EndpointID != "endpoint-1" {
		t.Fatalf("admit=%d intents=%#v", stub.admit, stub.intents)
	}
}

// TestProjectLaunchEndpointListFailureKeepsIdentifierPath proves a failed inventory read degrades.
func TestProjectLaunchEndpointListFailureKeepsIdentifierPath(t *testing.T) {
	stub := &launchEndpointStub{
		launchStub: &launchStub{interactiveStub: startupStub()},
		listErr:    errors.New("inventory unavailable"),
	}
	lines, done, stop := startInputReader(strings.NewReader("endpoint-1\n1\ndo work\n"), 8192)
	defer func() { stop(); done.Wait() }()
	var out strings.Builder
	if err := projectLaunch(context.Background(), stub, stub, &interactiveState{}, "", lines, &out, &out, InteractiveOptions{}); err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(out.String(), "Endpoint list unavailable (inventory unavailable); enter an endpoint ID.") {
		t.Fatalf("missing fallback notice: %q", out.String())
	}
	if stub.admit != 1 || len(stub.intents) != 1 || stub.intents[0].EndpointID != "endpoint-1" {
		t.Fatalf("admit=%d intents=%#v", stub.admit, stub.intents)
	}
}

// TestProjectLaunchEndpointNumberWithoutListRejects proves a number needs a rendered list.
func TestProjectLaunchEndpointNumberWithoutListRejects(t *testing.T) {
	stub := &launchEndpointStub{
		launchStub: &launchStub{interactiveStub: startupStub()},
		listErr:    errors.New("inventory unavailable"),
	}
	lines, done, stop := startInputReader(strings.NewReader("1\n"), 8192)
	defer func() { stop(); done.Wait() }()
	err := projectLaunch(context.Background(), stub, stub, &interactiveState{}, "", lines, io.Discard, io.Discard, InteractiveOptions{})
	if err == nil || !strings.Contains(err.Error(), "endpoint list is unavailable; enter an endpoint ID") {
		t.Fatalf("err=%v", err)
	}
	if stub.admit != 0 || stub.calls != 0 {
		t.Fatalf("admit=%d calls=%d", stub.admit, stub.calls)
	}
}

// TestProjectLaunchEndpointScopeSkipsNumberedList proves an explicit scope needs no prompt.
func TestProjectLaunchEndpointScopeSkipsNumberedList(t *testing.T) {
	stub := &launchEndpointStub{
		launchStub: &launchStub{interactiveStub: startupStub()},
		endpoints:  []protocol.Endpoint{{EndpointID: "endpoint-1", Hostname: "ai-dev"}},
	}
	state := &interactiveState{}
	state.enterEndpoint(protocol.Endpoint{EndpointID: "endpoint-1", Hostname: "ai-dev"})
	lines, done, stop := startInputReader(strings.NewReader("1\ndo work\n"), 8192)
	defer func() { stop(); done.Wait() }()
	var out strings.Builder
	if err := projectLaunch(context.Background(), stub, stub, state, "", lines, &out, &out, InteractiveOptions{}); err != nil {
		t.Fatal(err)
	}
	if strings.Contains(out.String(), "Choose an endpoint number") {
		t.Fatalf("numbered list rendered inside endpoint scope: %q", out.String())
	}
	if stub.admit != 1 || len(stub.intents) != 1 || stub.intents[0].EndpointID != "endpoint-1" {
		t.Fatalf("admit=%d intents=%#v", stub.admit, stub.intents)
	}
}

// TestResolveLaunchEndpointAnswerKeepsLiteralValues proves non-numeric answers pass through.
func TestResolveLaunchEndpointAnswerKeepsLiteralValues(t *testing.T) {
	endpoints := []protocol.Endpoint{{EndpointID: "endpoint-1"}, {EndpointID: "endpoint-2"}}
	for _, item := range []struct {
		answer string
		want   string
	}{
		{answer: "1", want: "endpoint-1"},
		{answer: "2", want: "endpoint-2"},
		{answer: "endpoint-9", want: "endpoint-9"},
		{answer: "0", want: ""},
		{answer: "3", want: ""},
	} {
		got, err := resolveLaunchEndpointAnswer(endpoints, item.answer)
		if item.want == "" {
			if err == nil {
				t.Fatalf("answer %q accepted as %q", item.answer, got)
			}
			continue
		}
		if err != nil || got != item.want {
			t.Fatalf("answer %q got %q err=%v", item.answer, got, err)
		}
	}
}

// TestProjectLaunchEndpointHostnameResolvesToIdentifier proves the reported
// defect is fixed: the hostname shown in the endpoint table is accepted by
// `start <hostname>` and mapped to the routable endpoint identifier.
func TestProjectLaunchEndpointHostnameResolvesToIdentifier(t *testing.T) {
	stub := &launchEndpointStub{
		launchStub: &launchStub{interactiveStub: startupStub()},
		endpoints: []protocol.Endpoint{
			{EndpointID: "local-endpoint", Hostname: "topsail"},
			{EndpointID: "endpoint-2", Hostname: "ai-dev-2"},
		},
	}
	lines, done, stop := startInputReader(strings.NewReader("1\ndo work\n"), 8192)
	defer func() { stop(); done.Wait() }()
	if err := projectLaunch(context.Background(), stub, stub, &interactiveState{}, "topsail", lines, io.Discard, io.Discard, InteractiveOptions{}); err != nil {
		t.Fatal(err)
	}
	if stub.admit != 1 || len(stub.intents) != 1 || stub.intents[0].EndpointID != "local-endpoint" {
		t.Fatalf("admit=%d intents=%#v", stub.admit, stub.intents)
	}
}

// TestProjectLaunchEndpointArgumentNumberResolves proves the printed row number
// works as an argument, not only as a wizard answer.
func TestProjectLaunchEndpointArgumentNumberResolves(t *testing.T) {
	stub := &launchEndpointStub{
		launchStub: &launchStub{interactiveStub: startupStub()},
		endpoints: []protocol.Endpoint{
			{EndpointID: "endpoint-1", Hostname: "ai-dev"},
			{EndpointID: "endpoint-2", Hostname: "ai-dev-2"},
		},
	}
	lines, done, stop := startInputReader(strings.NewReader("1\ndo work\n"), 8192)
	defer func() { stop(); done.Wait() }()
	if err := projectLaunch(context.Background(), stub, stub, &interactiveState{}, "2", lines, io.Discard, io.Discard, InteractiveOptions{}); err != nil {
		t.Fatal(err)
	}
	if stub.admit != 1 || len(stub.intents) != 1 || stub.intents[0].EndpointID != "endpoint-2" {
		t.Fatalf("admit=%d intents=%#v", stub.admit, stub.intents)
	}
}

// TestProjectLaunchUnknownEndpointFailsLocally proves an unknown identifier is
// rejected before any launch query, so it cannot surface as an availability error.
func TestProjectLaunchUnknownEndpointFailsLocally(t *testing.T) {
	stub := &launchEndpointStub{
		launchStub: &launchStub{interactiveStub: startupStub()},
		endpoints:  []protocol.Endpoint{{EndpointID: "endpoint-1", Hostname: "ai-dev"}},
	}
	lines, done, stop := startInputReader(strings.NewReader(""), 8192)
	defer func() { stop(); done.Wait() }()
	err := projectLaunch(context.Background(), stub, stub, &interactiveState{}, "no-such-host", lines, io.Discard, io.Discard, InteractiveOptions{})
	if err == nil || !strings.Contains(err.Error(), `endpoint "no-such-host" was not found`) {
		t.Fatalf("err=%v", err)
	}
	var notSyntax nonSyntaxError
	if !errors.As(err, &notSyntax) {
		t.Fatalf("unknown endpoint must not be reported as a syntax error: %v", err)
	}
	if stub.admit != 0 || stub.calls != 0 {
		t.Fatalf("admit=%d calls=%d", stub.admit, stub.calls)
	}
}

// TestResolveLaunchEndpointValuePrefersExactIdentifier proves a numeric endpoint
// identifier is never reinterpreted as a row number.
func TestResolveLaunchEndpointValuePrefersExactIdentifier(t *testing.T) {
	endpoints := []protocol.Endpoint{
		{EndpointID: "endpoint-1", Hostname: "ai-dev"},
		{EndpointID: "7", Hostname: "numeric-id"},
	}
	got, err := resolveLaunchEndpointValue(endpoints, "7")
	if err != nil || got != "7" {
		t.Fatalf("got=%q err=%v", got, err)
	}
}

// TestResolveLaunchEndpointValueRejectsAmbiguousHostname proves a hostname shared
// by several endpoints is refused instead of silently picking one.
func TestResolveLaunchEndpointValueRejectsAmbiguousHostname(t *testing.T) {
	endpoints := []protocol.Endpoint{
		{EndpointID: "endpoint-1", Hostname: "shared"},
		{EndpointID: "endpoint-2", Hostname: "shared"},
	}
	_, err := resolveLaunchEndpointValue(endpoints, "shared")
	if err == nil || !strings.Contains(err.Error(), "matches 2 endpoints") {
		t.Fatalf("err=%v", err)
	}
}

// TestWriteInteractiveErrorOmitsUsageForNonSyntaxFailure proves the misleading
// usage line is gone when the command shape was already valid.
func TestWriteInteractiveErrorOmitsUsageForNonSyntaxFailure(t *testing.T) {
	var out strings.Builder
	err := nonSyntaxError{message: `endpoint "topsail" was not found`, next: "Run endpoints to list valid endpoint identifiers."}
	if writeErr := writeInteractiveError(&out, "start", err); writeErr != nil {
		t.Fatal(writeErr)
	}
	text := out.String()
	if strings.Contains(text, "usage:") {
		t.Fatalf("non-syntax failure printed a usage line: %q", text)
	}
	if !strings.Contains(text, `error: endpoint "topsail" was not found`) {
		t.Fatalf("cause missing: %q", text)
	}
	if !strings.Contains(text, "next: Run endpoints to list valid endpoint identifiers.") {
		t.Fatalf("remedy missing: %q", text)
	}
}

// TestResolveLaunchEndpointTargetForwardsIdentifierOnInventoryFailure proves the
// degraded path: when the inventory cannot be read, an explicit identifier is
// forwarded unchanged so an identifier-only caller keeps working, and a hostname
// is not silently rejected as unknown.
func TestResolveLaunchEndpointTargetForwardsIdentifierOnInventoryFailure(t *testing.T) {
	stub := &launchEndpointStub{
		launchStub: &launchStub{interactiveStub: startupStub()},
		listErr:    errors.New("inventory unavailable"),
	}
	got, err := resolveLaunchEndpointTarget(context.Background(), stub, "local-endpoint")
	if err != nil {
		t.Fatalf("err=%v", err)
	}
	if got != "local-endpoint" {
		t.Fatalf("got=%q", got)
	}
}

// TestResolveLaunchEndpointTargetResolvesHostname proves the target helper reads
// the inventory and maps a hostname onto the endpoint identifier.
func TestResolveLaunchEndpointTargetResolvesHostname(t *testing.T) {
	stub := &launchEndpointStub{
		launchStub: &launchStub{interactiveStub: startupStub()},
		endpoints: []protocol.Endpoint{
			{EndpointID: "local-endpoint", Hostname: "topsail"},
		},
	}
	got, err := resolveLaunchEndpointTarget(context.Background(), stub, "topsail")
	if err != nil {
		t.Fatalf("err=%v", err)
	}
	if got != "local-endpoint" {
		t.Fatalf("got=%q", got)
	}
}

// TestResolveLaunchEndpointTargetRejectsUnknownValue proves an unknown value is
// refused before any launch query is sent.
func TestResolveLaunchEndpointTargetRejectsUnknownValue(t *testing.T) {
	stub := &launchEndpointStub{
		launchStub: &launchStub{interactiveStub: startupStub()},
		endpoints: []protocol.Endpoint{
			{EndpointID: "local-endpoint", Hostname: "topsail"},
		},
	}
	_, err := resolveLaunchEndpointTarget(context.Background(), stub, "no-such-host")
	if err == nil || !strings.Contains(err.Error(), `endpoint "no-such-host" was not found`) {
		t.Fatalf("err=%v", err)
	}
	var notSyntax nonSyntaxError
	if !errors.As(err, &notSyntax) {
		t.Fatalf("unknown endpoint is not a non-syntax error: %v", err)
	}
}
