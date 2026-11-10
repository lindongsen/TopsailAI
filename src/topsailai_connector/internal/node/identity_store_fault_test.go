package node

import (
	"os"
	"path/filepath"
	"strings"
	"testing"

	"topsailai_connector/internal/security"
)

// This file injects real failures into SaveIdentity and asserts the security
// promise its doc comment makes: "The temporary file is removed on every failure
// path, so a failed save does not leave a stray file holding a credential."
//
// A stray temporary file is not a cosmetic problem. It holds a node token that
// never expires, in a directory the Node owns, under a name the operator does not
// know to look for. So every failure case here asserts two things: the error names
// the path and the action, and no temporary file survives.
//
// What this file adds is assertions, not coverage. Both reachable failure
// branches were already exercised by store_extra_test.go, which fails the rename
// the same way; measured before and after, SaveIdentity stays at 69.0%. What was
// missing was the evidence: the existing test checks that no temporary file
// survives, but not that the error names the path and the action, not that the
// occupying directory is left intact, and not that the identity path holds nothing
// that parses as an identity afterwards. Those are the assertions added here.
//
// Which branches are reached, and which are not:
//
//   - CreateTemp failure: reached by making the parent directory a regular file.
//     The kernel refuses with ENOTDIR, so no temporary file is ever created.
//   - Rename failure: reached by making the rename target a non-empty directory.
//     The kernel refuses with EEXIST, and this is the case that matters most,
//     because the temporary file already exists and holds the credential when the
//     failure happens.
//   - Chmod, WriteString, Sync and Close failures: NOT reached. os.CreateTemp
//     always returns a fresh file opened for writing, so none of those four can
//     fail on a file this code just created. Reaching them would need a seam that
//     replaces os.CreateTemp with a package-level variable, which is a mutable
//     global in production code; the cleanup path they exercise is the same
//     cleanup function the rename case already proves, so the seam would buy a
//     different error string rather than different evidence. They are left
//     uncovered deliberately rather than faked.
//
// One injection that looks plausible but is not used: making the directory
// read-only with chmod 0500. It does not work here. The test suite runs as root in
// this environment, and root bypasses the permission bits, so the call would
// succeed and the test would pass without ever reaching the failure branch. That
// is the exact shape of a fake injection, so it is avoided.

// temporaryIdentityFiles returns the temporary files SaveIdentity would leave in a
// directory. The pattern matches the one SaveIdentity passes to os.CreateTemp.
func temporaryIdentityFiles(t *testing.T, directory string) []string {
	t.Helper()
	matches, err := filepath.Glob(filepath.Join(directory, ".identity-*"))
	if err != nil {
		t.Fatalf("glob temporary identity files in %q: %v", directory, err)
	}
	return matches
}

// assertNoTemporaryIdentityFile fails when a failed save left a credential behind.
func assertNoTemporaryIdentityFile(t *testing.T, directory string) {
	t.Helper()
	if stray := temporaryIdentityFiles(t, directory); len(stray) != 0 {
		t.Fatalf("a failed save left %v behind, want no temporary file holding a credential", stray)
	}
}

// newValidIdentity returns a pair that passes validation, so a test that wants to
// reach a disk failure is not stopped by the validation guards first.
func newValidIdentity(t *testing.T) security.NodeIdentity {
	t.Helper()
	identity, err := security.NewNodeIdentity()
	if err != nil {
		t.Fatalf("NewNodeIdentity() = %v, want nil", err)
	}
	return identity
}

// TestSaveIdentityReportsACreateTempFailure checks that a directory that cannot
// hold a temporary file is reported with the directory and the action, and that
// nothing is written.
func TestSaveIdentityReportsACreateTempFailure(t *testing.T) {
	parent := t.TempDir()

	// A regular file where a directory is expected. os.CreateTemp then fails with
	// ENOTDIR, which is a real failure of the step under test rather than a
	// missing-directory shortcut that would fail somewhere else.
	notADirectory := filepath.Join(parent, "not-a-directory")
	if err := os.WriteFile(notADirectory, []byte("occupied"), 0o600); err != nil {
		t.Fatalf("write the file that stands in for a directory: %v", err)
	}

	identityPath := filepath.Join(notADirectory, IdentityFileName)
	err := SaveIdentity(identityPath, newValidIdentity(t))
	if err == nil {
		t.Fatal("SaveIdentity() = nil error, want a failure when the directory cannot hold a temporary file")
	}

	message := err.Error()
	if !strings.Contains(message, "create temporary identity file") {
		t.Fatalf("error = %q, want it to name the create step", message)
	}
	if !strings.Contains(message, notADirectory) {
		t.Fatalf("error = %q, want it to name the directory %q", message, notADirectory)
	}

	// No temporary file can exist, because the step that creates one failed. The
	// assertion is still made, so a future change that creates the file earlier
	// cannot silently start leaving one behind.
	assertNoTemporaryIdentityFile(t, parent)

	// The path cannot hold an identity file, because its parent is a regular file.
	// The kernel answers ENOTDIR rather than ENOENT, so the assertion is that the
	// stat fails at all: either answer means no identity was written.
	if _, statErr := os.Stat(identityPath); statErr == nil {
		t.Fatal("stat identity file = nil error, want a failure because no identity was written")
	}
}

