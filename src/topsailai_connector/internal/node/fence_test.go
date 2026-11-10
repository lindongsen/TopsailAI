package node

import (
	"errors"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"topsailai_connector/internal/protocol"
)

// newScopeFixture builds a scope root with a small tree inside it and a
// directory outside it, so an escape attempt has somewhere real to escape to.
//
// The outside directory is a sibling rather than a parent, because a sibling
// named `<root>-secret` is the case a string prefix check gets wrong: the
// concatenation `<root>/../<root>-secret/key` starts with `<root>` while the
// real file is outside.
func newScopeFixture(t *testing.T) (root string, outside string) {
	t.Helper()

	base := t.TempDir()
	root = filepath.Join(base, "scope")
	outside = filepath.Join(base, "scope-secret")

	if err := os.Mkdir(root, 0o755); err != nil {
		t.Fatalf("mkdir root: %v", err)
	}
	if err := os.Mkdir(outside, 0o755); err != nil {
		t.Fatalf("mkdir outside: %v", err)
	}
	if err := os.Mkdir(filepath.Join(root, "sub"), 0o755); err != nil {
		t.Fatalf("mkdir sub: %v", err)
	}

	writeFile(t, filepath.Join(root, "inside.txt"), "inside content")
	writeFile(t, filepath.Join(root, "sub", "nested.txt"), "nested content")
	writeFile(t, filepath.Join(outside, "secret.txt"), "outside secret")
	return root, outside
}

// writeFile writes a file and fails the test if it cannot.
func writeFile(t *testing.T, path string, content string) {
	t.Helper()
	if err := os.WriteFile(path, []byte(content), 0o644); err != nil {
		t.Fatalf("write %q: %v", path, err)
	}
}

// openFixtureScope opens a scope over the fixture root.
func openFixtureScope(t *testing.T, root string) *Scope {
	t.Helper()
	scope, err := OpenScope("project", root, nil)
	if err != nil {
		t.Fatalf("OpenScope(%q) = %v, want nil", root, err)
	}
	t.Cleanup(func() { scope.Close() })
	return scope
}

// TestOpenScopeRejectsBadMappings checks the startup rules. Every one of them
// fails startup rather than warning, because a scope accepted with a caveat is a
// scope whose blast radius nobody measured.
func TestOpenScopeRejectsBadMappings(t *testing.T) {
	root, _ := newScopeFixture(t)

	filePath := filepath.Join(root, "inside.txt")
	symlinkPath := filepath.Join(filepath.Dir(root), "scope-link")
	if err := os.Symlink(root, symlinkPath); err != nil {
		t.Fatalf("symlink: %v", err)
	}

	cases := []struct {
		name string
		path string
		want string
	}{
		{name: "empty path", path: "", want: "empty"},
		{name: "relative path", path: "scope", want: "relative"},
		{name: "missing path", path: filepath.Join(root, "absent"), want: "stat"},
		{name: "file not directory", path: filePath, want: "not a directory"},
		{name: "symlink root", path: symlinkPath, want: "symlink"},
		{name: "filesystem root", path: string(filepath.Separator), want: "filesystem root"},
	}

	for _, testCase := range cases {
		t.Run(testCase.name, func(t *testing.T) {
			scope, err := OpenScope("project", testCase.path, nil)
			if err == nil {
				scope.Close()
				t.Fatalf("OpenScope(%q) = nil error, want a refusal", testCase.path)
			}
			if !strings.Contains(err.Error(), testCase.want) {
				t.Fatalf("OpenScope(%q) = %v, want a message containing %q", testCase.path, err, testCase.want)
			}
		})
	}
}

// TestOpenScopeRejectsBadScopeName checks that the scope name is validated at
// startup, so a name that could never be addressed is refused before the Node
// starts serving.
func TestOpenScopeRejectsBadScopeName(t *testing.T) {
	root, _ := newScopeFixture(t)

	for _, name := range []string{"", "a b", "a/b", "a.b", "-flag", "_under", "a\x00b", strings.Repeat("a", 65)} {
		t.Run(name, func(t *testing.T) {
			scope, err := OpenScope(name, root, nil)
			if err == nil {
				scope.Close()
				t.Fatalf("OpenScope(%q) = nil error, want a refusal", name)
			}
		})
	}
}

// TestOpenScopeRejectsHomeDirectory checks that the home directory is refused,
// because its blast radius is every file the user owns.
func TestOpenScopeRejectsHomeDirectory(t *testing.T) {
	home, err := os.UserHomeDir()
	if err != nil || home == "" {
		t.Skip("no home directory on this host")
	}
	resolved, err := filepath.EvalSymlinks(home)
	if err != nil {
		t.Skipf("cannot resolve home: %v", err)
	}

	scope, err := OpenScope("project", resolved, nil)
	if err == nil {
		scope.Close()
		t.Fatalf("OpenScope(home) = nil error, want a refusal")
	}
	if !strings.Contains(err.Error(), "home directory") {
		t.Fatalf("OpenScope(home) = %v, want a home-directory refusal", err)
	}
}

