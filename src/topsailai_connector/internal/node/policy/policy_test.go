package policy

import (
	"errors"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"topsailai_connector/internal/security"
)

// validDocument is the smallest policy that defines one scope and grants one
// permission. Every test starts from it and breaks one thing.
const validDocument = `
version: 1
scopes:
  project:
    path: /home/me/project
grants:
  - scope: project
    permissions: [read]
`

// mustParse parses a document and fails the test if it does not parse.
func mustParse(t *testing.T, document string) *Policy {
	t.Helper()
	loaded, err := ParseBytes([]byte(document))
	if err != nil {
		t.Fatalf("ParseBytes = %v, want nil", err)
	}
	return loaded
}

// TestParseAcceptsValidDocument checks the ordinary case, so the loader is not
// proven only by its refusals.
func TestParseAcceptsValidDocument(t *testing.T) {
	loaded := mustParse(t, validDocument)

	path, ok := loaded.ScopePath("project")
	if !ok {
		t.Fatal("ScopePath(project) = false, want true")
	}
	if path != "/home/me/project" {
		t.Fatalf("ScopePath(project) = %q, want /home/me/project", path)
	}
	if !loaded.Allows("project", security.PermissionRead) {
		t.Fatal("Allows(project, read) = false, want true")
	}
}

// TestParseRequiresVersion checks that a policy without a version is refused,
// because a policy that cannot be migrated is a policy that will be read as the
// wrong format.
func TestParseRequiresVersion(t *testing.T) {
	document := `
scopes:
  project:
    path: /home/me/project
`
	_, err := ParseBytes([]byte(document))
	if err == nil {
		t.Fatal("ParseBytes(no version) = nil error, want a refusal")
	}
	if !strings.Contains(err.Error(), "version is required") {
		t.Fatalf("ParseBytes(no version) = %v, want a version refusal", err)
	}
}

// TestParseRejectsUnknownVersion checks that a future version is refused rather
// than read as if it were the current one.
func TestParseRejectsUnknownVersion(t *testing.T) {
	document := strings.Replace(validDocument, "version: 1", "version: 2", 1)
	_, err := ParseBytes([]byte(document))
	if err == nil {
		t.Fatal("ParseBytes(version 2) = nil error, want a refusal")
	}
	if !strings.Contains(err.Error(), "not supported") {
		t.Fatalf("ParseBytes(version 2) = %v, want an unsupported-version refusal", err)
	}
}

// TestParseRejectsUnknownKey checks that an unknown key is an error. A typo in a
// security configuration that is silently ignored is worse than a crash.
func TestParseRejectsUnknownKey(t *testing.T) {
	document := validDocument + "\nallow_all: true\n"
	_, err := ParseBytes([]byte(document))
	if err == nil {
		t.Fatal("ParseBytes(unknown key) = nil error, want a refusal")
	}
}

// TestParseRejectsUnknownScopeKey checks that an unknown key inside a scope is
// refused too, so the strictness is not only at the top level.
func TestParseRejectsUnknownScopeKey(t *testing.T) {
	document := `
version: 1
scopes:
  project:
    path: /home/me/project
    writable: true
`
	_, err := ParseBytes([]byte(document))
	if err == nil {
		t.Fatal("ParseBytes(unknown scope key) = nil error, want a refusal")
	}
}

// TestParseRejectsScopeWithoutPath checks that a scope without a path is
// refused, because a scope that maps to nothing cannot be served.
func TestParseRejectsScopeWithoutPath(t *testing.T) {
	document := `
version: 1
scopes:
  project: {}
`
	_, err := ParseBytes([]byte(document))
	if err == nil {
		t.Fatal("ParseBytes(no path) = nil error, want a refusal")
	}
	if !strings.Contains(err.Error(), "path is required") {
		t.Fatalf("ParseBytes(no path) = %v, want a path refusal", err)
	}
}

