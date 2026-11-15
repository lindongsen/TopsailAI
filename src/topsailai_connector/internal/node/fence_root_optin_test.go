package node

import (
	"os"
	"path/filepath"
	"strings"
	"testing"

	"topsailai_connector/internal/protocol"
)

// relativeToRoot returns the path of target expressed relative to the
// filesystem root, in the form a caller would send through a scope rooted there.
//
// The value is derived from the root rather than written as a literal, because a
// literal would be POSIX-only and the opt-in is a Windows feature as much as a
// POSIX one.
func relativeToRoot(t *testing.T, target string) string {
	t.Helper()

	root := filesystemRootPath(t)
	relative, err := filepath.Rel(root, target)
	if err != nil {
		t.Fatalf("rel %q from %q: %v", target, root, err)
	}
	return filepath.ToSlash(relative)
}

// TestOpenScopeRefusesAFilesystemRootByDefault checks that the public entry point
// never permits a scope rooted at a filesystem root.
//
// The opt-in lives in the policy file and is applied by LoadAuthority, so a
// caller that has not read a policy cannot widen the fence by passing a flag.
func TestOpenScopeRefusesAFilesystemRootByDefault(t *testing.T) {
	root := filesystemRootPath(t)

	scope, err := OpenScope("whole", root, nil, "")
	if err == nil {
		scope.Close()
		t.Fatal("OpenScope(filesystem root) = nil error, want a refusal")
	}
	if !strings.Contains(err.Error(), "filesystem root") {
		t.Fatalf("OpenScope(filesystem root) = %v, want a message naming the filesystem root", err)
	}
}

// TestLoadAuthorityRefusesAFilesystemRootWithoutTheOptIn checks that a policy
// which does not state the opt-in keeps the refusal.
//
// The absence of the key is the default, so an operator who never heard of the
// opt-in cannot get a volume-root scope by accident.
func TestLoadAuthorityRefusesAFilesystemRootWithoutTheOptIn(t *testing.T) {
	base := t.TempDir()
	policyPath := filepath.Join(base, "policy.yaml")
	root := filesystemRootPath(t)

	writeFile(t, policyPath, "version: 1\n"+
		"scopes:\n"+
		"  whole:\n"+
		"    path: "+root+"\n"+
		"grants:\n"+
		"  - scope: whole\n"+
		"    permissions: [read, list, stat]\n")

	authority, err := LoadAuthority(policyPath, nil, "")
	if err == nil {
		authority.Close()
		t.Fatal("LoadAuthority(no opt-in) = nil error, want a refusal")
	}
	if !strings.Contains(err.Error(), "filesystem root") {
		t.Fatalf("LoadAuthority(no opt-in) = %v, want a message naming the filesystem root", err)
	}
}

// TestLoadAuthorityOpensAFilesystemRootWithTheOptIn checks that the opt-in is
// what makes a volume-root scope possible, and that the scope then serves a real
// file.
func TestLoadAuthorityOpensAFilesystemRootWithTheOptIn(t *testing.T) {
	base := t.TempDir()
	configDir := filepath.Join(base, "config")
	if err := os.Mkdir(configDir, 0o700); err != nil {
		t.Fatalf("mkdir config: %v", err)
	}
	writeFile(t, filepath.Join(configDir, "identity"), "node_secret.token_secret")
	writeFile(t, filepath.Join(base, "visible.txt"), "visible content")

	policyPath := filepath.Join(configDir, "policy.yaml")
	root := filesystemRootPath(t)

	writeFile(t, policyPath, "version: 1\n"+
		"allow_filesystem_root: true\n"+
		"scopes:\n"+
		"  whole:\n"+
		"    path: "+root+"\n"+
		"grants:\n"+
		"  - scope: whole\n"+
		"    permissions: [read, list, stat]\n")

	authority, err := LoadAuthority(policyPath, []string{configDir}, configDir)
	if err != nil {
		t.Fatalf("LoadAuthority(opt-in) = %v, want nil", err)
	}
	defer authority.Close()

	scope, ok := authority.Scope("whole")
	if !ok {
		t.Fatal("Authority.Scope(whole) = false, want the opted-in scope")
	}

	visible := relativeToRoot(t, filepath.Join(base, "visible.txt"))
	data, _, err := scope.Read(visible, 0, 0)
	if err != nil {
		t.Fatalf("Read(%q) = %v, want nil", visible, err)
	}
	if string(data) != "visible content" {
		t.Fatalf("Read(%q) = %q, want the file content", visible, data)
	}
}

