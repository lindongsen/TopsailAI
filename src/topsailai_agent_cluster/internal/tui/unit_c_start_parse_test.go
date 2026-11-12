package tui

import (
	"bytes"
	"context"
	"crypto/sha256"
	"fmt"
	"io"
	"reflect"
	"strings"
	"testing"
)

// TestUnitCStartDraftParserMissingFieldsInOrder verifies the exact parser or renderer contract.
func TestUnitCStartDraftParserMissingFieldsInOrder(t *testing.T) {
	tests := []struct {
		name string
		line string
		want [4]bool
	}{
		{"empty", "", [4]bool{true, true, true, true}},
		{"endpoint", "endpoint-1", [4]bool{false, true, true, true}},
		{"resource", "endpoint-1 resource-1", [4]bool{false, false, true, true}},
		{"profile", "endpoint-1 resource-1 --profile p", [4]bool{false, false, false, true}},
		{"complete", "endpoint-1 resource-1 --profile p --profile-revision r", [4]bool{false, false, false, false}},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			draft, err := parseInteractiveStartDraft(test.line)
			if err != nil {
				t.Fatalf("parseInteractiveStartDraft: %v", err)
			}
			if draft.missing != test.want {
				t.Fatalf("missing=%v, want %v", draft.missing, test.want)
			}
		})
	}
}

// TestUnitCStartDraftParserPreservesStrictFailures verifies the exact parser or renderer contract.
func TestUnitCStartDraftParserPreservesStrictFailures(t *testing.T) {
	for _, line := range []string{
		"endpoint resource --bogus",
		"endpoint resource --payload nope",
		"endpoint resource --folder",
		"endpoint resource extra",
		"endpoint resource --json",
	} {
		if _, err := parseInteractiveStartDraft(line); err == nil {
			t.Errorf("%q unexpectedly accepted", line)
		}
	}
}

// TestUnitCStartAnswerTreatsQuotedControlsAsValues verifies the exact parser or renderer contract.
func TestUnitCStartAnswerTreatsQuotedControlsAsValues(t *testing.T) {
	for _, line := range []string{"'q'", `"r"`, "'start'"} {
		value, err := parseStartAnswer(line)
		if err != nil || value != strings.Trim(line, "\"'") {
			t.Fatalf("parseStartAnswer(%q) = %q, %v", line, value, err)
		}
	}
}

// TestUnitCStartDraftMissingFieldMasks verifies the exact parser or renderer contract.
func TestUnitCStartDraftMissingFieldMasks(t *testing.T) {
	for mask := 0; mask < 16; mask++ {
		draft := startDraft{}
		for field := 0; field < len(draft.missing); field++ {
			draft.missing[field] = mask&(1<<field) != 0
		}
		field, ok := firstMissingField(draft)
		if mask == 0 {
			if ok {
				t.Fatalf("complete mask returned field %v", field)
			}
			continue
		}
		want := startDraftField(0)
		for !draft.missing[want] {
			want++
		}
		if !ok || field != want {
			t.Fatalf("mask %04b first field=%v,%t want=%v,true", mask, field, ok, want)
		}
	}
}

// TestUnitCStartDraftParserGrammarMatrix verifies the exact parser or renderer contract.
func TestUnitCStartDraftParserGrammarMatrix(t *testing.T) {
	cases := []struct {
		name        string
		line        string
		wantMissing [4]bool
		wantErr     bool
	}{
		{"start", "", [4]bool{true, true, true, true}, false},
		{"endpoint", "e", [4]bool{false, true, true, true}, false},
		{"endpoint-resource", "e r", [4]bool{false, false, true, true}, false},
		{"profile-only", "--profile p", [4]bool{true, true, false, true}, false},
		{"revision-only", "--profile-revision v", [4]bool{true, true, true, false}, false},
		{"unknown-option", "e r --unknown x", [4]bool{}, true},
		{"bad-quote", `e "unterminated`, [4]bool{}, true},
		{"json-option", "e r --json", [4]bool{}, true},
		{"rejected-payload", "e r --payload nope", [4]bool{}, true},
		{"missing-folder", "e r --folder", [4]bool{}, true},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			draft, err := parseInteractiveStartDraft(tc.line)
			if tc.wantErr {
				if err == nil {
					t.Fatalf("accepted invalid grammar: %q", tc.line)
				}
				return
			}
			if err != nil {
				t.Fatalf("parseInteractiveStartDraft(%q): %v", tc.line, err)
			}
			if draft.missing != tc.wantMissing {
				t.Fatalf("missing=%v, want %v", draft.missing, tc.wantMissing)
			}
		})
	}
}

// TestUnitCStartAnswerTokenizerBoundaries verifies the exact parser or renderer contract.
func TestUnitCStartAnswerTokenizerBoundaries(t *testing.T) {
	cases := []struct {
		line string
		want string
	}{
		{"1", "1"},
		{"001", "001"},
		{`"q"`, "q"},
		{`'start'`, "start"},
		{`"unicode-测试"`, "unicode-测试"},
		{`"path\\segment"`, `path\\segment`},
	}
	for _, tc := range cases {
		got, err := parseStartAnswer(tc.line)
		if err != nil || got != tc.want {
			t.Errorf("parseStartAnswer(%q)=%q,%v want %q", tc.line, got, err, tc.want)
		}
	}
}

