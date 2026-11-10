package node

import (
	"errors"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"topsailai_connector/internal/protocol"
)

// TestScopeStatUsesLstat checks that stat reports an escaping symlink as a
// symlink instead of refusing it.
//
// Stat must not follow the link: following an escaping link is exactly the
// operation the fence refuses, and a refusal here would tell the caller that the
// target exists outside the scope.
func TestScopeStatUsesLstat(t *testing.T) {
	root, outside := newScopeFixture(t)
	scope := openFixtureScope(t, root)

	target := filepath.Join(outside, "secret.txt")
	if err := os.Symlink(target, filepath.Join(root, "outlink")); err != nil {
		t.Fatalf("symlink: %v", err)
	}

	entry, err := scope.Stat("outlink")
	if err != nil {
		t.Fatalf("Stat(outlink) = %v, want nil", err)
	}
	if entry.Type != "symlink" {
		t.Fatalf("Stat(outlink) type = %q, want symlink", entry.Type)
	}
	if entry.LinkTarget != target {
		t.Fatalf("Stat(outlink) target = %q, want %q", entry.LinkTarget, target)
	}
}

// TestScopeStatReportsFile checks the ordinary case for stat.
func TestScopeStatReportsFile(t *testing.T) {
	root, _ := newScopeFixture(t)
	scope := openFixtureScope(t, root)

	entry, err := scope.Stat("inside.txt")
	if err != nil {
		t.Fatalf("Stat = %v, want nil", err)
	}
	if entry.Name != "inside.txt" {
		t.Fatalf("Stat name = %q, want inside.txt", entry.Name)
	}
	if entry.Type != "file" {
		t.Fatalf("Stat type = %q, want file", entry.Type)
	}
	if entry.Size != int64(len("inside content")) {
		t.Fatalf("Stat size = %d, want %d", entry.Size, len("inside content"))
	}
	if entry.ModifiedAt == 0 {
		t.Fatal("Stat modified_at = 0, want a timestamp")
	}
}

// TestScopeStatRejectsTraversal checks that stat refuses traversal by the
// grammar, so stat cannot be used as an existence oracle for the filesystem.
func TestScopeStatRejectsTraversal(t *testing.T) {
	root, _ := newScopeFixture(t)
	scope := openFixtureScope(t, root)

	for _, path := range []string{"../scope-secret/secret.txt", "..", "/etc/passwd"} {
		t.Run(path, func(t *testing.T) {
			_, err := scope.Stat(path)
			if err == nil {
				t.Fatalf("Stat(%q) = nil error, want a refusal", path)
			}
			if code := CodeOf(err); code != protocol.CodeInvalidArgument {
				t.Fatalf("Stat(%q) code = %s, want invalid_argument", path, code.Name())
			}
		})
	}
}

// TestScopeStatMissingFile checks that stat reports a missing file as
// not_found.
func TestScopeStatMissingFile(t *testing.T) {
	root, _ := newScopeFixture(t)
	scope := openFixtureScope(t, root)

	if _, err := scope.Stat("absent.txt"); CodeOf(err) != protocol.CodeNotFound {
		t.Fatalf("Stat(absent) = %v, want not_found", err)
	}
}

// TestScopeDenyListByIdentity checks that the Node's own files are refused by
// identity rather than by name.
//
// A hard link shares the inode, so a deny list compared by name would miss it
// while a comparison by identity catches it. This is the case that makes the
// deny list worth having.
func TestScopeDenyListByIdentity(t *testing.T) {
	root, _ := newScopeFixture(t)

	secretPath := filepath.Join(filepath.Dir(root), "node-secret")
	writeFile(t, secretPath, "node secret value")

	linkPath := filepath.Join(root, "innocent.txt")
	if err := os.Link(secretPath, linkPath); err != nil {
		t.Skipf("hard link unsupported here: %v", err)
	}

	scope, err := OpenScope("project", root, []string{secretPath})
	if err != nil {
		t.Fatalf("OpenScope = %v, want nil", err)
	}
	defer scope.Close()

	if _, _, err := scope.Read("innocent.txt", 0, 0); CodeOf(err) != protocol.CodeDenied {
		t.Fatalf("Read(hard link to denied file) = %v, want denied", err)
	}
	if _, err := scope.Stat("innocent.txt"); CodeOf(err) != protocol.CodeDenied {
		t.Fatalf("Stat(hard link to denied file) = %v, want denied", err)
	}
}

// TestScopeDenyListSkipsMissingPath checks that a deny path that does not exist
// is skipped rather than refused, because a Node that has not written its
// identity file yet must still be able to start.
func TestScopeDenyListSkipsMissingPath(t *testing.T) {
	root, _ := newScopeFixture(t)

	scope, err := OpenScope("project", root, []string{filepath.Join(root, "absent-secret")})
	if err != nil {
		t.Fatalf("OpenScope = %v, want nil", err)
	}
	defer scope.Close()

	if _, _, err := scope.Read("inside.txt", 0, 0); err != nil {
		t.Fatalf("Read = %v, want nil", err)
	}
}

// TestScopeDenyListDoesNotDenyUnrelatedFile checks that the deny list does not
// over-reach: a file that merely sits beside a denied file is still readable.
func TestScopeDenyListDoesNotDenyUnrelatedFile(t *testing.T) {
	root, _ := newScopeFixture(t)

	secretPath := filepath.Join(filepath.Dir(root), "node-secret")
	writeFile(t, secretPath, "node secret value")

	scope, err := OpenScope("project", root, []string{secretPath})
	if err != nil {
		t.Fatalf("OpenScope = %v, want nil", err)
	}
	defer scope.Close()

	if _, _, err := scope.Read("inside.txt", 0, 0); err != nil {
		t.Fatalf("Read(inside.txt) = %v, want nil", err)
	}
}

