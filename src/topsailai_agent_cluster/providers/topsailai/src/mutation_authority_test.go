package main

import (
	"context"
	"strings"
	"testing"
)

// TestWorkspaceAuthorityResolvesOneExactRow proves the authority read matches the
// provider key rather than a position, a PID or a display name.
func TestWorkspaceAuthorityResolvesOneExactRow(t *testing.T) {
	target := liveSessionTarget(t, "7")
	document := `{"items":[{"session_id":"s-1","filename":"other","pid":42,"process_generation":9},{"session_id":"s-1","filename":"row","pid":99,"process_generation":7}]}`
	runner := &scriptedRunner{t: t, answers: map[string][]runnerAnswer{authorityCall: answer(document)}}
	resolved, generation, err := fixedProvider(runner).workspaceAuthority(context.Background(), target)
	if err != nil {
		t.Fatalf("authority: %v", err)
	}
	if generation != "7" || resolved.PID != 99 || resolved.ProviderRowKey != "row" {
		t.Fatalf("resolved=%+v generation=%q", resolved, generation)
	}
	if len(runner.calls) != 1 {
		t.Fatalf("calls=%v", runner.calls)
	}
}

// TestWorkspaceAuthorityRejectsAmbiguousAndMissingRows proves an ambiguous selector is
// never resolved by picking one candidate.
func TestWorkspaceAuthorityRejectsAmbiguousAndMissingRows(t *testing.T) {
	tests := map[string]string{
		"missing":   `{"items":[]}`,
		"duplicate": `{"items":[{"session_id":"s-1","filename":"row","pid":42},{"session_id":"s-1","filename":"row","pid":42}]}`,
		"no items":  `{}`,
	}
	for name, document := range tests {
		t.Run(name, func(t *testing.T) {
			runner := &scriptedRunner{t: t, answers: map[string][]runnerAnswer{authorityCall: answer(document)}}
			if _, _, err := fixedProvider(runner).workspaceAuthority(context.Background(), liveSessionTarget(t, "7")); err == nil {
				t.Fatal("ambiguous authority was accepted")
			}
		})
	}
}

// TestWorkspaceAuthorityRejectsUnreadableGeneration proves a generation that is
// neither an integer nor a string is a rejection rather than an empty value.
func TestWorkspaceAuthorityRejectsUnreadableGeneration(t *testing.T) {
	document := `{"items":[{"session_id":"s-1","filename":"row","pid":42,"process_generation":{"nested":true}}]}`
	runner := &scriptedRunner{t: t, answers: map[string][]runnerAnswer{authorityCall: answer(document)}}
	if _, _, err := fixedProvider(runner).workspaceAuthority(context.Background(), liveSessionTarget(t, "7")); err == nil {
		t.Fatal("unreadable generation was accepted")
	}
}

// TestRequireLiveGenerationComparesTheRequestedValue proves the comparison is the
// operation-sensitive rule itself, not a mere presence check.
func TestRequireLiveGenerationComparesTheRequestedValue(t *testing.T) {
	tests := []struct {
		name      string
		document  string
		requested string
		wantErr   string
	}{
		{name: "match", document: liveWorkspaceDocument("7"), requested: "7"},
		{name: "stale", document: liveWorkspaceDocument("8"), requested: "7", wantErr: "target generation changed"},
		{name: "unverified", document: dormantWorkspaceDocument(), requested: "7", wantErr: "target liveness is unverified"},
		{name: "string generation", document: `{"items":[{"session_id":"s-1","filename":"row","pid":42,"process_generation":"gen-7"}]}`, requested: "gen-7"},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			runner := &scriptedRunner{t: t, answers: map[string][]runnerAnswer{authorityCall: answer(test.document)}}
			target := liveSessionTarget(t, test.requested)
			_, err := fixedProvider(runner).requireLiveGeneration(context.Background(), target)
			if test.wantErr == "" {
				if err != nil {
					t.Fatalf("unexpected error: %v", err)
				}
				return
			}
			if err == nil || !strings.Contains(err.Error(), test.wantErr) {
				t.Fatalf("error=%v want %q", err, test.wantErr)
			}
		})
	}
}

// TestRequireNonLiveRecordIgnoresGeneration proves a record-addressed operation does
// not demand a live process, which is what makes resume and drive stop reachable.
func TestRequireNonLiveRecordIgnoresGeneration(t *testing.T) {
	runner := &scriptedRunner{t: t, answers: map[string][]runnerAnswer{authorityCall: answer(dormantWorkspaceDocument())}}
	resolved, err := fixedProvider(runner).requireNonLiveRecord(context.Background(), sessionTarget(t))
	if err != nil {
		t.Fatalf("authority: %v", err)
	}
	if resolved.SessionID != "s-1" || resolved.PID != 42 {
		t.Fatalf("resolved=%+v", resolved)
	}
}

