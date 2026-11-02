package tui

import (
	"strings"
	"testing"

	"topsailai_agent_cluster/internal/protocol"
)

func TestScopeKindString(t *testing.T) {
	tests := []struct {
		kind ScopeKind
		want string
	}{
		{kind: ScopeWorkspace, want: "workspace"},
		{kind: ScopeEndpoint, want: "endpoint"},
		{kind: ScopeSession, want: "session"},
		{kind: ScopeKind(99), want: "unknown"},
	}
	for _, test := range tests {
		if got := test.kind.String(); got != test.want {
			t.Errorf("ScopeKind(%d).String() = %q, want %q", test.kind, got, test.want)
		}
	}
}

func TestScopePromptUsesEndpointFallbackAndSuppressesColor(t *testing.T) {
	var colored, plain strings.Builder
	scope := ScopeState{Kind: ScopeEndpoint, EndpointID: "endpoint-1"}
	if err := RenderPrompt(&colored, scope, false, ColorPolicy{Enabled: true}); err != nil {
		t.Fatal(err)
	}
	if want := ansiBoldGreen + "cluster[endpoint-1]>" + ansiReset + " "; colored.String() != want {
		t.Fatalf("colored endpoint prompt = %q, want %q", colored.String(), want)
	}
	if err := RenderPrompt(&plain, scope, false, ColorPolicy{}); err != nil {
		t.Fatal(err)
	}
	if plain.String() != "cluster[endpoint-1]> " || strings.Contains(plain.String(), "\x1b") {
		t.Fatalf("plain endpoint prompt = %q", plain.String())
	}
}

func TestScopeStateFillsHostnameFromEndpoint(t *testing.T) {
	endpoint := protocol.Endpoint{EndpointID: "endpoint-1", Hostname: "ai-dev"}
	state := interactiveState{}
	state.enterEndpoint(endpoint)
	if state.Scope.Kind != ScopeEndpoint || state.Scope.EndpointID != "endpoint-1" || state.Scope.Hostname != "ai-dev" {
		t.Fatalf("endpoint scope was not filled: %+v", state.Scope)
	}
	state.enterSession(endpoint, "session-1", "generation-1")
	if state.Scope.Kind != ScopeSession || state.Scope.EndpointID != "endpoint-1" || state.Scope.Hostname != "ai-dev" || state.Scope.SessionID != "session-1" || state.Scope.Generation != "generation-1" {
		t.Fatalf("session scope was not filled: %+v", state.Scope)
	}
	state.enterWorkspace()
	if state.Scope.Kind != ScopeWorkspace || state.Scope.EndpointID != "" || state.Scope.SessionID != "" || state.Scope.Hostname != "" {
		t.Fatalf("scope was not cleared: %+v", state.Scope)
	}
}
