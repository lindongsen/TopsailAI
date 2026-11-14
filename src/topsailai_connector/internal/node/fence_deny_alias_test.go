package node

import (
	"os"
	"path/filepath"
	"testing"

	"topsailai_connector/internal/protocol"
)

// newAliasFixture builds a config directory holding the three files a real Node
// keeps there, plus a scope tree that can hold a symlink pointing at it.
//
// The fixture includes `tunnel_token` on purpose. That file is not named in the
// deny list, so a rule that only compares the identity of the listed files cannot
// see it. A fixture that held only `identity` and `policy.yaml` would pass even
// when the alias route leaked the one file that is not listed.
func newAliasFixture(t *testing.T) (configDir string, scopeRoot string) {
	t.Helper()

	base := t.TempDir()
	configDir = filepath.Join(base, "node", "config")
	if err := os.MkdirAll(configDir, 0o700); err != nil {
		t.Fatalf("mkdir config: %v", err)
	}
	writeFile(t, filepath.Join(configDir, "identity"), "node_secret.token_secret")
	writeFile(t, filepath.Join(configDir, "policy.yaml"), "version: 1\n")
	writeFile(t, filepath.Join(configDir, "tunnel_token"), "tunnel-secret-value")

	scopeRoot = filepath.Join(base, "project")
	if err := os.MkdirAll(scopeRoot, 0o700); err != nil {
		t.Fatalf("mkdir scope root: %v", err)
	}
	writeFile(t, filepath.Join(scopeRoot, "readable.txt"), "readable content")

	return configDir, scopeRoot
}

// linkRelative creates a symlink whose target is expressed relative to the link's
// own directory.
//
// The target is relative on purpose. os.Root refuses to follow a symlink with an
// absolute target, so an absolute link would be refused before the deny list ran
// and the test would be measuring os.Root rather than the rule under test. A
// relative link that stays inside the root is followed, which is the case the
// deny list has to cover.
func linkRelative(t *testing.T, linkPath string, target string) {
	t.Helper()

	relative, err := filepath.Rel(filepath.Dir(linkPath), target)
	if err != nil {
		t.Fatalf("rel %q from %q: %v", target, filepath.Dir(linkPath), err)
	}
	if err := os.Symlink(relative, linkPath); err != nil {
		t.Skipf("symlink unsupported on this host: %v", err)
	}
}

// denyPathsFor returns the deny list a real Node passes: the identity file, the
// policy file and the config directory.
func denyPathsFor(configDir string) []string {
	return []string{
		filepath.Join(configDir, "identity"),
		filepath.Join(configDir, "policy.yaml"),
		configDir,
	}
}

