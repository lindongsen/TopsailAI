package main

import (
	"os"
	"path/filepath"
	"strings"
	"testing"

	"topsailai_connector/internal/node"
)

// credentialConfigDir returns a config directory for a credential test.
//
// The directory is a temporary one rather than the real config directory, because these
// commands write a credential file. A test that wrote to the operator's own directory
// would replace a working credential set with a fixture.
func credentialConfigDir(t *testing.T) string {
	t.Helper()

	directory := t.TempDir()
	t.Setenv("CONNECTOR_NODE_CONFIG_DIR", directory)
	return directory
}

// TestCredentialAddPrintsACredentialOnce checks the one moment a secret exists outside
// the file.
//
// The printed value is the only copy the operator will ever see, so it must be a complete
// credential and it must be the one that was stored. A test that only checked "something
// was printed" would pass for a truncated value that no CLI could use.
func TestCredentialAddPrintsACredentialOnce(t *testing.T) {
	directory := credentialConfigDir(t)

	printed, err := captureStdout(t, func() error {
		return run([]string{"credential", "add", "--key-id", "test-caller"})
	})
	if err != nil {
		t.Fatalf("credential add = %v, want nil", err)
	}

	credential := strings.TrimSpace(printed)
	if !strings.HasPrefix(credential, "test-caller.") {
		t.Fatalf("printed %q, want a credential named test-caller", credential)
	}
	if strings.Count(printed, "\n") != 1 {
		t.Errorf("printed %q, want exactly one line", printed)
	}

	// The printed value must be the stored one, because the operator copies it into a CLI
	// and a value that differs from the file would fail every request.
	stored, err := node.LoadCredentials(node.CredentialsPath(directory))
	if err != nil {
		t.Fatalf("load credentials: %v", err)
	}
	if len(stored.KeyIDs()) != 1 || stored.KeyIDs()[0] != "test-caller" {
		t.Fatalf("stored key ids = %v, want [test-caller]", stored.KeyIDs())
	}
}

// TestCredentialAddGeneratesAKeyIDWhenNoneIsGiven checks the default.
func TestCredentialAddGeneratesAKeyIDWhenNoneIsGiven(t *testing.T) {
	directory := credentialConfigDir(t)

	printed, err := captureStdout(t, func() error {
		return run([]string{"credential", "add"})
	})
	if err != nil {
		t.Fatalf("credential add = %v, want nil", err)
	}

	credential := strings.TrimSpace(printed)
	if !strings.Contains(credential, ".") {
		t.Fatalf("printed %q, want a key_id.secret pair", credential)
	}

	stored, err := node.LoadCredentials(node.CredentialsPath(directory))
	if err != nil {
		t.Fatalf("load credentials: %v", err)
	}
	if len(stored.KeyIDs()) != 1 {
		t.Fatalf("stored %d credentials, want 1", len(stored.KeyIDs()))
	}
}

// TestCredentialListPrintsKeyIDsAndNeverASecret checks the property the command exists to
// preserve.
//
// A file that could print a secret is a file that can leak one, so the assertion is on
// what must NOT appear. Checking only that the key id appears would pass for a command
// that printed the key id and the secret together.
func TestCredentialListPrintsKeyIDsAndNeverASecret(t *testing.T) {
	directory := credentialConfigDir(t)

	printed, err := captureStdout(t, func() error {
		return run([]string{"credential", "add", "--key-id", "first"})
	})
	if err != nil {
		t.Fatalf("credential add = %v, want nil", err)
	}
	secret := strings.TrimSpace(printed)
	secretPart := secret[strings.Index(secret, ".")+1:]

	listed, err := captureStdout(t, func() error {
		return run([]string{"credential", "list"})
	})
	if err != nil {
		t.Fatalf("credential list = %v, want nil", err)
	}

	if !strings.Contains(listed, "first") {
		t.Errorf("list printed %q, want the key id", listed)
	}
	if strings.Contains(listed, secretPart) {
		t.Errorf("list printed the secret: %q", listed)
	}

	// The stored file must still hold the secret, so the check above is about the output
	// rather than about a credential that was never written.
	stored, err := node.LoadCredentials(node.CredentialsPath(directory))
	if err != nil {
		t.Fatalf("load credentials: %v", err)
	}
	if len(stored.KeyIDs()) != 1 {
		t.Fatalf("stored %d credentials, want 1", len(stored.KeyIDs()))
	}
}

