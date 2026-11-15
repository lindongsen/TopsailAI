package node

import (
	"os"
	"path/filepath"
	"testing"

	"topsailai_connector/internal/protocol"
)

// newLookAlikeFixture builds a real config directory and a look-alike tree that
// copies its shape: the same directory name, the same file names and the same
// file contents, at a different path.
//
// The look-alike is deliberately indistinguishable by name and by size, because
// the deny list must answer by identity rather than by appearance. A fixture that
// differed in name would pass even if the rule were name-based.
func newLookAlikeFixture(t *testing.T) (configDir string, lookAlike string, base string) {
	t.Helper()

	base = t.TempDir()
	configDir = filepath.Join(base, "node", "config")
	if err := os.MkdirAll(configDir, 0o700); err != nil {
		t.Fatalf("mkdir config: %v", err)
	}
	writeFile(t, filepath.Join(configDir, "identity"), "node_secret.token_secret")
	writeFile(t, filepath.Join(configDir, "policy.yaml"), "version: 1\n")

	lookAlike = filepath.Join(base, "project", "config")
	if err := os.MkdirAll(lookAlike, 0o700); err != nil {
		t.Fatalf("mkdir look-alike: %v", err)
	}
	writeFile(t, filepath.Join(lookAlike, "identity"), "node_secret.token_secret")
	writeFile(t, filepath.Join(lookAlike, "policy.yaml"), "version: 1\n")

	return configDir, lookAlike, base
}

// TestDenyListDoesNotDenyALookAlikeConfigDirectory checks the direction the deny
// list must not overreach: a directory that merely looks like the Node's config
// directory is a different directory, so it stays readable.
//
// The deny list is built from the identity of the Node's own files, not from
// their names. A name-based rule would refuse every directory called `config` on
// the machine, which would make a whole-volume scope useless for the ordinary
// project trees a caller actually reads.
func TestDenyListDoesNotDenyALookAlikeConfigDirectory(t *testing.T) {
	configDir, lookAlike, base := newLookAlikeFixture(t)

	root := filesystemRootPath(t)
	scope, err := openScope("whole", root, []string{configDir}, configDir, true)
	if err != nil {
		t.Fatalf("openScope(opt-in) = %v, want nil", err)
	}
	defer scope.Close()

	relativeConfig := relativeToRoot(t, configDir)
	relativeLookAlike := relativeToRoot(t, lookAlike)

	t.Run("the real config directory is denied", func(t *testing.T) {
		if _, _, err := scope.Read(relativeConfig+"/identity", 0, 0); CodeOf(err) != protocol.CodeDenied {
			t.Fatalf("Read(real identity) = %v, want denied", err)
		}
	})

	t.Run("the look-alike identity file is readable", func(t *testing.T) {
		content, _, err := scope.Read(relativeLookAlike+"/identity", 0, 0)
		if err != nil {
			t.Fatalf("Read(look-alike identity) = %v, want nil", err)
		}
		if string(content) != "node_secret.token_secret" {
			t.Fatalf("Read(look-alike identity) = %q, want the look-alike content", content)
		}
	})

	t.Run("the look-alike directory is listable", func(t *testing.T) {
		entries, err := scope.List(relativeLookAlike)
		if err != nil {
			t.Fatalf("List(look-alike) = %v, want nil", err)
		}
		if _, ok := findEntry(entries, "identity"); !ok {
			t.Fatalf("List(look-alike) = %v, want identity reported", entryNames(entries))
		}
	})

	t.Run("listing the look-alike parent reports it", func(t *testing.T) {
		relativeParent := relativeToRoot(t, filepath.Dir(lookAlike))
		entries, err := scope.List(relativeParent)
		if err != nil {
			t.Fatalf("List(look-alike parent) = %v, want nil", err)
		}
		if _, ok := findEntry(entries, "config"); !ok {
			t.Fatalf("List(look-alike parent) = %v, want config reported", entryNames(entries))
		}
	})

	t.Run("listing the real config parent omits it", func(t *testing.T) {
		relativeParent := relativeToRoot(t, filepath.Dir(configDir))
		entries, err := scope.List(relativeParent)
		if err != nil {
			t.Fatalf("List(real config parent) = %v, want nil", err)
		}
		if _, ok := findEntry(entries, "config"); ok {
			t.Fatalf("List(real config parent) = %v, want config omitted", entryNames(entries))
		}
	})

	t.Run("a look-alike nested inside the look-alike is readable", func(t *testing.T) {
		nested := filepath.Join(lookAlike, "config")
		if err := os.Mkdir(nested, 0o700); err != nil {
			t.Fatalf("mkdir nested look-alike: %v", err)
		}
		writeFile(t, filepath.Join(nested, "identity"), "nested content")

		content, _, err := scope.Read(relativeToRoot(t, filepath.Join(nested, "identity")), 0, 0)
		if err != nil {
			t.Fatalf("Read(nested look-alike identity) = %v, want nil", err)
		}
		if string(content) != "nested content" {
			t.Fatalf("Read(nested look-alike identity) = %q, want the nested content", content)
		}
	})

	t.Run("a look-alike inside the real config directory is denied", func(t *testing.T) {
		inner := filepath.Join(configDir, "config")
		if err := os.Mkdir(inner, 0o700); err != nil {
			t.Fatalf("mkdir inner: %v", err)
		}
		writeFile(t, filepath.Join(inner, "identity"), "inner content")

		if _, _, err := scope.Read(relativeToRoot(t, filepath.Join(inner, "identity")), 0, 0); CodeOf(err) != protocol.CodeDenied {
			t.Fatalf("Read(inner identity) = %v, want denied because it sits inside the denied directory", err)
		}
	})

	t.Run("a sibling sharing the config name prefix is readable", func(t *testing.T) {
		sibling := filepath.Join(base, "node", "config-backup")
		if err := os.Mkdir(sibling, 0o700); err != nil {
			t.Fatalf("mkdir sibling: %v", err)
		}
		writeFile(t, filepath.Join(sibling, "identity"), "sibling content")

		content, _, err := scope.Read(relativeToRoot(t, filepath.Join(sibling, "identity")), 0, 0)
		if err != nil {
			t.Fatalf("Read(sibling identity) = %v, want nil", err)
		}
		if string(content) != "sibling content" {
			t.Fatalf("Read(sibling identity) = %q, want the sibling content", content)
		}
	})
}

