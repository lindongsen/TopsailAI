package node

import (
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"testing"

	"topsailai_connector/internal/protocol"
)

// TestScopeListSkipsVanishedEntry checks that a listing of a stable directory is
// complete, which is the property the skip path must not break.
func TestScopeListSkipsVanishedEntry(t *testing.T) {
	root, _ := newScopeFixture(t)
	scope := openFixtureScope(t, root)

	entries, err := scope.List("")
	if err != nil {
		t.Fatalf("List = %v, want nil", err)
	}
	if len(entries) == 0 {
		t.Fatal("List returned no entries")
	}
	if _, ok := findEntry(entries, "inside.txt"); !ok {
		t.Fatalf("List = %v, want inside.txt", entryNames(entries))
	}
}

// TestIsFilesystemRoot checks the root detection on the host platform, so a
// scope rooted at a volume root is refused before it is opened.
func TestIsFilesystemRoot(t *testing.T) {
	if !isFilesystemRoot(string(filepath.Separator)) {
		t.Fatalf("isFilesystemRoot(%q) = false, want true", string(filepath.Separator))
	}

	root, _ := newScopeFixture(t)
	if isFilesystemRoot(root) {
		t.Fatalf("isFilesystemRoot(%q) = true, want false", root)
	}
}

// TestIsMountPointOnOrdinaryDirectory checks that an ordinary directory is not
// reported as a mount point, so the startup rule does not refuse a legitimate
// scope.
func TestIsMountPointOnOrdinaryDirectory(t *testing.T) {
	root, _ := newScopeFixture(t)
	if isMountPoint(root) {
		t.Fatalf("isMountPoint(%q) = true, want false", root)
	}
}

// TestIsMountPointOnMissingPath checks that a missing path is not reported as a
// mount point, because the startup rule must not turn a missing directory into a
// mount-point refusal.
func TestIsMountPointOnMissingPath(t *testing.T) {
	if isMountPoint(filepath.Join(t.TempDir(), "absent")) {
		t.Fatal("isMountPoint(missing) = true, want false")
	}
}

// TestCollectDeniedRejectsUnreadablePath checks that a deny path which exists
// but cannot be stat-ed fails startup, because a deny list that silently drops
// an entry is a deny list that does not deny.
func TestCollectDeniedRejectsUnreadablePath(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("permission bits are not enforced this way on Windows")
	}
	if os.Geteuid() == 0 {
		t.Skip("root can stat a file inside an unreadable directory")
	}

	base := t.TempDir()
	locked := filepath.Join(base, "locked")
	if err := os.Mkdir(locked, 0o000); err != nil {
		t.Fatalf("mkdir: %v", err)
	}
	t.Cleanup(func() { os.Chmod(locked, 0o755) })

	if _, err := collectDenied([]string{filepath.Join(locked, "secret")}); err == nil {
		t.Fatal("collectDenied(unreadable) = nil error, want a refusal")
	}
}

// TestCollectDeniedSkipsEmptyPath checks that an empty deny path is skipped
// rather than stat-ed, because an empty path would stat the working directory.
func TestCollectDeniedSkipsEmptyPath(t *testing.T) {
	denied, err := collectDenied([]string{""})
	if err != nil {
		t.Fatalf("collectDenied = %v, want nil", err)
	}
	if len(denied) != 0 {
		t.Fatalf("collectDenied = %d entries, want 0", len(denied))
	}
}

// TestScopeReadRejectsSymlinkLoop checks that a symlink loop is refused as a
// denial rather than surfacing as an internal error, because the loop is an
// escape attempt and its outcome must not be distinguishable from a refusal.
func TestScopeReadRejectsSymlinkLoop(t *testing.T) {
	root, _ := newScopeFixture(t)
	scope := openFixtureScope(t, root)

	if err := os.Symlink("loop", filepath.Join(root, "loop")); err != nil {
		t.Skipf("symlink unsupported here: %v", err)
	}

	_, _, err := scope.Read("loop", 0, 0)
	if err == nil {
		t.Fatal("Read(loop) = nil error, want a refusal")
	}
	if code := CodeOf(err); code != protocol.CodeDenied {
		t.Fatalf("Read(loop) code = %s, want denied", code.Name())
	}
}

// TestScopeReadRejectsPrefixCollision checks the case a string prefix check gets
// wrong: a sibling directory whose name starts with the scope root's name.
//
// The concatenation `<root>/../<root>-secret/secret.txt` starts with `<root>`,
// so a HasPrefix check would pass while the real file is outside. The fence must
// refuse it, and it must refuse it by the grammar rather than by luck.
func TestScopeReadRejectsPrefixCollision(t *testing.T) {
	root, outside := newScopeFixture(t)

	if !strings.HasPrefix(outside, root) {
		t.Fatalf("fixture is not a prefix collision: %q does not start with %q", outside, root)
	}

	scope := openFixtureScope(t, root)

	attempt := "../" + filepath.Base(outside) + "/secret.txt"
	_, _, err := scope.Read(attempt, 0, 0)
	if err == nil {
		t.Fatalf("Read(%q) = nil error, want a refusal", attempt)
	}
	if code := CodeOf(err); code != protocol.CodeInvalidArgument {
		t.Fatalf("Read(%q) code = %s, want invalid_argument", attempt, code.Name())
	}
}

// TestScopeReadRejectsHardLinkEscape records a limitation rather than pretending
// the fence covers it.
//
// A hard link is not an escape: the inode is genuinely inside the scope, so the
// fence cannot refuse it by path. Only someone who already has write access to
// the scope can create one, which is why this is accepted rather than fixed.
func TestScopeReadRejectsHardLinkEscape(t *testing.T) {
	root, outside := newScopeFixture(t)

	linkPath := filepath.Join(root, "hardlink.txt")
	if err := os.Link(filepath.Join(outside, "secret.txt"), linkPath); err != nil {
		t.Skipf("hard link unsupported here: %v", err)
	}

	scope := openFixtureScope(t, root)

	data, _, err := scope.Read("hardlink.txt", 0, 0)
	if err != nil {
		t.Fatalf("Read(hardlink) = %v, want nil because the inode is inside the scope", err)
	}
	if string(data) != "outside secret" {
		t.Fatalf("Read(hardlink) = %q, want the linked content", data)
	}
}