// TestScopeReadReturnsContent checks the ordinary case, so the fence is not
// proven only by its refusals.
func TestScopeReadReturnsContent(t *testing.T) {
	root, _ := newScopeFixture(t)
	scope := openFixtureScope(t, root)

	data, truncated, err := scope.Read("inside.txt", 0, 0)
	if err != nil {
		t.Fatalf("Read = %v, want nil", err)
	}
	if string(data) != "inside content" {
		t.Fatalf("Read = %q, want %q", data, "inside content")
	}
	if truncated {
		t.Fatal("Read reported truncation for a small file")
	}
}

// TestScopeReadNestedPath checks that a nested path works, so the fence is not
// accidentally limited to the root's immediate children.
func TestScopeReadNestedPath(t *testing.T) {
	root, _ := newScopeFixture(t)
	scope := openFixtureScope(t, root)

	data, _, err := scope.Read("sub/nested.txt", 0, 0)
	if err != nil {
		t.Fatalf("Read = %v, want nil", err)
	}
	if string(data) != "nested content" {
		t.Fatalf("Read = %q, want %q", data, "nested content")
	}
}

// TestScopeReadOffsetAndLength checks that a byte range is honoured, because a
// caller that cannot page through a file has to read all of it.
func TestScopeReadOffsetAndLength(t *testing.T) {
	root, _ := newScopeFixture(t)
	scope := openFixtureScope(t, root)

	data, _, err := scope.Read("inside.txt", 7, 7)
	if err != nil {
		t.Fatalf("Read = %v, want nil", err)
	}
	if string(data) != "content" {
		t.Fatalf("Read = %q, want %q", data, "content")
	}
}

// TestScopeReadRejectsNegativeRange checks that a negative offset or length is
// refused as a malformed request rather than passed to the kernel.
func TestScopeReadRejectsNegativeRange(t *testing.T) {
	root, _ := newScopeFixture(t)
	scope := openFixtureScope(t, root)

	if _, _, err := scope.Read("inside.txt", -1, 0); CodeOf(err) != protocol.CodeInvalidArgument {
		t.Fatalf("Read(offset=-1) = %v, want invalid_argument", err)
	}
	if _, _, err := scope.Read("inside.txt", 0, -1); CodeOf(err) != protocol.CodeInvalidArgument {
		t.Fatalf("Read(length=-1) = %v, want invalid_argument", err)
	}
}

// TestScopeReadRejectsTraversal checks that a traversal attempt is refused by
// the grammar before the filesystem is consulted.
//
// The code must be invalid_argument rather than not_found: os.Root reports
// `../scope-secret/secret.txt` as an escape but `a/../../scope-secret/secret.txt`
// as a missing file, so a grammar that let traversal through would leak which
// form was tried.
func TestScopeReadRejectsTraversal(t *testing.T) {
	root, _ := newScopeFixture(t)
	scope := openFixtureScope(t, root)

	for _, path := range []string{"../scope-secret/secret.txt", "sub/../../scope-secret/secret.txt", ".."} {
		t.Run(path, func(t *testing.T) {
			_, _, err := scope.Read(path, 0, 0)
			if err == nil {
				t.Fatalf("Read(%q) = nil error, want a refusal", path)
			}
			if code := CodeOf(err); code != protocol.CodeInvalidArgument {
				t.Fatalf("Read(%q) code = %s, want invalid_argument", path, code.Name())
			}
		})
	}
}

// TestScopeReadRejectsAbsolutePath checks that an absolute path cannot address
// a file outside the scope, even one that exists.
func TestScopeReadRejectsAbsolutePath(t *testing.T) {
	root, outside := newScopeFixture(t)
	scope := openFixtureScope(t, root)

	absolute := filepath.Join(outside, "secret.txt")
	_, _, err := scope.Read(absolute, 0, 0)
	if err == nil {
		t.Fatalf("Read(%q) = nil error, want a refusal", absolute)
	}
	if code := CodeOf(err); code != protocol.CodeInvalidArgument {
		t.Fatalf("Read(absolute) code = %s, want invalid_argument", code.Name())
	}
}