// TestDenyListDoesNotDenyALookAlikeUnderASubdirectoryScope checks the same
// property when the scope root is an ordinary directory rather than a volume.
//
// A subdirectory scope is the common case, so the look-alike rule must hold there
// too: the deny list is relative to the scope root, and a look-alike at a
// different relative path must not collide with it.
func TestDenyListDoesNotDenyALookAlikeUnderASubdirectoryScope(t *testing.T) {
	base := t.TempDir()
	scopeRoot := filepath.Join(base, "project")
	configDir := filepath.Join(scopeRoot, "node", "config")
	if err := os.MkdirAll(configDir, 0o700); err != nil {
		t.Fatalf("mkdir config: %v", err)
	}
	writeFile(t, filepath.Join(configDir, "identity"), "node_secret.token_secret")

	lookAlike := filepath.Join(scopeRoot, "app", "config")
	if err := os.MkdirAll(lookAlike, 0o700); err != nil {
		t.Fatalf("mkdir look-alike: %v", err)
	}
	writeFile(t, filepath.Join(lookAlike, "identity"), "look-alike content")

	scope, err := openScope("project", scopeRoot, []string{configDir}, "", false)
	if err != nil {
		t.Fatalf("openScope = %v, want nil", err)
	}
	defer scope.Close()

	if _, _, err := scope.Read("node/config/identity", 0, 0); CodeOf(err) != protocol.CodeDenied {
		t.Fatalf("Read(real identity) = %v, want denied", err)
	}

	content, _, err := scope.Read("app/config/identity", 0, 0)
	if err != nil {
		t.Fatalf("Read(look-alike identity) = %v, want nil", err)
	}
	if string(content) != "look-alike content" {
		t.Fatalf("Read(look-alike identity) = %q, want the look-alike content", content)
	}
}
