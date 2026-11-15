package node

import (
	"os"
	"path/filepath"
	"runtime"
	"testing"
)

// TestSamePathAcceptsEquivalentSpellings checks that two spellings of the same
// directory compare equal.
//
// A trailing separator and a redundant dot segment name the same directory as
// the cleaned form, so a comparison that refuses them refuses a legitimate
// scope. The refusal is worse than it looks: it reports "a scope root must not
// be a symlink" for a path that contains no symlink, which sends the operator
// looking for a link instead of a spelling.
func TestSamePathAcceptsEquivalentSpellings(t *testing.T) {
	base := t.TempDir()
	root := filepath.Join(base, "scope")
	if err := os.Mkdir(root, 0o755); err != nil {
		t.Fatalf("mkdir: %v", err)
	}

	cases := []struct {
		name  string
		left  string
		right string
	}{
		{name: "identical", left: root, right: root},
		{name: "trailing separator", left: root + string(filepath.Separator), right: root},
		{name: "redundant dot segment", left: filepath.Join(root, "."), right: root},
		{name: "redundant separator", left: root + string(filepath.Separator) + string(filepath.Separator), right: root},
	}

	for _, testCase := range cases {
		t.Run(testCase.name, func(t *testing.T) {
			if !samePath(testCase.left, testCase.right) {
				t.Fatalf("samePath(%q, %q) = false, want true", testCase.left, testCase.right)
			}
		})
	}
}

// TestSamePathFollowsPlatformCaseRule checks that the case rule matches the
// filesystem the Node is running on.
//
// Windows compares case-insensitively because its filesystem does, so a
// configured spelling that differs in case from the resolved one names the same
// directory. POSIX compares byte for byte because its filesystem does, so the
// same difference names a directory that may not exist.
func TestSamePathFollowsPlatformCaseRule(t *testing.T) {
	base := t.TempDir()
	root := filepath.Join(base, "Scope")
	if err := os.Mkdir(root, 0o755); err != nil {
		t.Fatalf("mkdir: %v", err)
	}

	otherCase := filepath.Join(base, "scope")
	want := runtime.GOOS == "windows"
	if got := samePath(root, otherCase); got != want {
		t.Fatalf("samePath(%q, %q) = %v on %s, want %v", root, otherCase, got, runtime.GOOS, want)
	}
}

// TestSamePathRejectsDifferentDirectories checks that the comparison still
// distinguishes two directories that really are different, so the fix does not
// turn the check into "always equal".
func TestSamePathRejectsDifferentDirectories(t *testing.T) {
	base := t.TempDir()
	first := filepath.Join(base, "first")
	second := filepath.Join(base, "second")
	for _, path := range []string{first, second} {
		if err := os.Mkdir(path, 0o755); err != nil {
			t.Fatalf("mkdir %q: %v", path, err)
		}
	}

	if samePath(first, second) {
		t.Fatalf("samePath(%q, %q) = true, want false", first, second)
	}
}

// TestSamePathRejectsSymlinkedParent checks that a path reached through a
// symlinked parent is not equal to the path it resolves to.
//
// This is the property the symlink refusal depends on: if the comparison
// reported these two as equal, a scope root reached through a link would be
// accepted, and the link could be repointed after startup.
func TestSamePathRejectsSymlinkedParent(t *testing.T) {
	base := t.TempDir()
	real := filepath.Join(base, "real")
	if err := os.Mkdir(real, 0o755); err != nil {
		t.Fatalf("mkdir: %v", err)
	}
	sub := filepath.Join(real, "sub")
	if err := os.Mkdir(sub, 0o755); err != nil {
		t.Fatalf("mkdir sub: %v", err)
	}

	link := filepath.Join(base, "link")
	mustSymlink(t, real, link)

	throughLink := filepath.Join(link, "sub")
	resolved, err := filepath.EvalSymlinks(throughLink)
	if err != nil {
		t.Skipf("EvalSymlinks unsupported here: %v", err)
	}

	if samePath(resolved, throughLink) {
		t.Fatalf("samePath(%q, %q) = true, want false", resolved, throughLink)
	}
}

// TestOpenScopeAcceptsEquivalentSpellings checks that a legitimate scope is
// accepted when the configured spelling differs from the resolved one.
//
// This is the regression test for the defect: OpenScope compared the configured
// path with its own resolution as raw strings, so a trailing separator or a
// redundant dot segment was refused as a symlink. The bug was not
// Windows-specific, because EvalSymlinks cleans the path on every platform; it
// was simply easier to hit on Windows, where EvalSymlinks also rewrites the
// drive letter and the component case.
func TestOpenScopeAcceptsEquivalentSpellings(t *testing.T) {
	root, _ := newScopeFixture(t)

	cases := []struct {
		name string
		path string
	}{
		{name: "canonical", path: root},
		{name: "trailing separator", path: root + string(filepath.Separator)},
		{name: "redundant dot segment", path: filepath.Join(root, ".")},
	}

	for _, testCase := range cases {
		t.Run(testCase.name, func(t *testing.T) {
			scope, err := OpenScope("project", testCase.path, nil, "")
			if err != nil {
				t.Fatalf("OpenScope(%q) = %v, want nil", testCase.path, err)
			}
			defer scope.Close()

			// The scope must still work, not merely open: a handle that opened
			// the wrong directory would pass an "err == nil" check.
			data, _, err := scope.Read("inside.txt", 0, 0)
			if err != nil {
				t.Fatalf("Read(inside.txt) = %v, want nil", err)
			}
			if string(data) != "inside content" {
				t.Fatalf("Read(inside.txt) = %q, want the fixture content", data)
			}
		})
	}
}

// TestIsHomeDirectoryFollowsPlatformCaseRule checks that the home directory is
// recognised regardless of how its drive letter is spelled.
//
// This is the trap in the fix: making only the symlink comparison
// case-insensitive would let a home directory spelled with a lower-case drive
// letter pass both checks, and the home directory would become a valid scope
// root whose blast radius is every file the user owns.
func TestIsHomeDirectoryFollowsPlatformCaseRule(t *testing.T) {
	home, err := os.UserHomeDir()
	if err != nil || home == "" {
		t.Skip("no home directory on this host")
	}

	if !isHomeDirectory(home) {
		t.Fatalf("isHomeDirectory(%q) = false, want true", home)
	}

	if runtime.GOOS != "windows" {
		// On POSIX a case difference names a different directory, so the
		// lower-case spelling must not be recognised as home.
		return
	}

	lowered := lowerDriveLetter(home)
	if lowered == home {
		t.Skip("home directory has no drive letter to lower")
	}
	if !isHomeDirectory(lowered) {
		t.Fatalf("isHomeDirectory(%q) = false, want true on Windows", lowered)
	}
}

// lowerDriveLetter rewrites a Windows drive letter to lower case, so the test
// can spell the home directory the other way.
func lowerDriveLetter(path string) string {
	if len(path) < 2 || path[1] != ':' {
		return path
	}
	letter := path[0]
	if letter >= 'A' && letter <= 'Z' {
		letter = letter - 'A' + 'a'
	}
	return string(letter) + path[1:]
}