// TestScopeReadRejectsSymlinkEscape checks that a symlink pointing outside the
// scope cannot be read through.
//
// The refusal comes from the kernel, not from a check in this package: os.Root
// refuses a name whose resolution leaves the root. That is the property the
// fence depends on, so it is asserted rather than assumed.
func TestScopeReadRejectsSymlinkEscape(t *testing.T) {
	root, outside := newScopeFixture(t)
	scope := openFixtureScope(t, root)

	if err := os.Symlink(filepath.Join(outside, "secret.txt"), filepath.Join(root, "outlink")); err != nil {
		t.Fatalf("symlink file: %v", err)
	}
	if err := os.Symlink(outside, filepath.Join(root, "outdir")); err != nil {
		t.Fatalf("symlink dir: %v", err)
	}

	for _, path := range []string{"outlink", "outdir/secret.txt"} {
		t.Run(path, func(t *testing.T) {
			data, _, err := scope.Read(path, 0, 0)
			if err == nil {
				t.Fatalf("Read(%q) = %q, want a refusal", path, data)
			}
			if code := CodeOf(err); code != protocol.CodeDenied {
				t.Fatalf("Read(%q) code = %s, want denied", path, code.Name())
			}
		})
	}
}

// TestScopeReadAllowsSymlinkInside checks that a symlink whose target stays
// inside the scope is readable. Refusing it would be a fence that breaks
// ordinary use without adding safety.
func TestScopeReadAllowsSymlinkInside(t *testing.T) {
	root, _ := newScopeFixture(t)
	scope := openFixtureScope(t, root)

	if err := os.Symlink("inside.txt", filepath.Join(root, "rel_inside")); err != nil {
		t.Fatalf("symlink: %v", err)
	}

	data, _, err := scope.Read("rel_inside", 0, 0)
	if err != nil {
		t.Fatalf("Read(rel_inside) = %v, want nil", err)
	}
	if string(data) != "inside content" {
		t.Fatalf("Read(rel_inside) = %q, want %q", data, "inside content")
	}
}

// TestScopeReadMissingFile checks that a genuinely missing file is reported as
// not_found, so the caller can tell "it is not there" from "you may not".
func TestScopeReadMissingFile(t *testing.T) {
	root, _ := newScopeFixture(t)
	scope := openFixtureScope(t, root)

	_, _, err := scope.Read("absent.txt", 0, 0)
	if err == nil {
		t.Fatal("Read(absent) = nil error, want not_found")
	}
	if code := CodeOf(err); code != protocol.CodeNotFound {
		t.Fatalf("Read(absent) code = %s, want not_found", code.Name())
	}
}

// TestScopeReadRejectsDirectory checks that reading a directory is refused as a
// malformed request rather than returning a kernel error.
func TestScopeReadRejectsDirectory(t *testing.T) {
	root, _ := newScopeFixture(t)
	scope := openFixtureScope(t, root)

	_, _, err := scope.Read("sub", 0, 0)
	if err == nil {
		t.Fatal("Read(directory) = nil error, want a refusal")
	}
	if code := CodeOf(err); code != protocol.CodeInvalidArgument {
		t.Fatalf("Read(directory) code = %s, want invalid_argument", code.Name())
	}
}

// TestScopeReadRejectsEmptyPath checks that the empty path is refused for a
// read. Listing the root is a normal request; reading the root is not a file
// operation at all.
func TestScopeReadRejectsEmptyPath(t *testing.T) {
	root, _ := newScopeFixture(t)
	scope := openFixtureScope(t, root)

	if _, _, err := scope.Read("", 0, 0); CodeOf(err) != protocol.CodeInvalidArgument {
		t.Fatalf("Read(\"\") = %v, want invalid_argument", err)
	}
}

// TestScopeReadCapsResponseSize checks that a file larger than the cap is
// truncated and the truncation is reported, so a caller knows the answer is
// partial instead of assuming it is complete.
func TestScopeReadCapsResponseSize(t *testing.T) {
	root, _ := newScopeFixture(t)
	scope := openFixtureScope(t, root)

	large := strings.Repeat("x", MaxResponseBytes+1024)
	writeFile(t, filepath.Join(root, "large.bin"), large)

	data, truncated, err := scope.Read("large.bin", 0, 0)
	if err != nil {
		t.Fatalf("Read(large) = %v, want nil", err)
	}
	if len(data) != MaxResponseBytes {
		t.Fatalf("Read(large) returned %d bytes, want %d", len(data), MaxResponseBytes)
	}
	if !truncated {
		t.Fatal("Read(large) reported no truncation, want truncated")
	}
}