// TestDenyListRefusesARelativeSymlinkAlias checks that a symlink inside the scope
// pointing at the Node's config directory is refused, including for the file that
// the deny list does not name.
//
// This is the gap the written-path rule and the file-identity rule each leave
// open. The alias is a different written path, so the prefix rule cannot see it.
// `tunnel_token` is not in the deny list, so the file comparison cannot see it
// either. Comparing the identity of every ancestor closes both at once.
func TestDenyListRefusesARelativeSymlinkAlias(t *testing.T) {
	configDir, scopeRoot := newAliasFixture(t)
	linkRelative(t, filepath.Join(scopeRoot, "alias"), configDir)

	scope, err := openScope("project", scopeRoot, denyPathsFor(configDir), "", false)
	if err != nil {
		t.Fatalf("openScope = %v, want nil", err)
	}
	defer scope.Close()

	for _, name := range []string{"identity", "policy.yaml", "tunnel_token"} {
		t.Run("read through the alias is denied: "+name, func(t *testing.T) {
			content, _, err := scope.Read("alias/"+name, 0, 0)
			if CodeOf(err) != protocol.CodeDenied {
				t.Fatalf("Read(alias/%s) = %v, content %q; want denied", name, err, content)
			}
			if len(content) != 0 {
				t.Fatalf("Read(alias/%s) returned %q with a refusal; a refusal must carry no content", name, content)
			}
		})
	}

	t.Run("stat through the alias is denied", func(t *testing.T) {
		if _, err := scope.Stat("alias/identity"); CodeOf(err) != protocol.CodeDenied {
			t.Fatalf("Stat(alias/identity) = %v, want denied", err)
		}
	})

	t.Run("listing the alias is denied", func(t *testing.T) {
		if _, err := scope.List("alias"); CodeOf(err) != protocol.CodeDenied {
			t.Fatalf("List(alias) = %v, want denied", err)
		}
	})

	t.Run("stat of the alias itself is denied", func(t *testing.T) {
		// The alias resolves to a denied directory, so it is refused rather
		// than reported. Reporting it with the target withheld was the earlier
		// behaviour and it was wrong twice over: it answered differently
		// depending on whether the alias escaped the scope root, and a
		// symlink's reported size is the length of its target, so the withheld
		// target was still disclosed by its length.
		if _, err := scope.Stat("alias"); CodeOf(err) != protocol.CodeDenied {
			t.Fatalf("Stat(alias) = %v, want denied", err)
		}
	})

	t.Run("listing the alias parent omits it", func(t *testing.T) {
		// The alias is omitted rather than reported, for the same reason the
		// config directory itself is omitted: the deny list answers by
		// identity, so the same directory must get the same answer whichever
		// name reaches it. An escaping symlink that does not resolve to a
		// denied directory is still reported, which the look-alike test
		// asserts.
		entries, err := scope.List("")
		if err != nil {
			t.Fatalf("List(root) = %v, want nil", err)
		}
		if _, ok := findEntry(entries, "alias"); ok {
			t.Fatalf("List(root) = %v, want alias omitted", entryNames(entries))
		}
		if _, ok := findEntry(entries, "readable.txt"); !ok {
			t.Fatalf("List(root) = %v, want readable.txt reported", entryNames(entries))
		}
	})
	t.Run("an ordinary file is still readable", func(t *testing.T) {
		content, _, err := scope.Read("readable.txt", 0, 0)
		if err != nil {
			t.Fatalf("Read(readable.txt) = %v, want nil", err)
		}
		if string(content) != "readable content" {
			t.Fatalf("Read(readable.txt) = %q, want the file content", content)
		}
	})
}

// TestDenyListRefusesAnAbsoluteSymlinkAlias checks the same property for an
// absolute link target.
//
// os.Root refuses an absolute target that leaves the root, so this case is
// already refused before the deny list runs. The test states it anyway, because
// the refusal must not depend on which of the two rules happens to fire first.
func TestDenyListRefusesAnAbsoluteSymlinkAlias(t *testing.T) {
	configDir, scopeRoot := newAliasFixture(t)

	if err := os.Symlink(configDir, filepath.Join(scopeRoot, "alias")); err != nil {
		t.Skipf("symlink unsupported on this host: %v", err)
	}

	scope, err := openScope("project", scopeRoot, denyPathsFor(configDir), "", false)
	if err != nil {
		t.Fatalf("openScope = %v, want nil", err)
	}
	defer scope.Close()

	if _, _, err := scope.Read("alias/tunnel_token", 0, 0); CodeOf(err) != protocol.CodeDenied {
		t.Fatalf("Read(alias/tunnel_token) = %v, want denied", err)
	}

	t.Run("the alias is omitted from a listing", func(t *testing.T) {
		entries, err := scope.List("")
		if err != nil {
			t.Fatalf("List(root) = %v, want nil", err)
		}
		if _, ok := findEntry(entries, "alias"); ok {
			t.Fatalf("List(root) = %v, want alias omitted", entryNames(entries))
		}
	})

	t.Run("stat of the alias itself is denied", func(t *testing.T) {
		// The answer must not depend on which rule fires first. An absolute
		// target is refused by os.Root before the deny list runs, and the deny
		// list refuses it too, so the caller sees one answer either way.
		if _, err := scope.Stat("alias"); CodeOf(err) != protocol.CodeDenied {
			t.Fatalf("Stat(alias) = %v, want denied", err)
		}
	})
}

