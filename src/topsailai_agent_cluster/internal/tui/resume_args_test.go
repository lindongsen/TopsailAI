package tui

import (
	"context"
	"strings"
	"testing"
)

// TestParseResumeArgsAcceptsSessionFlag proves the -s form parses. Without it the
// interactive surface rejected the flag before any resolution ran, so the operator
// could not name a session at all.
func TestParseResumeArgsAcceptsSessionFlag(t *testing.T) {
	cases := map[string]string{
		"-s wa-1":        "wa-1",
		"--session wa-1": "wa-1",
		"--session=wa-1": "wa-1",
		"  -s   wa-1  ":  "wa-1",
	}
	for input, want := range cases {
		parsed, err := parseResumeArgs(input)
		if err != nil {
			t.Fatalf("%q: unexpected error %v", input, err)
		}
		if parsed.Handle != want {
			t.Fatalf("%q: handle = %q, want %q", input, parsed.Handle, want)
		}
		if parsed.Token != "" {
			t.Fatalf("%q: token = %q, want empty", input, parsed.Token)
		}
	}
}

// TestParseResumeArgsKeepsRowForm proves the existing row-number and bare forms are
// unchanged, so the new flag cannot silently reinterpret an old invocation.
func TestParseResumeArgsKeepsRowForm(t *testing.T) {
	parsed, err := parseResumeArgs("3")
	if err != nil {
		t.Fatal(err)
	}
	if parsed.Token != "3" || parsed.Handle != "" {
		t.Fatalf("parsed = %+v, want token 3 and no handle", parsed)
	}
	bare, err := parseResumeArgs("")
	if err != nil {
		t.Fatal(err)
	}
	if bare.Token != "" || bare.Handle != "" {
		t.Fatalf("bare form = %+v, want both empty", bare)
	}
}

// TestParseResumeArgsRejectsAmbiguousAndUnknownInput proves a typo cannot silently
// resume a different session, and that naming one target two ways is refused
// instead of resolved by precedence.
func TestParseResumeArgsRejectsAmbiguousAndUnknownInput(t *testing.T) {
	for _, input := range []string{"-s", "--session", "-s wa-1 3", "-s wa-1 -s wa-2", "--force wa-1", "-x", "1 2", "--session="} {
		if _, err := parseResumeArgs(input); err == nil {
			t.Fatalf("%q must be rejected", input)
		}
	}
}

// TestResolveResumeArgsHandleNeedsEndpointScope proves the flag is refused outside
// endpoint scope with an actionable message. A handle names a session on one
// machine, so accepting it in workspace or session scope would leave the client
// guessing which endpoint to address.
func TestResolveResumeArgsHandleNeedsEndpointScope(t *testing.T) {
	for _, kind := range []ScopeKind{ScopeWorkspace, ScopeSession} {
		state := &interactiveState{Scope: ScopeState{Kind: kind, EndpointID: "endpoint-1"}}
		_, err := resolveResumeArgs(context.Background(), nil, state, resumeArgs{Handle: "wa-1"})
		if err == nil {
			t.Fatalf("scope %v must be refused", kind)
		}
		if !strings.Contains(err.Error(), "endpoint scope") {
			t.Fatalf("scope %v: error %q must name the required scope", kind, err)
		}
	}
}

// TestResolveResumeArgsHandlePerformsNoLookup proves the client does not judge the
// session. The API is nil on purpose: any lookup would panic, so a passing test is
// evidence that resolution is purely local. This is the operator's explicit
// requirement, not an optimisation.
func TestResolveResumeArgsHandlePerformsNoLookup(t *testing.T) {
	state := &interactiveState{Scope: ScopeState{Kind: ScopeEndpoint, EndpointID: "endpoint-1"}}
	selection, err := resolveResumeArgs(context.Background(), nil, state, resumeArgs{Handle: "wa-unknown"})
	if err != nil {
		t.Fatalf("an unknown handle must not be rejected by the client: %v", err)
	}
	if selection.Handle != "wa-unknown" {
		t.Fatalf("handle = %q, want wa-unknown", selection.Handle)
	}
	if selection.EndpointID != "endpoint-1" {
		t.Fatalf("endpoint = %q, want endpoint-1", selection.EndpointID)
	}
	if selection.Source != resumeSourceHandle {
		t.Fatalf("source = %q, want %q", selection.Source, resumeSourceHandle)
	}
	if selection.ResourceID != "" {
		t.Fatalf("resource ID = %q, want empty because the Endpoint mints it", selection.ResourceID)
	}
}

// TestResumeHandleSkipsAbsenceRecheck proves the handle form does not run the
// absence recheck. That recheck reads the inventory, which has no entry for a
// session the Endpoint never discovered, so running it would reject exactly the
// target the operator named.
func TestResumeHandleSkipsAbsenceRecheck(t *testing.T) {
	if resumeNeedsAbsenceRecheck(resumeSourceHandle) {
		t.Fatal("the handle form must skip the absence recheck")
	}
	if resumeNeedsAbsenceRecheck(resumeSourceSessionID) {
		t.Fatal("the named-session form must skip the absence recheck")
	}
	if !resumeNeedsAbsenceRecheck(resumeSourceList) {
		t.Fatal("a list row must still recheck absence")
	}
	if !resumeNeedsAbsenceRecheck(resumeSourceHistory) {
		t.Fatal("a history row must still recheck absence")
	}
}