// TestRequireResumableRecordRejectsLiveTarget proves resume refuses a session that is
// already running, because that would start a second process for one record.
func TestRequireResumableRecordRejectsLiveTarget(t *testing.T) {
	runner := &scriptedRunner{t: t, answers: map[string][]runnerAnswer{authorityCall: answer(liveWorkspaceDocument("7"))}}
	_, err := fixedProvider(runner).requireResumableRecord(context.Background(), sessionTarget(t))
	if err == nil || !strings.Contains(err.Error(), "already live") {
		t.Fatalf("error=%v", err)
	}
	runner = &scriptedRunner{t: t, answers: map[string][]runnerAnswer{authorityCall: answer(dormantWorkspaceDocument())}}
	if _, err := fixedProvider(runner).requireResumableRecord(context.Background(), sessionTarget(t)); err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
}

// TestRequireLaunchProfilePinsIdentityAndRevision proves a launch profile is
// authorized by its frozen identity and revision, not by a process generation.
func TestRequireLaunchProfilePinsIdentityAndRevision(t *testing.T) {
	tests := []struct {
		name    string
		target  *target
		wantErr string
	}{
		{name: "frozen", target: launchProfileTarget(launchProfileRevision)},
		{name: "wrong kind", target: &target{ResourceKind: resourceSession, ProviderResourceKey: launchProfileKey, ExpectedGeneration: launchProfileRevision}, wantErr: "launch profile target is required"},
		{name: "unknown key", target: &target{ResourceKind: resourceLaunchProfile, ProviderResourceKey: "other", ExpectedGeneration: launchProfileRevision}, wantErr: "unknown launch profile"},
		{name: "stale revision", target: launchProfileTarget("topsailai-launch-v0"), wantErr: "launch profile revision changed"},
		{name: "missing revision", target: launchProfileTarget(""), wantErr: "launch profile revision changed"},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			err := fixedProvider(&scriptedRunner{t: t, answers: map[string][]runnerAnswer{}}).requireLaunchProfile(test.target)
			if test.wantErr == "" {
				if err != nil {
					t.Fatalf("unexpected error: %v", err)
				}
				return
			}
			if err == nil || !strings.Contains(err.Error(), test.wantErr) {
				t.Fatalf("error=%v want %q", err, test.wantErr)
			}
		})
	}
}

// TestWorkspaceAuthorityRejectsNonSessionTarget proves the authority read refuses a
// target that is not a provider session key before it reads anything.
func TestWorkspaceAuthorityRejectsNonSessionTarget(t *testing.T) {
	for name, target := range map[string]*target{
		"nil":    nil,
		"kind":   {ResourceKind: resourceLaunchProfile, ProviderResourceKey: launchProfileKey},
		"prefix": {ResourceKind: resourceSession, ProviderResourceKey: "not-a-session-key"},
		"empty":  {ResourceKind: resourceSession},
	} {
		t.Run(name, func(t *testing.T) {
			runner := &scriptedRunner{t: t, answers: map[string][]runnerAnswer{}}
			if _, _, err := fixedProvider(runner).workspaceAuthority(context.Background(), target); err == nil {
				t.Fatal("invalid target was accepted")
			}
			if len(runner.calls) != 0 {
				t.Fatalf("calls=%v", runner.calls)
			}
		})
	}
}

// TestWorkspaceAuthorityScopesTheGenerationReadFromTheProviderTarget proves the
// exact slot removes a global workspace scan without replacing generation proof.
func TestWorkspaceAuthorityScopesTheGenerationReadFromTheProviderTarget(t *testing.T) {
	target := liveSessionTarget(t, "7")
	slot, err := encodeProviderTarget(providerSessionTarget{SessionID: "s-1", ProviderRowKey: "row", PID: 42})
	if err != nil {
		t.Fatal(err)
	}
	target.ProviderTarget = slot
	key := "workspace\x00list\x00--json\x00--local\x00-s\x00s-1"
	runner := &scriptedRunner{t: t, answers: map[string][]runnerAnswer{key: answer(liveWorkspaceDocument("7"))}}
	resolved, err := fixedProvider(runner).requireLiveGeneration(context.Background(), target)
	if err != nil {
		t.Fatalf("authority: %v", err)
	}
	if resolved.SessionID != "s-1" || resolved.PID != 42 {
		t.Fatalf("resolved=%+v", resolved)
	}
	if len(runner.calls) != 1 || strings.Join(runner.calls[0].args, "\x00") != key {
		t.Fatalf("calls=%v", runner.calls)
	}
}