// TestParseRejectsBadScopeName checks that a scope name is validated at load
// time, so a name that could never be addressed is refused before the Node
// starts serving.
func TestParseRejectsBadScopeName(t *testing.T) {
	names := []string{"a b", "a/b", "a.b", "-flag", "_under", "a:b", "a\x00b"}

	for _, name := range names {
		t.Run(name, func(t *testing.T) {
			document := "version: 1\nscopes:\n  \"" + name + "\":\n    path: /home/me/project\n"
			_, err := ParseBytes([]byte(document))
			if err == nil {
				t.Fatalf("ParseBytes(scope %q) = nil error, want a refusal", name)
			}
		})
	}
}

// TestParseRejectsGrantOnUndefinedScope checks that a grant naming an undefined
// scope is an error rather than a silent no-op, because a typo would otherwise
// look like a working policy.
func TestParseRejectsGrantOnUndefinedScope(t *testing.T) {
	document := `
version: 1
scopes:
  project:
    path: /home/me/project
grants:
  - scope: projct
    permissions: [read]
`
	_, err := ParseBytes([]byte(document))
	if err == nil {
		t.Fatal("ParseBytes(undefined scope) = nil error, want a refusal")
	}
	if !strings.Contains(err.Error(), "not defined") {
		t.Fatalf("ParseBytes(undefined scope) = %v, want an undefined-scope refusal", err)
	}
}

// TestParseRejectsUnknownPermission checks that an unknown permission string is
// an error, because a guess in an authorization check is a grant.
func TestParseRejectsUnknownPermission(t *testing.T) {
	for _, permission := range []string{"admin", "READ", "read ", "*", ""} {
		t.Run(permission, func(t *testing.T) {
			document := `
version: 1
scopes:
  project:
    path: /home/me/project
grants:
  - scope: project
    permissions: ["` + permission + `"]
`
			_, err := ParseBytes([]byte(document))
			if err == nil {
				t.Fatalf("ParseBytes(permission %q) = nil error, want a refusal", permission)
			}
		})
	}
}

// TestParseRejectsDuplicatePermission checks that a permission listed twice is
// refused rather than collapsed, because a policy that says the same thing twice
// is a policy whose author was not reading what they wrote.
func TestParseRejectsDuplicatePermission(t *testing.T) {
	document := `
version: 1
scopes:
  project:
    path: /home/me/project
grants:
  - scope: project
    permissions: [read, read]
`
	_, err := ParseBytes([]byte(document))
	if err == nil {
		t.Fatal("ParseBytes(duplicate permission) = nil error, want a refusal")
	}
	if !strings.Contains(err.Error(), "twice") {
		t.Fatalf("ParseBytes(duplicate permission) = %v, want a duplicate refusal", err)
	}
}

// TestParseAcceptsEmptyGrants checks that an empty grants list is valid and
// refuses everything. A policy that defines scopes but grants nothing is a
// legitimate way to start a Node before any caller is authorized.
func TestParseAcceptsEmptyGrants(t *testing.T) {
	document := `
version: 1
scopes:
  project:
    path: /home/me/project
grants: []
`
	loaded := mustParse(t, document)

	if loaded.Allows("project", security.PermissionRead) {
		t.Fatal("Allows(project, read) = true, want false for an empty grant list")
	}
	if names := loaded.ScopeNames(); len(names) != 1 || names[0] != "project" {
		t.Fatalf("ScopeNames = %v, want [project]", names)
	}
}

// TestParseAcceptsNoGrantsKey checks that a policy with no grants key at all is
// valid and refuses everything, because the absence of a grant is the absence of
// authority rather than a reason to fail.
func TestParseAcceptsNoGrantsKey(t *testing.T) {
	document := `
version: 1
scopes:
  project:
    path: /home/me/project
`
	loaded := mustParse(t, document)

	if loaded.Allows("project", security.PermissionRead) {
		t.Fatal("Allows(project, read) = true, want false when no grant exists")
	}
}