// TestOptedInScopeDoesNotDiscloseTheConfigDirectory checks the property that
// makes the opt-in safe: a scope rooted at a volume contains the Node's config
// directory, so the deny list must refuse the directory and everything inside it,
// and a listing must not report it.
//
// Without this, opting in would hand a caller the identity file, which holds the
// credential that authorizes every operation on this Node.
func TestOptedInScopeDoesNotDiscloseTheConfigDirectory(t *testing.T) {
	base := t.TempDir()
	configDir := filepath.Join(base, "config")
	if err := os.Mkdir(configDir, 0o700); err != nil {
		t.Fatalf("mkdir config: %v", err)
	}
	writeFile(t, filepath.Join(configDir, "identity"), "node_secret.token_secret")
	writeFile(t, filepath.Join(configDir, "policy.yaml"), "version: 1\n")
	writeFile(t, filepath.Join(base, "visible.txt"), "visible content")

	root := filesystemRootPath(t)
	scope, err := openScope("whole", root, []string{configDir}, configDir, true)
	if err != nil {
		t.Fatalf("openScope(opt-in) = %v, want nil", err)
	}
	defer scope.Close()

	relativeConfig := relativeToRoot(t, configDir)

	t.Run("read the identity file", func(t *testing.T) {
		attempt := relativeConfig + "/identity"
		if _, _, err := scope.Read(attempt, 0, 0); CodeOf(err) != protocol.CodeDenied {
			t.Fatalf("Read(%q) = %v, want denied", attempt, err)
		}
	})

	t.Run("stat the config directory", func(t *testing.T) {
		if _, err := scope.Stat(relativeConfig); CodeOf(err) != protocol.CodeDenied {
			t.Fatalf("Stat(%q) = %v, want denied", relativeConfig, err)
		}
	})

	t.Run("list the config directory", func(t *testing.T) {
		if _, err := scope.List(relativeConfig); CodeOf(err) != protocol.CodeDenied {
			t.Fatalf("List(%q) = %v, want denied", relativeConfig, err)
		}
	})

	t.Run("listing the parent omits the config directory", func(t *testing.T) {
		relativeBase := relativeToRoot(t, base)
		entries, err := scope.List(relativeBase)
		if err != nil {
			t.Fatalf("List(%q) = %v, want nil", relativeBase, err)
		}
		if _, ok := findEntry(entries, "config"); ok {
			t.Fatalf("List(%q) = %v, want the config directory omitted", relativeBase, entryNames(entries))
		}
		if _, ok := findEntry(entries, "visible.txt"); !ok {
			t.Fatalf("List(%q) = %v, want visible.txt reported", relativeBase, entryNames(entries))
		}
	})
}

// TestOptedInScopeStillRefusesAnEscape checks that the opt-in relaxes the
// filesystem-root refusal and nothing else: a path that leaves the root is still
// refused, so a volume-root scope is not a fence-free scope.
func TestOptedInScopeStillRefusesAnEscape(t *testing.T) {
	base := t.TempDir()
	configDir := filepath.Join(base, "config")
	if err := os.Mkdir(configDir, 0o700); err != nil {
		t.Fatalf("mkdir config: %v", err)
	}

	root := filesystemRootPath(t)
	scope, err := openScope("whole", root, []string{configDir}, configDir, true)
	if err != nil {
		t.Fatalf("openScope(opt-in) = %v, want nil", err)
	}
	defer scope.Close()

	for _, attempt := range []string{"../etc/passwd", "..", "/etc/passwd"} {
		t.Run(attempt, func(t *testing.T) {
			if _, _, err := scope.Read(attempt, 0, 0); CodeOf(err) != protocol.CodeInvalidArgument {
				t.Fatalf("Read(%q) = %v, want invalid_argument", attempt, err)
			}
		})
	}
}

// TestOptedInScopeStillRefusesARelativeRoot checks that the opt-in does not
// relax the rules that have nothing to do with the blast radius: a relative path
// still resolves differently per launch, so it is still refused.
func TestOptedInScopeStillRefusesARelativeRoot(t *testing.T) {
	base := t.TempDir()
	configDir := filepath.Join(base, "config")
	if err := os.Mkdir(configDir, 0o700); err != nil {
		t.Fatalf("mkdir config: %v", err)
	}

	if _, err := openScope("whole", "relative/path", []string{configDir}, configDir, true); err == nil {
		t.Fatal("openScope(relative, opt-in) = nil error, want a refusal")
	}
}

