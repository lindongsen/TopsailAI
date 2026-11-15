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

// TestSaveIdentityFailsWhenTheDirectoryIsMissing checks that a save into a
// directory that does not exist is reported rather than silently skipped,
// because a Node that believed it had saved an identity would start with none.
func TestSaveIdentityFailsWhenTheDirectoryIsMissing(t *testing.T) {
	base := t.TempDir()
	identity, err := security.NewNodeIdentity()
	if err != nil {
		t.Fatalf("NewNodeIdentity() = %v, want nil", err)
	}

	missing := filepath.Join(base, "absent", IdentityFileName)
	if err := SaveIdentity(missing, identity); err == nil {
		t.Fatal("SaveIdentity() = nil error, want a failure for a missing directory")
	}
	if _, err := os.Stat(missing); !errors.Is(err, os.ErrNotExist) {
		t.Fatal("SaveIdentity() wrote a file into a missing directory, want no file")
	}
}

// TestSaveIdentityLeavesNoTemporaryFileOnFailure checks that a failed save does
// not leave a temporary file behind, because that file holds a credential.
//
// The rename is made to fail by pointing the target at an existing directory: a
// rename over a directory fails on every platform, so the failure path is
// exercised without depending on a permission trick that root ignores.
func TestSaveIdentityLeavesNoTemporaryFileOnFailure(t *testing.T) {
	base := t.TempDir()
	identity, err := security.NewNodeIdentity()
	if err != nil {
		t.Fatalf("NewNodeIdentity() = %v, want nil", err)
	}

	target := filepath.Join(base, "identity")
	if err := os.Mkdir(target, 0o755); err != nil {
		t.Fatalf("mkdir target: %v", err)
	}

	if err := SaveIdentity(target, identity); err == nil {
		t.Fatal("SaveIdentity() = nil error, want a failure when the target is a directory")
	}

	entries, err := os.ReadDir(base)
	if err != nil {
		t.Fatalf("read base dir: %v", err)
	}
	for _, entry := range entries {
		if strings.HasPrefix(entry.Name(), ".identity-") {
			t.Fatalf("failed save left temporary file %q, want none", entry.Name())
		}
	}
}

// TestSaveIdentityReplacesAnExistingFile checks that a save over an existing
// identity replaces it, because regeneration must not fail on the file it is
// replacing.
func TestSaveIdentityReplacesAnExistingFile(t *testing.T) {
	_, identityPath := newIdentityFixture(t)

	first, err := security.NewNodeIdentity()
	if err != nil {
		t.Fatalf("NewNodeIdentity() = %v, want nil", err)
	}
	if err := SaveIdentity(identityPath, first); err != nil {
		t.Fatalf("first SaveIdentity() = %v, want nil", err)
	}

	second, err := security.NewNodeIdentity()
	if err != nil {
		t.Fatalf("NewNodeIdentity() = %v, want nil", err)
	}
	if err := SaveIdentity(identityPath, second); err != nil {
		t.Fatalf("second SaveIdentity() = %v, want nil", err)
	}

	loaded, err := LoadIdentity(identityPath)
	if err != nil {
		t.Fatalf("LoadIdentity() = %v, want nil", err)
	}
	if loaded.ID != second.ID {
		t.Fatalf("stored id = %q, want the replacement %q", loaded.ID, second.ID)
	}
}

// TestResolveConfigDirDefaultsToThePlatformDirectory checks that an empty value
// resolves to a directory named after the project, so a Node started without a
// configuration still has somewhere to keep its identity.
func TestResolveConfigDirDefaultsToThePlatformDirectory(t *testing.T) {
	base := t.TempDir()
	if runtime.GOOS == "windows" {
		t.Setenv("AppData", base)
	} else {
		t.Setenv("XDG_CONFIG_HOME", base)
	}

	resolved, err := resolveConfigDir("")
	if err != nil {
		t.Fatalf("resolveConfigDir(\"\") = %v, want nil", err)
	}
	if !filepath.IsAbs(resolved) {
		t.Fatalf("resolveConfigDir(\"\") = %q, want an absolute path", resolved)
	}
	if filepath.Base(resolved) != DefaultConfigDirectoryName {
		t.Fatalf("resolveConfigDir(\"\") = %q, want a path ending in %q", resolved, DefaultConfigDirectoryName)
	}
	info, err := os.Stat(resolved)
	if err != nil {
		t.Fatalf("stat resolved config dir: %v", err)
	}
	if !info.IsDir() {
		t.Fatalf("resolveConfigDir(\"\") = %q, want a directory", resolved)
	}
}

