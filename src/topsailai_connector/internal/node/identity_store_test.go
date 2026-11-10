package node

import (
	"errors"
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"testing"

	"topsailai_connector/internal/security"
)

// newIdentityFixture returns a config directory and the identity path inside it.
func newIdentityFixture(t *testing.T) (configDir string, identityPath string) {
	t.Helper()
	configDir = t.TempDir()
	return configDir, IdentityPath(configDir)
}

// TestEnsureIdentityGeneratesOnce checks that the first call generates a pair and
// the second returns the same pair, because a Node that regenerated on every start
// would invalidate the pair the operator already copied into a CLI.
func TestEnsureIdentityGeneratesOnce(t *testing.T) {
	_, identityPath := newIdentityFixture(t)

	first, generated, err := EnsureIdentity(identityPath)
	if err != nil {
		t.Fatalf("EnsureIdentity() = %v, want nil", err)
	}
	if !generated {
		t.Fatal("EnsureIdentity() reported generated = false on the first call, want true")
	}
	if err := security.ValidateNodeID(first.ID); err != nil {
		t.Fatalf("generated id is invalid: %v", err)
	}
	if err := security.ValidateNodeToken(first.Token); err != nil {
		t.Fatalf("generated token is invalid: %v", err)
	}

	second, generated, err := EnsureIdentity(identityPath)
	if err != nil {
		t.Fatalf("second EnsureIdentity() = %v, want nil", err)
	}
	if generated {
		t.Fatal("second EnsureIdentity() reported generated = true, want false")
	}
	if second.ID != first.ID {
		t.Fatalf("second id = %q, want %q", second.ID, first.ID)
	}
	if !second.Token.Equal(first.Token) {
		t.Fatal("second token differs from the first, want the same pair")
	}
}

// TestEnsureIdentityRejectsMalformedFile checks that a malformed identity file is
// a startup failure rather than a regeneration, because regenerating would
// silently invalidate the pair the operator already distributed.
func TestEnsureIdentityRejectsMalformedFile(t *testing.T) {
	cases := []struct {
		name    string
		content string
	}{
		{"no dot", "node_abc\n"},
		{"empty token", "node_abc.\n"},
		{"empty id", ".token\n"},
		{"second dot", "node_abc.tok.en\n"},
		{"bad prefix", "abc.token\n"},
		{"empty file", ""},
		{"whitespace", " node_abc.token\n"},
	}

	for _, testCase := range cases {
		t.Run(testCase.name, func(t *testing.T) {
			_, identityPath := newIdentityFixture(t)
			writeFile(t, identityPath, testCase.content)
			if err := os.Chmod(identityPath, 0o600); err != nil {
				t.Fatalf("chmod identity file: %v", err)
			}

			_, _, err := EnsureIdentity(identityPath)
			if err == nil {
				t.Fatal("EnsureIdentity() = nil error, want a failure for a malformed file")
			}
			if errors.Is(err, ErrIdentityMissing) {
				t.Fatal("EnsureIdentity() reported a missing file, want a malformed-file failure")
			}
		})
	}
}

// TestLoadIdentityRejectsLoosePermissions checks that an identity file another
// user can read is refused, because it holds a credential that never expires.
func TestLoadIdentityRejectsLoosePermissions(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("permission bits are synthesised on Windows and carry no ownership information")
	}

	_, identityPath := newIdentityFixture(t)
	identity, _, err := EnsureIdentity(identityPath)
	if err != nil {
		t.Fatalf("EnsureIdentity() = %v, want nil", err)
	}
	if err := os.Chmod(identityPath, 0o644); err != nil {
		t.Fatalf("chmod identity file: %v", err)
	}

	if _, err := LoadIdentity(identityPath); err == nil {
		t.Fatal("LoadIdentity() = nil error, want a failure for a world-readable identity file")
	}

	// The pair itself is still valid, so the refusal is about the mode rather
	// than about the content.
	if err := security.ValidateNodeID(identity.ID); err != nil {
		t.Fatalf("identity id is invalid: %v", err)
	}
}