// TestScopeReadExplicitLengthBelowCap checks that an explicit length smaller
// than the cap is honoured and is not reported as truncation.
func TestScopeReadExplicitLengthBelowCap(t *testing.T) {
	root, _ := newScopeFixture(t)
	scope := openFixtureScope(t, root)

	data, truncated, err := scope.Read("inside.txt", 0, 6)
	if err != nil {
		t.Fatalf("Read = %v, want nil", err)
	}
	if string(data) != "inside" {
		t.Fatalf("Read = %q, want %q", data, "inside")
	}
	if truncated {
		t.Fatal("Read reported truncation for an explicit short length")
	}
}

// TestScopeListRoot checks that the empty path lists the scope root, which is
// the one place the empty path is allowed.
func TestScopeListRoot(t *testing.T) {
	root, _ := newScopeFixture(t)
	scope := openFixtureScope(t, root)

	entries, err := scope.List("")
	if err != nil {
		t.Fatalf("List(\"\") = %v, want nil", err)
	}

	names := entryNames(entries)
	want := []string{"inside.txt", "sub"}
	if strings.Join(names, ",") != strings.Join(want, ",") {
		t.Fatalf("List(\"\") = %v, want %v", names, want)
	}
}

// TestScopeListIsSorted checks that a listing is sorted, so a caller can diff
// two listings and a test does not depend on directory order.
func TestScopeListIsSorted(t *testing.T) {
	root, _ := newScopeFixture(t)
	scope := openFixtureScope(t, root)

	for _, name := range []string{"zebra.txt", "alpha.txt", "mike.txt"} {
		writeFile(t, filepath.Join(root, name), name)
	}

	entries, err := scope.List("")
	if err != nil {
		t.Fatalf("List = %v, want nil", err)
	}

	names := entryNames(entries)
	for index := 1; index < len(names); index++ {
		if names[index-1] > names[index] {
			t.Fatalf("List = %v, want sorted", names)
		}
	}
}

// TestScopeListSubdirectory checks that a subdirectory can be listed.
func TestScopeListSubdirectory(t *testing.T) {
	root, _ := newScopeFixture(t)
	scope := openFixtureScope(t, root)

	entries, err := scope.List("sub")
	if err != nil {
		t.Fatalf("List(sub) = %v, want nil", err)
	}
	if names := entryNames(entries); len(names) != 1 || names[0] != "nested.txt" {
		t.Fatalf("List(sub) = %v, want [nested.txt]", names)
	}
}

// TestScopeListRejectsFile checks that listing a file is refused as a malformed
// request.
func TestScopeListRejectsFile(t *testing.T) {
	root, _ := newScopeFixture(t)
	scope := openFixtureScope(t, root)

	if _, err := scope.List("inside.txt"); CodeOf(err) != protocol.CodeInvalidArgument {
		t.Fatalf("List(file) = %v, want invalid_argument", err)
	}
}

// TestScopeListReportsSymlinkAsSymlink checks that a listed symlink is reported
// as a symlink rather than followed. Following it would answer whether its
// target exists, which is an existence oracle for the whole filesystem.
func TestScopeListReportsSymlinkAsSymlink(t *testing.T) {
	root, outside := newScopeFixture(t)
	scope := openFixtureScope(t, root)

	if err := os.Symlink(filepath.Join(outside, "secret.txt"), filepath.Join(root, "outlink")); err != nil {
		t.Fatalf("symlink: %v", err)
	}

	entries, err := scope.List("")
	if err != nil {
		t.Fatalf("List = %v, want nil", err)
	}

	entry, ok := findEntry(entries, "outlink")
	if !ok {
		t.Fatalf("List = %v, want an entry named outlink", entryNames(entries))
	}
	if entry.Type != "symlink" {
		t.Fatalf("outlink type = %q, want symlink", entry.Type)
	}
	if !entry.IsSymlink {
		t.Fatal("outlink IsSymlink = false, want true")
	}
}

// TestScopeListReportsGrammarRefusedName checks that a file whose name the
// grammar refuses is still reported, with an unknown type, rather than omitted.
// A listing that hides a file is a listing a caller cannot trust.
func TestScopeListReportsGrammarRefusedName(t *testing.T) {
	root, _ := newScopeFixture(t)
	scope := openFixtureScope(t, root)

	// A trailing space is refused by the grammar, so this name can be listed
	// but never addressed.
	refused := filepath.Join(root, "trailing ")
	if err := os.WriteFile(refused, []byte("x"), 0o644); err != nil {
		t.Skipf("filesystem refuses a trailing space: %v", err)
	}

	entries, err := scope.List("")
	if err != nil {
		t.Fatalf("List = %v, want nil", err)
	}

	entry, ok := findEntry(entries, "trailing ")
	if !ok {
		t.Fatalf("List = %v, want an entry named %q", entryNames(entries), "trailing ")
	}
	if entry.Type != "unknown" {
		t.Fatalf("trailing-space entry type = %q, want unknown", entry.Type)
	}
}

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