// TestSaveIdentityRemovesTheTemporaryFileWhenRenameFails is the central test of
// this file. The temporary file exists and holds the credential when the rename
// fails, so this is the case where the cleanup promise is actually under load.
func TestSaveIdentityRemovesTheTemporaryFileWhenRenameFails(t *testing.T) {
	directory := t.TempDir()
	identityPath := IdentityPath(directory)

	// A non-empty directory where the identity file should go. os.Rename refuses
	// to replace it with EEXIST, so the failure happens after the temporary file
	// has been written, synced and closed.
	occupied := filepath.Join(directory, IdentityFileName)
	if err := os.MkdirAll(occupied, 0o700); err != nil {
		t.Fatalf("create the directory that occupies the identity path: %v", err)
	}
	marker := filepath.Join(occupied, "marker")
	if err := os.WriteFile(marker, []byte("keep"), 0o600); err != nil {
		t.Fatalf("write the marker inside the occupying directory: %v", err)
	}

	err := SaveIdentity(identityPath, newValidIdentity(t))
	if err == nil {
		t.Fatal("SaveIdentity() = nil error, want a failure when the rename target is a non-empty directory")
	}

	message := err.Error()
	if !strings.Contains(message, "rename temporary identity file over") {
		t.Fatalf("error = %q, want it to name the rename step", message)
	}
	if !strings.Contains(message, identityPath) {
		t.Fatalf("error = %q, want it to name the target %q", message, identityPath)
	}

	// The error names the temporary file it tried to rename, which proves the
	// temporary file really existed. Without this the test could pass while never
	// reaching the branch it claims to cover.
	if !strings.Contains(message, ".identity-") {
		t.Fatalf("error = %q, want it to name the temporary file, which proves one was created", message)
	}

	assertNoTemporaryIdentityFile(t, directory)

	// The occupying directory must be untouched. A save that clobbered it would be
	// a worse failure than the one being reported.
	content, readErr := os.ReadFile(marker)
	if readErr != nil {
		t.Fatalf("read the marker after a failed save: %v", readErr)
	}
	if string(content) != "keep" {
		t.Fatalf("marker content = %q, want %q", content, "keep")
	}
}

// TestSaveIdentityLeavesNoTemporaryFileOnEveryFailure states the security promise
// once, over every failure this test file can inject, so a new failure mode added
// later is checked against the same rule.
func TestSaveIdentityLeavesNoTemporaryFileOnEveryFailure(t *testing.T) {
	cases := []struct {
		name  string
		setup func(t *testing.T, directory string) (identityPath string)
	}{
		{
			name: "the directory cannot hold a temporary file",
			setup: func(t *testing.T, directory string) string {
				blocked := filepath.Join(directory, "blocked")
				if err := os.WriteFile(blocked, []byte("occupied"), 0o600); err != nil {
					t.Fatalf("write the blocking file: %v", err)
				}
				return filepath.Join(blocked, IdentityFileName)
			},
		},
		{
			name: "the rename target is a non-empty directory",
			setup: func(t *testing.T, directory string) string {
				occupied := filepath.Join(directory, IdentityFileName)
				if err := os.MkdirAll(occupied, 0o700); err != nil {
					t.Fatalf("create the occupying directory: %v", err)
				}
				if err := os.WriteFile(filepath.Join(occupied, "marker"), []byte("keep"), 0o600); err != nil {
					t.Fatalf("write the marker: %v", err)
				}
				return occupied
			},
		},
	}

	for _, testCase := range cases {
		t.Run(testCase.name, func(t *testing.T) {
			directory := t.TempDir()
			identityPath := testCase.setup(t, directory)

			if err := SaveIdentity(identityPath, newValidIdentity(t)); err == nil {
				t.Fatal("SaveIdentity() = nil error, want a failure")
			}

			assertNoTemporaryIdentityFile(t, directory)
		})
	}
}

// TestSaveIdentityLeavesNoHalfWrittenFileWhenTheSaveFails checks that a failed
// save leaves nothing at the identity path that parses as an identity. A file that
// parses as neither the old pair nor the new one would leave the operator unable to
// tell which credential the Node holds.
//
// The previous file is removed before the failure is injected, because a rename
// over an existing regular file succeeds on POSIX and would not fail at all. So
// this test does not claim the old pair survives; it claims the failure does not
// invent a third state.
func TestSaveIdentityLeavesNoHalfWrittenFileWhenTheSaveFails(t *testing.T) {
	directory := t.TempDir()
	identityPath := IdentityPath(directory)

	previous := newValidIdentity(t)
	if err := SaveIdentity(identityPath, previous); err != nil {
		t.Fatalf("SaveIdentity() = %v, want nil for the first save", err)
	}

	// Make the rename fail by replacing the identity file with a non-empty
	// directory. The previous pair is gone from disk at this point, so this test
	// checks the narrower promise that the failure does not leave a half-written
	// file that parses as neither pair.
	if err := os.Remove(identityPath); err != nil {
		t.Fatalf("remove the identity file to make room for the occupying directory: %v", err)
	}
	occupied := identityPath
	if err := os.MkdirAll(occupied, 0o700); err != nil {
		t.Fatalf("create the occupying directory: %v", err)
	}
	if err := os.WriteFile(filepath.Join(occupied, "marker"), []byte("keep"), 0o600); err != nil {
		t.Fatalf("write the marker: %v", err)
	}

	if err := SaveIdentity(identityPath, newValidIdentity(t)); err == nil {
		t.Fatal("SaveIdentity() = nil error, want a failure")
	}

	assertNoTemporaryIdentityFile(t, directory)

	// Nothing at the identity path may parse as an identity, because a file that
	// parses as neither the old pair nor the new one leaves the operator unable to
	// tell which credential the Node holds.
	if _, loadErr := LoadIdentity(identityPath); loadErr == nil {
		t.Fatal("LoadIdentity() = nil error after a failed save, want the path to hold no identity")
	}
}