// TestAllowsIsFalseForUndefinedScope checks that an undefined scope is refused
// rather than reported as an error, so a caller cannot tell "this scope does not
// exist" from "you may not use it": that difference is a scope-name oracle.
func TestAllowsIsFalseForUndefinedScope(t *testing.T) {
	loaded := mustParse(t, validDocument)

	if loaded.Allows("scratch", security.PermissionRead) {
		t.Fatal("Allows(undefined scope) = true, want false")
	}
	if _, ok := loaded.ScopePath("scratch"); ok {
		t.Fatal("ScopePath(undefined scope) = true, want false")
	}
}

// TestAllowsDoesNotLeakAcrossScopes checks that a permission granted on one
// scope is not held on another, because a grant that leaked across scopes would
// make the policy mean something its author did not write.
func TestAllowsDoesNotLeakAcrossScopes(t *testing.T) {
	document := `
version: 1
scopes:
  project:
    path: /home/me/project
  scratch:
    path: /home/me/scratch
grants:
  - scope: project
    permissions: [read]
`
	loaded := mustParse(t, document)

	if !loaded.Allows("project", security.PermissionRead) {
		t.Fatal("Allows(project, read) = false, want true")
	}
	if loaded.Allows("scratch", security.PermissionRead) {
		t.Fatal("Allows(scratch, read) = true, want false")
	}
}

// TestAllowsDoesNotImplyPermissions checks that each permission is separate, so
// a read grant never authorizes a list, a stat, a write or an exec.
func TestAllowsDoesNotImplyPermissions(t *testing.T) {
	loaded := mustParse(t, validDocument)

	for _, permission := range []security.Permission{
		security.PermissionList,
		security.PermissionStat,
		security.PermissionWrite,
		security.PermissionExec,
	} {
		if loaded.Allows("project", permission) {
			t.Fatalf("Allows(project, %q) = true, want false", permission)
		}
	}
}

// TestAllowsCombinesGrantsOnOneScope checks that two grants on the same scope
// combine, so a policy can be split by permission instead of repeated.
func TestAllowsCombinesGrantsOnOneScope(t *testing.T) {
	document := `
version: 1
scopes:
  project:
    path: /home/me/project
grants:
  - scope: project
    permissions: [read]
  - scope: project
    permissions: [list]
`
	loaded := mustParse(t, document)

	if !loaded.Allows("project", security.PermissionRead) {
		t.Fatal("Allows(project, read) = false, want true")
	}
	if !loaded.Allows("project", security.PermissionList) {
		t.Fatal("Allows(project, list) = false, want true")
	}
	if loaded.Allows("project", security.PermissionStat) {
		t.Fatal("Allows(project, stat) = true, want false")
	}
}

// TestScopeNamesAreSorted checks that the scope list is sorted, so a startup
// report and a test are both stable.
func TestScopeNamesAreSorted(t *testing.T) {
	document := `
version: 1
scopes:
  zebra:
    path: /home/me/zebra
  alpha:
    path: /home/me/alpha
  mike:
    path: /home/me/mike
`
	loaded := mustParse(t, document)

	names := loaded.ScopeNames()
	want := []security.Scope{"alpha", "mike", "zebra"}
	for index := range want {
		if names[index] != want[index] {
			t.Fatalf("ScopeNames = %v, want %v", names, want)
		}
	}
}

// TestGrantsReturnsCopy checks that the grant list is copied, so a caller cannot
// mutate the policy it was handed.
func TestGrantsReturnsCopy(t *testing.T) {
	loaded := mustParse(t, validDocument)

	grants := loaded.Grants()
	if len(grants) != 1 {
		t.Fatalf("Grants = %d entries, want 1", len(grants))
	}
	grants[0].Scope = "tampered"

	if !loaded.Allows("project", security.PermissionRead) {
		t.Fatal("Allows(project, read) = false after a caller mutated the returned slice")
	}
}