// TestDenyListRefusesAnAliasToALookAlikeInsideTheConfigDirectory checks the
// combination: a symlink that points at a directory nested inside the real config
// directory.
//
// The nested directory is not itself deny-listed, so only the ancestor rule can
// refuse it. Without that rule the alias would be a second route into the config
// directory, one level deeper than the first.
func TestDenyListRefusesAnAliasToALookAlikeInsideTheConfigDirectory(t *testing.T) {
	configDir, scopeRoot := newAliasFixture(t)

	nested := filepath.Join(configDir, "nested")
	if err := os.Mkdir(nested, 0o700); err != nil {
		t.Fatalf("mkdir nested: %v", err)
	}
	writeFile(t, filepath.Join(nested, "secret.txt"), "nested secret")

	linkRelative(t, filepath.Join(scopeRoot, "deep"), nested)

	scope, err := openScope("project", scopeRoot, denyPathsFor(configDir), "", false)
	if err != nil {
		t.Fatalf("openScope = %v, want nil", err)
	}
	defer scope.Close()

	if _, _, err := scope.Read("deep/secret.txt", 0, 0); CodeOf(err) != protocol.CodeDenied {
		t.Fatalf("Read(deep/secret.txt) = %v, want denied", err)
	}
}

// TestDenyListAllowsAnAliasToALookAlikeConfigDirectory checks the direction the
// ancestor rule must not overreach.
//
// A symlink pointing at a directory that merely looks like the config directory
// is a different directory, so it stays readable. A rule that refused it would be
// answering by name, which is the defect the identity comparison exists to avoid.
func TestDenyListAllowsAnAliasToALookAlikeConfigDirectory(t *testing.T) {
	configDir, scopeRoot := newAliasFixture(t)

	lookAlike := filepath.Join(scopeRoot, "app", "config")
	if err := os.MkdirAll(lookAlike, 0o700); err != nil {
		t.Fatalf("mkdir look-alike: %v", err)
	}
	writeFile(t, filepath.Join(lookAlike, "identity"), "look-alike content")

	linkRelative(t, filepath.Join(scopeRoot, "lookalike-alias"), lookAlike)

	scope, err := openScope("project", scopeRoot, denyPathsFor(configDir), "", false)
	if err != nil {
		t.Fatalf("openScope = %v, want nil", err)
	}
	defer scope.Close()

	content, _, err := scope.Read("lookalike-alias/identity", 0, 0)
	if err != nil {
		t.Fatalf("Read(lookalike-alias/identity) = %v, want nil", err)
	}
	if string(content) != "look-alike content" {
		t.Fatalf("Read(lookalike-alias/identity) = %q, want the look-alike content", content)
	}
}

// TestDenyListRefusesAnAliasUnderAWholeVolumeScope checks the alias rule under the
// configuration the filesystem-root opt-in makes possible: one scope rooted at the
// volume, with the config directory inside it.
//
// This is the shape a bundle produced with PACKAGE_ALLOW_FILESYSTEM_ROOT=1 runs,
// so the alias rule has to hold there rather than only under a subdirectory scope.
func TestDenyListRefusesAnAliasUnderAWholeVolumeScope(t *testing.T) {
	configDir, scopeRoot := newAliasFixture(t)
	linkRelative(t, filepath.Join(scopeRoot, "alias"), configDir)

	root := filesystemRootPath(t)
	scope, err := openScope("whole", root, denyPathsFor(configDir), configDir, true)
	if err != nil {
		t.Fatalf("openScope(opt-in) = %v, want nil", err)
	}
	defer scope.Close()

	relativeAlias := relativeToRoot(t, filepath.Join(scopeRoot, "alias"))
	for _, name := range []string{"identity", "policy.yaml", "tunnel_token"} {
		t.Run("read through the alias is denied: "+name, func(t *testing.T) {
			content, _, err := scope.Read(relativeAlias+"/"+name, 0, 0)
			if CodeOf(err) != protocol.CodeDenied {
				t.Fatalf("Read(alias/%s) = %v, content %q; want denied", name, err, content)
			}
		})
	}

	t.Run("listing the alias parent omits it", func(t *testing.T) {
		entries, err := scope.List(relativeToRoot(t, scopeRoot))
		if err != nil {
			t.Fatalf("List(scope root) = %v, want nil", err)
		}
		if _, ok := findEntry(entries, "alias"); ok {
			t.Fatalf("List(scope root) = %v, want alias omitted", entryNames(entries))
		}
	})
}