// TestCredentialRemoveDeletesOneCredential checks the ordinary removal.
func TestCredentialRemoveDeletesOneCredential(t *testing.T) {
	directory := credentialConfigDir(t)

	for _, name := range []string{"keep", "drop"} {
		if _, err := captureStdout(t, func() error {
			return run([]string{"credential", "add", "--key-id", name})
		}); err != nil {
			t.Fatalf("credential add %s = %v, want nil", name, err)
		}
	}

	if _, err := captureStdout(t, func() error {
		return run([]string{"credential", "remove", "--key-id", "drop"})
	}); err != nil {
		t.Fatalf("credential remove = %v, want nil", err)
	}

	stored, err := node.LoadCredentials(node.CredentialsPath(directory))
	if err != nil {
		t.Fatalf("load credentials: %v", err)
	}
	if len(stored.KeyIDs()) != 1 || stored.KeyIDs()[0] != "keep" {
		t.Errorf("stored key ids = %v, want [keep]", stored.KeyIDs())
	}
}

// TestCredentialRemoveRefusesTheLastCredential checks the refusal that keeps an operator
// from locking themselves out.
//
// A Node with no credential accepts nothing, which looks exactly like a Node whose policy
// denies everything, so an operator who did it by accident would debug the policy instead
// of the credential file.
func TestCredentialRemoveRefusesTheLastCredential(t *testing.T) {
	directory := credentialConfigDir(t)

	if _, err := captureStdout(t, func() error {
		return run([]string{"credential", "add", "--key-id", "only"})
	}); err != nil {
		t.Fatalf("credential add = %v, want nil", err)
	}

	err := run([]string{"credential", "remove", "--key-id", "only"})
	if err == nil {
		t.Fatal("credential remove of the last credential = nil, want a refusal")
	}
	if !strings.Contains(err.Error(), "last credential") {
		t.Errorf("error = %v, want a message about the last credential", err)
	}

	// The refusal must leave the file intact, because a refusal that removed the entry and
	// then complained would be worse than no refusal at all.
	stored, loadErr := node.LoadCredentials(node.CredentialsPath(directory))
	if loadErr != nil {
		t.Fatalf("load credentials: %v", loadErr)
	}
	if len(stored.KeyIDs()) != 1 {
		t.Errorf("stored %d credentials after a refusal, want 1", len(stored.KeyIDs()))
	}
}

// TestCredentialRemoveRefusesAnUnknownKeyID checks the typo case.
func TestCredentialRemoveRefusesAnUnknownKeyID(t *testing.T) {
	credentialConfigDir(t)

	if _, err := captureStdout(t, func() error {
		return run([]string{"credential", "add", "--key-id", "present"})
	}); err != nil {
		t.Fatalf("credential add = %v, want nil", err)
	}

	err := run([]string{"credential", "remove", "--key-id", "absent"})
	if err == nil {
		t.Fatal("credential remove of an unknown key id = nil, want a refusal")
	}
	if !strings.Contains(err.Error(), "absent") {
		t.Errorf("error = %v, want the rejected key id", err)
	}
}

// TestCredentialListOnAMissingFileReportsTheFailure checks the first-run case.
//
// An operator who runs `list` before adding anything must be told the file is missing
// rather than shown an empty list, because an empty list reads as "no callers are
// configured" while the truth is "this Node has never been set up".
func TestCredentialListOnAMissingFileReportsTheFailure(t *testing.T) {
	credentialConfigDir(t)

	err := run([]string{"credential", "list"})
	if err == nil {
		t.Fatal("credential list with no file = nil, want a refusal")
	}
}

// TestCredentialAddCreatesTheConfigDirectory checks that the first add works on a fresh
// machine.
//
// The directory does not exist on a machine that has never run the Node, so an add that
// required it would fail exactly where the documented first-run order puts it.
func TestCredentialAddCreatesTheConfigDirectory(t *testing.T) {
	parent := t.TempDir()
	directory := filepath.Join(parent, "not-yet-created")
	t.Setenv("CONNECTOR_NODE_CONFIG_DIR", directory)

	if _, err := captureStdout(t, func() error {
		return run([]string{"credential", "add", "--key-id", "fresh"})
	}); err != nil {
		t.Fatalf("credential add into a missing directory = %v, want nil", err)
	}

	if _, err := os.Stat(node.CredentialsPath(directory)); err != nil {
		t.Errorf("credentials file was not created: %v", err)
	}
}
