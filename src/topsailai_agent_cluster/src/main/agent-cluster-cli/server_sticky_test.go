package main

import (
	"os"
	"path/filepath"
	"testing"
)

// TestPreferStickyKeepsTheRememberedServerFirst asserts the property that keeps
// the CLI in the same world as the fleet.
//
// An Endpoint only reconnects on transport failure, so after a primary recovers
// the fleet stays on the secondary. A CLI that always probed from the head of the
// list would return to the primary and report an empty fleet, which reads as a
// total outage.
func TestPreferStickyKeepsTheRememberedServerFirst(t *testing.T) {
	candidates := []ServerTarget{
		{Profile: "primary", URL: "https://primary.invalid"},
		{Profile: "secondary", URL: "https://secondary.invalid"},
	}
	ordered := preferSticky(candidates, "secondary")
	if len(ordered) != 2 {
		t.Fatalf("candidate count = %d, want 2", len(ordered))
	}
	if ordered[0].Profile != "secondary" {
		t.Fatalf("first candidate = %q, want secondary", ordered[0].Profile)
	}
	if ordered[1].Profile != "primary" {
		t.Fatalf("second candidate = %q, want primary", ordered[1].Profile)
	}
}

// TestPreferStickyPreservesRemainingOrder asserts that the preference is a
// rotation rather than a reordering.
//
// The operator's stated preference must still decide everything after the
// remembered Server, otherwise a remembered third choice would silently promote
// the fourth over the second.
func TestPreferStickyPreservesRemainingOrder(t *testing.T) {
	candidates := []ServerTarget{
		{Profile: "primary"},
		{Profile: "secondary"},
		{Profile: "tertiary"},
	}
	ordered := preferSticky(candidates, "tertiary")
	want := []string{"tertiary", "primary", "secondary"}
	if len(ordered) != len(want) {
		t.Fatalf("candidate count = %d, want %d", len(ordered), len(want))
	}
	for index, name := range want {
		if ordered[index].Profile != name {
			t.Fatalf("candidate %d = %q, want %q", index, ordered[index].Profile, name)
		}
	}
}

// TestPreferStickyIgnoresUnknownName asserts that a remembered profile the
// operator has since removed is ignored.
//
// Honouring it would mean probing a Server that is no longer configured, and the
// failure would name a profile the operator cannot find in their configuration.
func TestPreferStickyIgnoresUnknownName(t *testing.T) {
	candidates := []ServerTarget{
		{Profile: "primary"},
		{Profile: "secondary"},
	}
	ordered := preferSticky(candidates, "retired")
	if ordered[0].Profile != "primary" || ordered[1].Profile != "secondary" {
		t.Fatalf("order = %q,%q, want primary,secondary", ordered[0].Profile, ordered[1].Profile)
	}
}

// TestPreferStickyLeavesSingleCandidateAlone asserts that a group of one is
// unchanged, because there is nothing to prefer.
func TestPreferStickyLeavesSingleCandidateAlone(t *testing.T) {
	candidates := []ServerTarget{{Profile: "only"}}
	ordered := preferSticky(candidates, "only")
	if len(ordered) != 1 || ordered[0].Profile != "only" {
		t.Fatalf("order = %+v, want the single candidate unchanged", ordered)
	}
}

// TestPreferStickyWithoutRememberedServer asserts that a first run keeps the
// configured order.
func TestPreferStickyWithoutRememberedServer(t *testing.T) {
	candidates := []ServerTarget{{Profile: "primary"}, {Profile: "secondary"}}
	ordered := preferSticky(candidates, "")
	if ordered[0].Profile != "primary" {
		t.Fatalf("first candidate = %q, want primary", ordered[0].Profile)
	}
}

// TestStickyProfileRoundTrip asserts that the remembered name survives a write and
// a read, and that the file is private to the operator.
func TestStickyProfileRoundTrip(t *testing.T) {
	path := filepath.Join(t.TempDir(), "server-profile")
	if err := writeStickyProfile(path, "secondary"); err != nil {
		t.Fatalf("writeStickyProfile returned an error: %v", err)
	}
	if got := readStickyProfile(path); got != "secondary" {
		t.Fatalf("readStickyProfile = %q, want secondary", got)
	}
	info, err := os.Stat(path)
	if err != nil {
		t.Fatalf("stat sticky file: %v", err)
	}
	if mode := info.Mode().Perm(); mode != 0o600 {
		t.Fatalf("sticky file mode = %o, want 600", mode)
	}
}

// TestReadStickyProfileToleratesEveryFailure asserts that the preference is
// advisory.
//
// A missing file is the normal first run, and an unreadable file is a permissions
// problem the operator will notice elsewhere. Turning either into a startup
// failure would make a convenience able to break the CLI.
func TestReadStickyProfileToleratesEveryFailure(t *testing.T) {
	if got := readStickyProfile(""); got != "" {
		t.Fatalf("readStickyProfile(\"\") = %q, want empty", got)
	}
	missing := filepath.Join(t.TempDir(), "absent")
	if got := readStickyProfile(missing); got != "" {
		t.Fatalf("readStickyProfile(missing) = %q, want empty", got)
	}
}

// TestWriteStickyProfileSkipsEmptyInput asserts that nothing is written when there
// is nothing to remember.
//
// An invocation that selected no profile has no name to record, and writing an
// empty file would make the next run read a name that does not exist.
func TestWriteStickyProfileSkipsEmptyInput(t *testing.T) {
	path := filepath.Join(t.TempDir(), "server-profile")
	if err := writeStickyProfile(path, ""); err != nil {
		t.Fatalf("writeStickyProfile returned an error: %v", err)
	}
	if _, err := os.Stat(path); !os.IsNotExist(err) {
		t.Fatalf("sticky file exists after an empty write: %v", err)
	}
	if err := writeStickyProfile("", "secondary"); err != nil {
		t.Fatalf("writeStickyProfile with no path returned an error: %v", err)
	}
}

// TestStickyProfilePathPrefersConfiguration asserts that an operator can place the
// state file deliberately, and that the per-user default is used otherwise.
func TestStickyProfilePathPrefersConfiguration(t *testing.T) {
	lookup := func(name string) string {
		if name == cliServerProfileStickyFileEnv {
			return "/srv/state/server-profile"
		}
		return ""
	}
	if got := stickyProfilePath(lookup, "/home/operator"); got != "/srv/state/server-profile" {
		t.Fatalf("stickyProfilePath = %q, want the configured path", got)
	}
	empty := func(string) string { return "" }
	want := filepath.Join("/home/operator", filepath.FromSlash(stickyProfileRelativePath))
	if got := stickyProfilePath(empty, "/home/operator"); got != want {
		t.Fatalf("stickyProfilePath = %q, want %q", got, want)
	}
	if got := stickyProfilePath(empty, ""); got != "" {
		t.Fatalf("stickyProfilePath with no home = %q, want empty", got)
	}
}
