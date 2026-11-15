package node

import (
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

// mustSymlink creates a symlink and skips the test when the platform cannot.
//
// A successful os.Symlink call is not proof the link exists: an unprivileged
// Windows account fails outright, and some environments report success while
// creating nothing. The link is therefore read back with Lstat before the test
// continues, so a platform that cannot represent a symlink skips instead of
// failing. A failure would report a missing privilege as a defect in the fence,
// which is the one thing a security test must never do.
func mustSymlink(t *testing.T, target string, link string) {
	t.Helper()

	if err := os.Symlink(target, link); err != nil {
		t.Skipf("symlink unsupported here: %v", err)
	}
	info, err := os.Lstat(link)
	if err != nil {
		t.Skipf("symlink was not created here: %v", err)
	}
	if info.Mode()&os.ModeSymlink == 0 {
		t.Skipf("created entry %q is not a symlink here", link)
	}
}

// openFixtureScope opens a scope over the fixture root.
func openFixtureScope(t *testing.T, root string) *Scope {
	t.Helper()
	scope, err := OpenScope("project", root, nil, "")
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

	cases := []struct {
		name string
		path string
		want string
	}{
		{name: "empty path", path: "", want: "empty"},
		{name: "relative path", path: "scope", want: "relative"},
		{name: "missing path", path: filepath.Join(root, "absent"), want: "stat"},
		{name: "file not directory", path: filePath, want: "not a directory"},
		{name: "filesystem root", path: filesystemRootPath(t), want: "filesystem root"},
	}

	for _, testCase := range cases {
		t.Run(testCase.name, func(t *testing.T) {
			scope, err := OpenScope("project", testCase.path, nil, "")
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

// TestOpenScopeRejectsSymlinkRoot checks that a scope root reached through a
// symlink is refused, because the link could be repointed after startup and the
// scope would silently mean a different directory.
//
// The case is separate from TestOpenScopeRejectsBadMappings because creating a
// symlink needs a privilege on Windows that an ordinary account does not have.
// A test that cannot create its fixture must skip, not fail: a failure would
// report a missing privilege as a defect in the fence.
func TestOpenScopeRejectsSymlinkRoot(t *testing.T) {
	root, _ := newScopeFixture(t)

	symlinkPath := filepath.Join(filepath.Dir(root), "scope-link")
	mustSymlink(t, root, symlinkPath)

	scope, err := OpenScope("project", symlinkPath, nil, "")
	if err == nil {
		scope.Close()
		t.Fatalf("OpenScope(%q) = nil error, want a refusal", symlinkPath)
	}
	if !strings.Contains(err.Error(), "symlink") {
		t.Fatalf("OpenScope(%q) = %v, want a message containing %q", symlinkPath, err, "symlink")
	}
}

// filesystemRootPath returns the root of the filesystem the test is running on.
//
// The root is derived from the working directory rather than written as a
// separator, because a bare separator is not an absolute path on Windows: `\` is
// drive-relative, so it would be refused as a relative path and the
// filesystem-root rule would never be reached.
func filesystemRootPath(t *testing.T) string {
	t.Helper()

	workingDirectory, err := os.Getwd()
	if err != nil {
		t.Fatalf("getwd: %v", err)
	}
	volume := filepath.VolumeName(workingDirectory)
	root := volume + string(filepath.Separator)
	if !filepath.IsAbs(root) {
		t.Fatalf("derived root %q is not absolute", root)
	}
	return root
}

// TestOpenScopeRejectsBadScopeName checks that the scope name is validated at
// startup, so a name that could never be addressed is refused before the Node
// starts serving.
func TestOpenScopeRejectsBadScopeName(t *testing.T) {
	root, _ := newScopeFixture(t)

	for _, name := range []string{"", "a b", "a/b", "a.b", "-flag", "_under", "a\x00b", strings.Repeat("a", 65)} {
		t.Run(name, func(t *testing.T) {
			scope, err := OpenScope(name, root, nil, "")
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

	scope, err := OpenScope("project", resolved, nil, "")
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

	mustSymlink(t, filepath.Join(outside, "secret.txt"), filepath.Join(root, "outlink"))
	mustSymlink(t, outside, filepath.Join(root, "outdir"))

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

	mustSymlink(t, "inside.txt", filepath.Join(root, "rel_inside"))

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

	mustSymlink(t, filepath.Join(outside, "secret.txt"), filepath.Join(root, "outlink"))

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
	const refusedName = "trailing "
	refused := filepath.Join(root, refusedName)
	if err := os.WriteFile(refused, []byte("x"), 0o644); err != nil {
		t.Skipf("filesystem refuses a trailing space: %v", err)
	}

	// A successful write is not proof the name survived: Windows strips a
	// trailing space, so the file is created as "trailing" and the write
	// returns nil. The name must be read back before the listing is asserted,
	// otherwise the test fails on a platform that cannot represent the name
	// rather than on a listing that hides it.
	if !directoryHasName(t, root, refusedName) {
		t.Skipf("filesystem strips a trailing space, so the name cannot exist here")
	}

	entries, err := scope.List("")
	if err != nil {
		t.Fatalf("List = %v, want nil", err)
	}

	entry, ok := findEntry(entries, refusedName)
	if !ok {
		t.Fatalf("List = %v, want an entry named %q", entryNames(entries), refusedName)
	}
	if entry.Type != "unknown" {
		t.Fatalf("trailing-space entry type = %q, want unknown", entry.Type)
	}
}

// directoryHasName reports whether a directory holds an entry with exactly this
// name, so a test can tell "the name was created" from "the name was silently
// rewritten by the filesystem".
func directoryHasName(t *testing.T, directory string, name string) bool {
	t.Helper()

	entries, err := os.ReadDir(directory)
	if err != nil {
		t.Fatalf("readdir %q: %v", directory, err)
	}
	for _, entry := range entries {
		if entry.Name() == name {
			return true
		}
	}
	return false
}
