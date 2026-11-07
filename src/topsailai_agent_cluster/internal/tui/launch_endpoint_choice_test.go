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