// TestSaveIdentityWritesOwnerOnlyFile checks that a saved identity is readable by
// its owner and nobody else.
func TestSaveIdentityWritesOwnerOnlyFile(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("permission bits are synthesised on Windows and carry no ownership information")
	}

	_, identityPath := newIdentityFixture(t)
	identity, err := security.NewNodeIdentity()
	if err != nil {
		t.Fatalf("NewNodeIdentity() = %v, want nil", err)
	}
	if err := SaveIdentity(identityPath, identity); err != nil {
		t.Fatalf("SaveIdentity() = %v, want nil", err)
	}

	info, err := os.Stat(identityPath)
	if err != nil {
		t.Fatalf("stat identity file: %v", err)
	}
	if mode := info.Mode().Perm(); mode != 0o600 {
		t.Fatalf("identity file mode = %04o, want 0600", mode)
	}
}

// TestSaveIdentityLeavesNoTemporaryFile checks that a successful save leaves only
// the identity file, because a stray temporary file would hold a credential.
func TestSaveIdentityLeavesNoTemporaryFile(t *testing.T) {
	configDir, identityPath := newIdentityFixture(t)
	identity, err := security.NewNodeIdentity()
	if err != nil {
		t.Fatalf("NewNodeIdentity() = %v, want nil", err)
	}
	if err := SaveIdentity(identityPath, identity); err != nil {
		t.Fatalf("SaveIdentity() = %v, want nil", err)
	}

	entries, err := os.ReadDir(configDir)
	if err != nil {
		t.Fatalf("read config dir: %v", err)
	}
	if len(entries) != 1 {
		names := make([]string, 0, len(entries))
		for _, entry := range entries {
			names = append(names, entry.Name())
		}
		t.Fatalf("config dir holds %v, want only the identity file", names)
	}
	if entries[0].Name() != IdentityFileName {
		t.Fatalf("config dir holds %q, want %q", entries[0].Name(), IdentityFileName)
	}
}

// TestSaveIdentityRejectsInvalidIdentity checks that an invalid pair is refused
// before it reaches the disk, so a file that can never be parsed is never written.
func TestSaveIdentityRejectsInvalidIdentity(t *testing.T) {
	cases := []struct {
		name     string
		identity security.NodeIdentity
	}{
		{"bad id", security.NodeIdentity{ID: "abc", Token: "token"}},
		{"empty token", security.NodeIdentity{ID: "node_abc", Token: ""}},
		{"uppercase token", security.NodeIdentity{ID: "node_abc", Token: "TOKEN"}},
	}

	for _, testCase := range cases {
		t.Run(testCase.name, func(t *testing.T) {
			_, identityPath := newIdentityFixture(t)
			if err := SaveIdentity(identityPath, testCase.identity); err == nil {
				t.Fatal("SaveIdentity() = nil error, want a failure")
			}
			if _, err := os.Stat(identityPath); !errors.Is(err, os.ErrNotExist) {
				t.Fatal("SaveIdentity() wrote a file for an invalid identity, want no file")
			}
		})
	}
}

// TestRegenerateIdentityReplacesBothHalves checks that a full regeneration changes
// the identifier and the token, because the old pair must stop working.
func TestRegenerateIdentityReplacesBothHalves(t *testing.T) {
	_, identityPath := newIdentityFixture(t)
	original, _, err := EnsureIdentity(identityPath)
	if err != nil {
		t.Fatalf("EnsureIdentity() = %v, want nil", err)
	}

	regenerated, err := RegenerateIdentity(identityPath, false)
	if err != nil {
		t.Fatalf("RegenerateIdentity() = %v, want nil", err)
	}
	if regenerated.ID == original.ID {
		t.Fatal("regenerated id equals the original, want a new id")
	}
	if regenerated.Token.Equal(original.Token) {
		t.Fatal("regenerated token equals the original, want a new token")
	}

	loaded, err := LoadIdentity(identityPath)
	if err != nil {
		t.Fatalf("LoadIdentity() = %v, want nil", err)
	}
	if loaded.ID != regenerated.ID {
		t.Fatalf("stored id = %q, want %q", loaded.ID, regenerated.ID)
	}
	if !loaded.Token.Equal(regenerated.Token) {
		t.Fatal("stored token differs from the regenerated token")
	}
}