// TestUnitCStartPromptRendererExactScopeBytes verifies the exact parser or renderer contract.
func TestUnitCStartPromptRendererExactScopeBytes(t *testing.T) {
	longEndpoint := "endpoint/with\\controls\n" + strings.Repeat("宽", 30)
	cases := []struct {
		name  string
		scope ScopeState
		bad   bool
		want  string
	}{
		{"workspace", ScopeState{Kind: ScopeWorkspace}, false, "workspace> "},
		{"endpoint-fallback", ScopeState{Kind: ScopeEndpoint, EndpointID: "ep-1"}, false, "endpoint[ep-1]> "},
		{"endpoint-host", ScopeState{Kind: ScopeEndpoint, Hostname: "host", EndpointID: "ep-1"}, false, "endpoint[host/ep-1]> "},
		{"session-default-provider", ScopeState{Kind: ScopeSession, EndpointID: "ep-1"}, false, "session[ep-1/-]> "},
		{"session-invalidated", ScopeState{Kind: ScopeSession, Hostname: "host", ProviderSessionID: "provider", EndpointID: "ep-1"}, true, "session[host/provider!]> "},
		{"sanitized-and-unclipped", ScopeState{Kind: ScopeEndpoint, Hostname: longEndpoint, EndpointID: "ep-1"}, false, "endpoint[endpoint∕with\\\\controls�宽宽宽宽宽宽宽宽宽宽宽宽宽宽宽宽宽宽宽宽宽宽宽宽宽宽宽宽宽宽/ep-1]> "},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			var output bytes.Buffer
			if err := RenderPrompt(&output, tc.scope, tc.bad, ColorPolicy{}); err != nil {
				t.Fatal(err)
			}
			if got := output.String(); got != tc.want {
				t.Fatalf("prompt bytes=%q, want %q", got, tc.want)
			}
		})
	}
}

// TestUnitCStartStandaloneHelpMatchesCurrentPreCContract pins outputs verified against pre-C 15ee593f.
// TestUnitCStartStandaloneHelpMatchesCurrentPreCContract verifies the exact parser or renderer contract.
func TestUnitCStartStandaloneHelpMatchesCurrentPreCContract(t *testing.T) {
	for _, tc := range []struct {
		target, digest string
		size           int
	}{
		{"", "905644ac79cd1dfee9f80f10aaf68f38303b80598e41fcff0b54cc3a9f6db3e9", 6645},
		{"list", "bda5f255d181309d9345ab9b7df75c7ecb86d06f44b70a647c2735e2668cec51", 3395},
		{"start", "73003792c52a940a6d9b840466b920295f45a8b1246db0573d0e5cc541bdb0da", 1781},
		{"btw", "0480dd649bbb307b08dd28468c5c5a95779df94dd2d88cc394024d434c98317c", 654},
		{"control", "687f9ba133d29a477be40b43b8a73628df8ed59cd6f85869e2d9091f24f516b7", 1119},
	} {
		var output bytes.Buffer
		if err := PrintCommandHelp(&output, tc.target); err != nil {
			t.Fatal(err)
		}
		if got := fmt.Sprintf("%x", sha256.Sum256(output.Bytes())); got != tc.digest || output.Len() != tc.size {
			t.Fatalf("standalone %q digest=%s size=%d want=%s/%d", tc.target, got, output.Len(), tc.digest, tc.size)
		}
	}
}

// TestUnitCStartAuthorityStateSnapshotCanBeComparedExactly invokes the real rejecting dispatcher.
// TestUnitCStartAuthorityStateSnapshotCanBeComparedExactly verifies the exact parser or renderer contract.
func TestUnitCStartAuthorityStateSnapshotCanBeComparedExactly(t *testing.T) {
	state := seedUnitCState()
	state.Scope.Kind = ScopeSession
	before := cloneUnitCState(state)
	api := newUnitCAPI()
	var out, diag bytes.Buffer
	exit, err := executeInteractiveLine(context.Background(), api, &state, "start", make(chan lineReadResult), &out, io.Discard, &diag, InteractiveOptions{})
	if exit || err == nil || !strings.Contains(err.Error(), "session") || !reflect.DeepEqual(state, before) || out.Len() != 0 || diag.Len() != 0 {
		t.Fatalf("authority rejection exit=%v err=%v stateEqual=%v output=%q diag=%q", exit, err, reflect.DeepEqual(state, before), out.String(), diag.String())
	}
	assertNoAPIActivity(t, api)
}

// TestUnitCStartDraftParserRejectsExplicitMalformedPositions verifies the exact parser or renderer contract.
func TestUnitCStartDraftParserRejectsExplicitMalformedPositions(t *testing.T) {
	for _, line := range []string{
		"'' r --profile p --profile-revision v",
		"e '' --profile p --profile-revision v",
		"-e r --profile p --profile-revision v",
	} {
		t.Run(line, func(t *testing.T) {
			if _, err := parseInteractiveStartDraft(line); err == nil {
				t.Fatalf("parseInteractiveStartDraft(%q) accepted malformed positional value", line)
			}
		})
	}
}
