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

// TestEnsureIdentityGeneratesOnce checks that the first call generates an id and the
// second returns the same id, because a Node that regenerated on every start would
// invalidate the address the operator already copied into a CLI.
func TestEnsureIdentityGeneratesOnce(t *testing.T) {
	_, identityPath := newIdentityFixture(t)

	first, generated, err := EnsureIdentity(identityPath)
	if err != nil {
		t.Fatalf("EnsureIdentity() = %v, want nil", err)
	}
	if !generated {
		t.Fatal("EnsureIdentity() reported generated = false on the first call, want true")
	}
	if err := security.ValidateNodeID(first); err != nil {
		t.Fatalf("generated id is invalid: %v", err)
	}

	second, generated, err := EnsureIdentity(identityPath)
	if err != nil {
		t.Fatalf("second EnsureIdentity() = %v, want nil", err)
	}
	if generated {
		t.Fatal("second EnsureIdentity() reported generated = true, want false")
	}
	if second != first {
		t.Fatalf("second id = %q, want %q", second, first)
	}
}

// TestEnsureIdentityRejectsMalformedFile checks that a malformed identity file is a
// startup failure rather than a regeneration, because regenerating would silently
// invalidate the address the operator already distributed.
func TestEnsureIdentityRejectsMalformedFile(t *testing.T) {
	cases := []struct {
		name    string
		content string
	}{
		{"no prefix", "abc\n"},
		{"empty file", ""},
		{"whitespace", " node_abc\n"},
		{"truncated body", "node_abc\n"},
		{"uppercase body", "node_ABCDEFGHIJKLMNOPQRSTUVWXY\n"},
		{"dot pair", "node_abcdefghijklmnopqrstuvwxy.abcdefghijklmnopqrstuvwxyzabcdefghijklmnopqrstuvwxyz\n"},
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

// TestLoadIdentityRejectsLoosePermissions checks that an identity file another user
// can read is refused.
//
// The id is an address rather than a credential, but it names the Node, so it is kept
// owner-only for the same reason a host name in a private file is: it is nobody else's
// business which Nodes exist.
func TestLoadIdentityRejectsLoosePermissions(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("permission bits are synthesised on Windows and carry no ownership information")
	}

	_, identityPath := newIdentityFixture(t)
	nodeID, _, err := EnsureIdentity(identityPath)
	if err != nil {
		t.Fatalf("EnsureIdentity() = %v, want nil", err)
	}
	if err := os.Chmod(identityPath, 0o644); err != nil {
		t.Fatalf("chmod identity file: %v", err)
	}

	if _, err := LoadIdentity(identityPath); err == nil {
		t.Fatal("LoadIdentity() = nil error, want a failure for a world-readable identity file")
	}

	// The id itself is still valid, so the refusal is about the mode rather than
	// about the content.
	if err := security.ValidateNodeID(nodeID); err != nil {
		t.Fatalf("identity id is invalid: %v", err)
	}
}

// TestSaveIdentityWritesOwnerOnlyFile checks that a saved identity is readable by its
// owner and nobody else.
func TestSaveIdentityWritesOwnerOnlyFile(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("permission bits are synthesised on Windows and carry no ownership information")
	}

	_, identityPath := newIdentityFixture(t)
	nodeID, err := security.NewNodeID()
	if err != nil {
		t.Fatalf("NewNodeID() = %v, want nil", err)
	}
	if err := SaveIdentity(identityPath, nodeID); err != nil {
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

// TestSaveIdentityLeavesNoTemporaryFile checks that a successful save leaves only the
// identity file, because a stray temporary file would be a file the operator does not
// know to look for.
func TestSaveIdentityLeavesNoTemporaryFile(t *testing.T) {
	configDir, identityPath := newIdentityFixture(t)
	nodeID, err := security.NewNodeID()
	if err != nil {
		t.Fatalf("NewNodeID() = %v, want nil", err)
	}
	if err := SaveIdentity(identityPath, nodeID); err != nil {
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

// TestSaveIdentityRejectsInvalidID checks that an invalid id is refused before it
// reaches the disk, so a file that can never be parsed is never written.
func TestSaveIdentityRejectsInvalidID(t *testing.T) {
	cases := []struct {
		name   string
		nodeID string
	}{
		{"empty", ""},
		{"no prefix", "abcdefghijklmnopqrstuvwxyz"},
		{"truncated body", "node_abc"},
		{"uppercase body", "node_ABCDEFGHIJKLMNOPQRSTUVWXY"},
		{"dot pair", "node_abcdefghijklmnopqrstuvwxy.abcdefghijklmnopqrstuvwxyzabcdefghijklmnopqrstuvwxyz"},
	}

	for _, testCase := range cases {
		t.Run(testCase.name, func(t *testing.T) {
			_, identityPath := newIdentityFixture(t)
			if err := SaveIdentity(identityPath, testCase.nodeID); err == nil {
				t.Fatal("SaveIdentity() = nil error, want a failure")
			}
			if _, err := os.Stat(identityPath); !errors.Is(err, os.ErrNotExist) {
				t.Fatal("SaveIdentity() wrote a file for an invalid id, want no file")
			}
		})
	}
}

// TestRegenerateIdentityReplacesTheID checks that a regeneration changes the address,
// because the old address must stop being the one the Node answers to.
func TestRegenerateIdentityReplacesTheID(t *testing.T) {
	_, identityPath := newIdentityFixture(t)
	original, _, err := EnsureIdentity(identityPath)
	if err != nil {
		t.Fatalf("EnsureIdentity() = %v, want nil", err)
	}

	regenerated, err := RegenerateIdentity(identityPath)
	if err != nil {
		t.Fatalf("RegenerateIdentity() = %v, want nil", err)
	}
	if regenerated == original {
		t.Fatal("regenerated id equals the original, want a new id")
	}

	loaded, err := LoadIdentity(identityPath)
	if err != nil {
		t.Fatalf("LoadIdentity() = %v, want nil", err)
	}
	if loaded != regenerated {
		t.Fatalf("stored id = %q, want %q", loaded, regenerated)
	}
}

// TestRegenerateIdentityLeavesCredentialsUntouched checks that regenerating the address
// does not revoke a caller.
//
// The two live in separate files because they answer different questions: regenerating
// the address must not lock every caller out, and revoking a caller must not change the
// address.
func TestRegenerateIdentityLeavesCredentialsUntouched(t *testing.T) {
	configDir, identityPath := newIdentityFixture(t)
	credentialsPath := CredentialsPath(configDir)

	if _, _, err := EnsureIdentity(identityPath); err != nil {
		t.Fatalf("EnsureIdentity() = %v, want nil", err)
	}
	_, created, err := EnsureCredentials(credentialsPath)
	if err != nil {
		t.Fatalf("EnsureCredentials() = %v, want nil", err)
	}
	if created == nil {
		t.Fatal("EnsureCredentials() generated no credential, so the test cannot prove it survived")
	}

	if _, err := RegenerateIdentity(identityPath); err != nil {
		t.Fatalf("RegenerateIdentity() = %v, want nil", err)
	}

	credentials, err := LoadCredentials(credentialsPath)
	if err != nil {
		t.Fatalf("LoadCredentials() = %v, want nil", err)
	}
	if _, present := credentials.Lookup(created.KeyID); !present {
		t.Fatal("regenerating the address revoked the caller, want the credential to survive")
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

// TestLoadIdentityAcceptsTrailingNewline checks that the newline the Node writes itself
// is accepted, so a file the Node wrote is always readable by the Node.
func TestLoadIdentityAcceptsTrailingNewline(t *testing.T) {
	_, identityPath := newIdentityFixture(t)
	nodeID, _, err := EnsureIdentity(identityPath)
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
	if loaded != nodeID {
		t.Fatalf("loaded id = %q, want %q", loaded, nodeID)
	}
}

// TestIdentityPathJoinsTheConfigDirectory checks that the identity file lives inside
// the config directory, so the deny list can name it before it exists.
func TestIdentityPathJoinsTheConfigDirectory(t *testing.T) {
	configDir := t.TempDir()
	want := filepath.Join(configDir, IdentityFileName)
	if got := IdentityPath(configDir); got != want {
		t.Fatalf("IdentityPath() = %q, want %q", got, want)
	}
}