// TestRegenerateIdentityKeepIDKeepsTheIdentifier checks that --keep-id preserves
// the routing name while replacing the secret, because the CLI's target must stay
// valid while the credential changes.
func TestRegenerateIdentityKeepIDKeepsTheIdentifier(t *testing.T) {
	_, identityPath := newIdentityFixture(t)
	original, _, err := EnsureIdentity(identityPath)
	if err != nil {
		t.Fatalf("EnsureIdentity() = %v, want nil", err)
	}

	regenerated, err := RegenerateIdentity(identityPath, true)
	if err != nil {
		t.Fatalf("RegenerateIdentity(keep-id) = %v, want nil", err)
	}
	if regenerated.ID != original.ID {
		t.Fatalf("regenerated id = %q, want %q", regenerated.ID, original.ID)
	}
	if regenerated.Token.Equal(original.Token) {
		t.Fatal("regenerated token equals the original, want a new token")
	}
}

// TestRegenerateIdentityKeepIDRequiresAnIdentity checks that --keep-id on a Node
// with no identity fails rather than inventing an identifier, because there is no
// name to keep.
func TestRegenerateIdentityKeepIDRequiresAnIdentity(t *testing.T) {
	_, identityPath := newIdentityFixture(t)
	if _, err := RegenerateIdentity(identityPath, true); err == nil {
		t.Fatal("RegenerateIdentity(keep-id) = nil error, want a failure with no identity file")
	}
}

// TestLoadIdentityReportsMissingFile checks that a missing file is reported as
// ErrIdentityMissing, so the caller can tell "generate one" from "refuse".
func TestLoadIdentityReportsMissingFile(t *testing.T) {
	_, identityPath := newIdentityFixture(t)
	_, err := LoadIdentity(identityPath)
	if err == nil {
		t.Fatal("LoadIdentity() = nil error, want a failure")
	}
	if !errors.Is(err, ErrIdentityMissing) {
		t.Fatalf("LoadIdentity() error = %v, want it to wrap ErrIdentityMissing", err)
	}
}

// TestLoadIdentityAcceptsTrailingNewline checks that the newline the Node writes
// itself is accepted, so a file the Node wrote is always readable by the Node.
func TestLoadIdentityAcceptsTrailingNewline(t *testing.T) {
	_, identityPath := newIdentityFixture(t)
	identity, _, err := EnsureIdentity(identityPath)
	if err != nil {
		t.Fatalf("EnsureIdentity() = %v, want nil", err)
	}

	content, err := os.ReadFile(identityPath)
	if err != nil {
		t.Fatalf("read identity file: %v", err)
	}
	if !strings.HasSuffix(string(content), "\n") {
		t.Fatal("identity file does not end with a newline, want one")
	}

	loaded, err := LoadIdentity(identityPath)
	if err != nil {
		t.Fatalf("LoadIdentity() = %v, want nil", err)
	}
	if loaded.ID != identity.ID {
		t.Fatalf("loaded id = %q, want %q", loaded.ID, identity.ID)
	}
}

// TestIdentityPathJoinsTheConfigDirectory checks that the identity file lives
// inside the config directory, so the deny list can name it before it exists.
func TestIdentityPathJoinsTheConfigDirectory(t *testing.T) {
	configDir := t.TempDir()
	want := filepath.Join(configDir, IdentityFileName)
	if got := IdentityPath(configDir); got != want {
		t.Fatalf("IdentityPath() = %q, want %q", got, want)
	}
}