// TestResolveConfigDirRejectsARelativePath checks that a relative config
// directory is refused, because it resolves against whatever directory the
// process inherited.
func TestResolveConfigDirRejectsARelativePath(t *testing.T) {
	if _, err := resolveConfigDir("relative/config"); err == nil {
		t.Fatal("resolveConfigDir(relative) = nil error, want a refusal")
	}
}

// TestResolveConfigDirFailsWhenTheParentIsAFile checks that a config directory
// whose parent is a file is reported, because the failure is a configuration
// mistake rather than a transient condition.
func TestResolveConfigDirFailsWhenTheParentIsAFile(t *testing.T) {
	base := t.TempDir()
	blocker := filepath.Join(base, "blocker")
	writeFile(t, blocker, "not a directory")

	if _, err := resolveConfigDir(filepath.Join(blocker, "config")); err == nil {
		t.Fatal("resolveConfigDir() = nil error, want a failure when the parent is a file")
	}
}

// TestResolveConfigDirAcceptsAnExistingDirectory checks that an existing
// directory is returned unchanged, because re-permissioning a directory the
// operator created would be a surprise.
func TestResolveConfigDirAcceptsAnExistingDirectory(t *testing.T) {
	existing := t.TempDir()

	resolved, err := resolveConfigDir(existing)
	if err != nil {
		t.Fatalf("resolveConfigDir() = %v, want nil", err)
	}
	if resolved != existing {
		t.Fatalf("resolveConfigDir() = %q, want %q", resolved, existing)
	}
}

// TestScopeCloseOnAnUnopenedScopeIsSafe checks that closing a scope that was
// never opened returns nil, so a caller can defer Close without a nil check.
func TestScopeCloseOnAnUnopenedScopeIsSafe(t *testing.T) {
	scope := &Scope{}
	if err := scope.Close(); err != nil {
		t.Fatalf("Close() on an unopened scope = %v, want nil", err)
	}
}

// TestOpenScopeRejectsASymlinkedParent checks that a scope root reached through a
// symlinked parent is refused, because the resolved path differs from the
// configured one and the operator's mental model of the root would be wrong.
func TestOpenScopeRejectsASymlinkedParent(t *testing.T) {
	base := t.TempDir()
	real := filepath.Join(base, "real")
	if err := os.Mkdir(real, 0o755); err != nil {
		t.Fatalf("mkdir real: %v", err)
	}
	sub := filepath.Join(real, "sub")
	if err := os.Mkdir(sub, 0o755); err != nil {
		t.Fatalf("mkdir sub: %v", err)
	}

	link := filepath.Join(base, "link")
	mustSymlink(t, real, link)

	throughLink := filepath.Join(link, "sub")
	scope, err := OpenScope("project", throughLink, nil, "")
	if err == nil {
		scope.Close()
		t.Fatalf("OpenScope(%q) = nil error, want a refusal for a symlinked parent", throughLink)
	}
	if !strings.Contains(err.Error(), "resolves to") {
		t.Fatalf("OpenScope(%q) = %v, want a message naming the resolved path", throughLink, err)
	}
}

// TestIsHomeDirectoryWithAnUnresolvableHome checks that a home directory that
// cannot be resolved is still compared by its literal path, so the refusal does
// not disappear when the home directory is a broken symlink.
func TestIsHomeDirectoryWithAnUnresolvableHome(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("os.UserHomeDir reads a different variable on Windows")
	}

	base := t.TempDir()
	broken := filepath.Join(base, "broken-home")
	t.Setenv("HOME", broken)

	if !isHomeDirectory(broken) {
		t.Fatalf("isHomeDirectory(%q) = false, want true for the configured home", broken)
	}
	if isHomeDirectory(filepath.Join(base, "elsewhere")) {
		t.Fatal("isHomeDirectory(elsewhere) = true, want false")
	}
}

// TestIsHomeDirectoryWithNoHome checks that a missing home directory makes the
// check answer false rather than refusing every scope, because a refusal that
// depends on an unrelated environment variable is a refusal nobody can explain.
func TestIsHomeDirectoryWithNoHome(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("os.UserHomeDir reads a different variable on Windows")
	}

	t.Setenv("HOME", "")
	if isHomeDirectory(t.TempDir()) {
		t.Fatal("isHomeDirectory() = true with no home directory, want false")
	}
}