// TestIsDeniedPathUsesASeparatorBoundary checks that a denied directory does not
// deny a sibling whose name merely starts with the same text.
//
// A string prefix test would refuse `config-backup` because it starts with
// `config`, which is the same defect the path fence refuses elsewhere.
func TestIsDeniedPathUsesASeparatorBoundary(t *testing.T) {
	base := t.TempDir()
	configDir := filepath.Join(base, "config")
	if err := os.Mkdir(configDir, 0o700); err != nil {
		t.Fatalf("mkdir config: %v", err)
	}
	if err := os.Mkdir(filepath.Join(base, "config-backup"), 0o700); err != nil {
		t.Fatalf("mkdir config-backup: %v", err)
	}

	scope, err := openScope("project", base, []string{configDir}, "", false)
	if err != nil {
		t.Fatalf("openScope = %v, want nil", err)
	}
	defer scope.Close()

	cases := map[string]bool{
		"config":             true,
		"config/identity":    true,
		"config/nested/deep": true,
		"config-backup":      false,
		"config-backup/file": false,
		"visible.txt":        false,
		"":                   false,
	}
	for path, want := range cases {
		if got := scope.isDeniedPath(path); got != want {
			t.Fatalf("isDeniedPath(%q) = %v, want %v", path, got, want)
		}
	}
}

// TestCollectDeniedPrefixesSkipsADenyPathOutsideTheScope checks that a deny path
// the scope cannot address is skipped rather than turned into a prefix that
// matches nothing.
func TestCollectDeniedPrefixesSkipsADenyPathOutsideTheScope(t *testing.T) {
	base := t.TempDir()
	scopeRoot := filepath.Join(base, "project")
	if err := os.Mkdir(scopeRoot, 0o700); err != nil {
		t.Fatalf("mkdir scope: %v", err)
	}
	outside := filepath.Join(base, "elsewhere")
	if err := os.Mkdir(outside, 0o700); err != nil {
		t.Fatalf("mkdir outside: %v", err)
	}

	prefixes, err := collectDeniedPrefixes([]string{outside}, scopeRoot)
	if err != nil {
		t.Fatalf("collectDeniedPrefixes = %v, want nil", err)
	}
	if len(prefixes) != 0 {
		t.Fatalf("collectDeniedPrefixes = %v, want no prefix for a path outside the scope", prefixes)
	}
}

// TestCollectDeniedPrefixesRefusesADeniedScopeRoot checks that a scope whose own
// root is deny-listed fails startup, because such a scope serves nothing and the
// operator should be told rather than left with a Node that denies everything.
func TestCollectDeniedPrefixesRefusesADeniedScopeRoot(t *testing.T) {
	base := t.TempDir()

	if _, err := collectDeniedPrefixes([]string{base}, base); err == nil {
		t.Fatal("collectDeniedPrefixes(scope root denied) = nil error, want a refusal")
	}
}

// TestOptedInScopeWithoutTheDenyEntryReadsTheIdentityFile proves the deny list is
// load-bearing rather than decorative.
//
// The test above asserts that the identity file is refused. That assertion is
// only meaningful if the same read succeeds when the deny entry is absent, so
// this test performs the read without it. If this test ever fails, the refusal
// above is coming from somewhere else and the deny list is not what protects the
// credential.
func TestOptedInScopeWithoutTheDenyEntryReadsTheIdentityFile(t *testing.T) {
	base := t.TempDir()
	configDir := filepath.Join(base, "config")
	if err := os.Mkdir(configDir, 0o700); err != nil {
		t.Fatalf("mkdir config: %v", err)
	}
	writeFile(t, filepath.Join(configDir, "identity"), "node_secret.token_secret")

	root := filesystemRootPath(t)
	scope, err := openScope("whole", root, nil, configDir, true)
	if err != nil {
		t.Fatalf("openScope(opt-in, no deny entry) = %v, want nil", err)
	}
	defer scope.Close()

	attempt := relativeToRoot(t, filepath.Join(configDir, "identity"))
	data, _, err := scope.Read(attempt, 0, 0)
	if err != nil {
		t.Fatalf("Read(%q) = %v, want nil because no deny entry was supplied", attempt, err)
	}
	if string(data) != "node_secret.token_secret" {
		t.Fatalf("Read(%q) = %q, want the identity content", attempt, data)
	}
}