// TestClassifyOpenErrorIsFailClosed checks that only a missing file becomes
// not_found and every other failure becomes denied. An error nobody classified
// must be a refusal, never a success.
func TestClassifyOpenErrorIsFailClosed(t *testing.T) {
	cases := []struct {
		name string
		err  error
		want protocol.Code
	}{
		{name: "not exist", err: os.ErrNotExist, want: protocol.CodeNotFound},
		{name: "wrapped not exist", err: &os.PathError{Op: "open", Path: "x", Err: os.ErrNotExist}, want: protocol.CodeNotFound},
		{name: "permission", err: os.ErrPermission, want: protocol.CodeDenied},
		{name: "escape", err: errors.New("path escapes from parent"), want: protocol.CodeDenied},
		{name: "unknown", err: errors.New("something else"), want: protocol.CodeDenied},
	}

	for _, testCase := range cases {
		t.Run(testCase.name, func(t *testing.T) {
			if got := classifyOpenError(testCase.err).Code; got != testCase.want {
				t.Fatalf("classifyOpenError(%v) = %s, want %s", testCase.err, got.Name(), testCase.want.Name())
			}
		})
	}
}

// TestCodeOfUnclassifiedError checks that an error which is not a fence error
// is reported as internal, because an unclassified failure must never be
// presented as a policy decision.
func TestCodeOfUnclassifiedError(t *testing.T) {
	if got := CodeOf(errors.New("plain")); got != protocol.CodeInternal {
		t.Fatalf("CodeOf(plain) = %s, want internal", got.Name())
	}
	if got := CodeOf(nil); got != protocol.CodeInternal {
		t.Fatalf("CodeOf(nil) = %s, want internal", got.Name())
	}
}

// TestFenceErrorDoesNotLeakPathInCode checks that a fence error carries a code
// and keeps its detail separate, so the detail can be logged while the code is
// returned.
func TestFenceErrorDoesNotLeakPathInCode(t *testing.T) {
	err := newError(protocol.CodeDenied, "path %q is outside", "/etc/passwd")
	if err.Code != protocol.CodeDenied {
		t.Fatalf("Code = %s, want denied", err.Code.Name())
	}
	if !strings.Contains(err.Detail, "/etc/passwd") {
		t.Fatalf("Detail = %q, want the path for the log", err.Detail)
	}
	if !strings.Contains(err.Error(), "denied") {
		t.Fatalf("Error() = %q, want the code name", err.Error())
	}
}

// TestScopeResolvedPathIsAbsolute checks that the resolved path is absolute, so
// the startup report names a real directory rather than a relative one that
// resolves differently per launch.
func TestScopeResolvedPathIsAbsolute(t *testing.T) {
	root, _ := newScopeFixture(t)
	scope := openFixtureScope(t, root)

	if !filepath.IsAbs(scope.ResolvedPath()) {
		t.Fatalf("ResolvedPath = %q, want an absolute path", scope.ResolvedPath())
	}
	if scope.Name() != "project" {
		t.Fatalf("Name = %q, want project", scope.Name())
	}
}

// TestScopeCloseIsIdempotent checks that closing a scope twice does not panic,
// because a shutdown path may close scopes it did not open.
func TestScopeCloseIsIdempotent(t *testing.T) {
	root, _ := newScopeFixture(t)
	scope, err := OpenScope("project", root, nil)
	if err != nil {
		t.Fatalf("OpenScope = %v, want nil", err)
	}
	if err := scope.Close(); err != nil {
		t.Fatalf("Close = %v, want nil", err)
	}
	if err := scope.Close(); err != nil {
		t.Fatalf("second Close = %v, want nil", err)
	}
}

// TestTypeOfNamesEveryKind checks the small stable vocabulary a caller branches
// on, so a caller never has to parse a mode string.
func TestTypeOfNamesEveryKind(t *testing.T) {
	root, _ := newScopeFixture(t)
	scope := openFixtureScope(t, root)

	if err := os.Symlink("inside.txt", filepath.Join(root, "link")); err != nil {
		t.Fatalf("symlink: %v", err)
	}

	cases := map[string]string{
		"inside.txt": "file",
		"sub":        "dir",
		"link":       "symlink",
	}

	for path, want := range cases {
		t.Run(path, func(t *testing.T) {
			entry, err := scope.Stat(path)
			if err != nil {
				t.Fatalf("Stat(%q) = %v, want nil", path, err)
			}
			if entry.Type != want {
				t.Fatalf("Stat(%q) type = %q, want %q", path, entry.Type, want)
			}
		})
	}
}

// TestModifiedAtOfRoundTrip checks that the timestamp helper agrees with the
// entry it reads, so a caller converting the value gets the same instant.
func TestModifiedAtOfRoundTrip(t *testing.T) {
	root, _ := newScopeFixture(t)
	scope := openFixtureScope(t, root)

	entry, err := scope.Stat("inside.txt")
	if err != nil {
		t.Fatalf("Stat = %v, want nil", err)
	}
	if got := ModifiedAtOf(entry).UnixMilli(); got != entry.ModifiedAt {
		t.Fatalf("ModifiedAtOf = %d, want %d", got, entry.ModifiedAt)
	}
}

// entryNames returns the names of a listing in order.
func entryNames(entries []Entry) []string {
	names := make([]string, 0, len(entries))
	for _, entry := range entries {
		names = append(names, entry.Name)
	}
	return names
}

// findEntry returns the entry with the given name.
func findEntry(entries []Entry, name string) (Entry, bool) {
	for _, entry := range entries {
		if entry.Name == name {
			return entry, true
		}
	}
	return Entry{}, false
}