// TestParseBytesRejectsEmptyDocument checks that an empty file is refused rather
// than read as an empty policy. An empty policy refuses everything, which looks
// like a working Node that denies every request.
func TestParseBytesRejectsEmptyDocument(t *testing.T) {
	_, err := ParseBytes([]byte(""))
	if err == nil {
		t.Fatal("ParseBytes(empty) = nil error, want a refusal")
	}
	if !strings.Contains(err.Error(), "empty") {
		t.Fatalf("ParseBytes(empty) = %v, want an empty-file refusal", err)
	}
}

// TestParseBytesRejectsMultipleDocuments checks that a second YAML document is
// refused, because it would be silently ignored and a policy that is half-read
// is a policy nobody can reason about.
func TestParseBytesRejectsMultipleDocuments(t *testing.T) {
	document := validDocument + "\n---\nversion: 1\n"
	_, err := ParseBytes([]byte(document))
	if err == nil {
		t.Fatal("ParseBytes(two documents) = nil error, want a refusal")
	}
	if !strings.Contains(err.Error(), "more than one document") {
		t.Fatalf("ParseBytes(two documents) = %v, want a multi-document refusal", err)
	}
}

// TestParseBytesRejectsMalformedYAML checks that a syntax error is reported as a
// decode failure rather than being read as an empty policy.
func TestParseBytesRejectsMalformedYAML(t *testing.T) {
	_, err := ParseBytes([]byte("version: [unclosed\n"))
	if err == nil {
		t.Fatal("ParseBytes(malformed) = nil error, want a refusal")
	}
}

// TestLoadReadsFile checks the ordinary file path.
func TestLoadReadsFile(t *testing.T) {
	path := writePolicy(t, validDocument)

	loaded, err := Load(path)
	if err != nil {
		t.Fatalf("Load = %v, want nil", err)
	}
	if !loaded.Allows("project", security.PermissionRead) {
		t.Fatal("Allows(project, read) = false, want true")
	}
}

// TestLoadRejectsMissingFile checks that a missing file is a distinct error and
// fails startup, because an implicit allow-all is exactly what a missing
// configuration must never become.
func TestLoadRejectsMissingFile(t *testing.T) {
	_, err := Load(filepath.Join(t.TempDir(), "absent.yaml"))
	if err == nil {
		t.Fatal("Load(missing) = nil error, want a refusal")
	}
	if !errors.Is(err, ErrMissingFile) {
		t.Fatalf("Load(missing) = %v, want ErrMissingFile", err)
	}
}

// TestLoadRejectsEmptyPath checks that an empty path is refused rather than
// stat-ing the working directory.
func TestLoadRejectsEmptyPath(t *testing.T) {
	if _, err := Load(""); err == nil {
		t.Fatal("Load(\"\") = nil error, want a refusal")
	}
}

// TestLoadRejectsDirectory checks that a directory is refused rather than read
// as a file.
func TestLoadRejectsDirectory(t *testing.T) {
	if _, err := Load(t.TempDir()); err == nil {
		t.Fatal("Load(directory) = nil error, want a refusal")
	}
}

// TestLoadRejectsOversizedFile checks that a file larger than the cap is refused
// before it is parsed, because reading it into memory before deciding that is the
// wrong order.
func TestLoadRejectsOversizedFile(t *testing.T) {
	path := filepath.Join(t.TempDir(), "large.yaml")
	content := validDocument + "\n# " + strings.Repeat("x", MaxPolicyBytes) + "\n"
	if err := os.WriteFile(path, []byte(content), 0o644); err != nil {
		t.Fatalf("write: %v", err)
	}

	_, err := Load(path)
	if err == nil {
		t.Fatal("Load(oversized) = nil error, want a refusal")
	}
	if !strings.Contains(err.Error(), "want at most") {
		t.Fatalf("Load(oversized) = %v, want a size refusal", err)
	}
}

// writePolicy writes a policy document to a temporary file and returns its path.
func writePolicy(t *testing.T, document string) string {
	t.Helper()
	path := filepath.Join(t.TempDir(), "policy.yaml")
	if err := os.WriteFile(path, []byte(document), 0o644); err != nil {
		t.Fatalf("write policy: %v", err)
	}
	return path
}
