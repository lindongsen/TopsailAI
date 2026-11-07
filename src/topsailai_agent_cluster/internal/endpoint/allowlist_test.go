package endpoint

import (
	"strings"
	"testing"
)

func TestParseAllowlistRejectsEmptyDocument(t *testing.T) {
	if _, err := ParseAllowlist([]byte("\n# only a comment\n\n")); err == nil {
		t.Fatalf("empty allowlist must be rejected so a truncated file cannot disable every command")
	}
}

func TestParseAllowlistAcceptsExplicitEmptyDirective(t *testing.T) {
	entries, err := ParseAllowlist([]byte("allow-empty\n"))
	if err != nil {
		t.Fatalf("explicit empty directive must be accepted: %v", err)
	}
	if len(entries) != 0 {
		t.Fatalf("expected no entries, got %v", entries)
	}
}

func TestParseAllowlistRejectsSingleTokenCommandExecutingProgram(t *testing.T) {
	// A bare "git" entry would authorize "git -c core.fsmonitor=..." which runs an
	// arbitrary command, so it must be rejected at load time.
	if _, err := ParseAllowlist([]byte("git\n")); err == nil {
		t.Fatalf("single token git entry must be rejected")
	}
	if _, err := ParseAllowlist([]byte("git status\n")); err != nil {
		t.Fatalf("git status entry must be accepted: %v", err)
	}
}

func TestParseAllowlistAllowsSingleTokenHarmlessProgram(t *testing.T) {
	if _, err := ParseAllowlist([]byte("ls\n")); err != nil {
		t.Fatalf("single token ls entry must be accepted: %v", err)
	}
}

func TestParseAllowlistReportsLineNumber(t *testing.T) {
	_, err := ParseAllowlist([]byte("ls\n\nfind\n"))
	if err == nil {
		t.Fatalf("expected rejection")
	}
	if !strings.Contains(err.Error(), "line 3") {
		t.Fatalf("error must name the offending line, got %v", err)
	}
}

func TestAllowlistPermitMatchesByPrefix(t *testing.T) {
	list, err := LoadAllowlist([]byte("git status\nls\n"))
	if err != nil {
		t.Fatal(err)
	}
	tests := []struct {
		name    string
		argv    []string
		wantErr bool
	}{
		{name: "exact entry", argv: []string{"git", "status"}},
		{name: "entry with extra arguments", argv: []string{"git", "status", "--short"}},
		{name: "single token entry", argv: []string{"ls", "-l"}},
		{name: "different subcommand is rejected", argv: []string{"git", "push"}, wantErr: true},
		{name: "option injection is rejected", argv: []string{"git", "-c", "core.fsmonitor=touch /tmp/x"}, wantErr: true},
		{name: "unknown program is rejected", argv: []string{"curl", "http://example.com"}, wantErr: true},
		{name: "empty argv is rejected", argv: nil, wantErr: true},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			err := list.Permit(test.argv)
			if (err != nil) != test.wantErr {
				t.Fatalf("err=%v, wantErr=%v", err, test.wantErr)
			}
		})
	}
}

func TestAllowlistEmptyPermitsNothing(t *testing.T) {
	list, err := LoadAllowlist([]byte("allow-empty\n"))
	if err != nil {
		t.Fatal(err)
	}
	if err := list.Permit([]string{"ls"}); err == nil {
		t.Fatalf("an empty allowlist must permit nothing")
	}
}

func TestAllowlistReloadIsAtomicAndKeepsPreviousOnFailure(t *testing.T) {
	list, err := LoadAllowlist([]byte("ls\n"))
	if err != nil {
		t.Fatal(err)
	}
	if err := list.Permit([]string{"ls"}); err != nil {
		t.Fatalf("initial entry must permit: %v", err)
	}
	// A failed reload must leave the previous list in force rather than clearing it.
	if err := list.Reload([]byte("git\n")); err == nil {
		t.Fatalf("expected reload to reject a single token git entry")
	}
	if err := list.Permit([]string{"ls"}); err != nil {
		t.Fatalf("previous entry must survive a failed reload: %v", err)
	}
	if list.Len() != 1 {
		t.Fatalf("expected 1 entry after failed reload, got %d", list.Len())
	}
	// A successful reload replaces the list.
	if err := list.Reload([]byte("git status\n")); err != nil {
		t.Fatalf("reload must succeed: %v", err)
	}
	if err := list.Permit([]string{"git", "status"}); err != nil {
		t.Fatalf("new entry must permit: %v", err)
	}
	if err := list.Permit([]string{"ls"}); err == nil {
		t.Fatalf("replaced entry must no longer permit")
	}
}

func TestAllowlistReloadRejectsEmptyDocument(t *testing.T) {
	list, err := LoadAllowlist([]byte("ls\n"))
	if err != nil {
		t.Fatal(err)
	}
	if err := list.Reload([]byte("")); err == nil {
		t.Fatalf("reload of an empty document must be rejected")
	}
	if list.Len() != 1 {
		t.Fatalf("expected previous entry to survive, got %d", list.Len())
	}
}
