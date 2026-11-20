package main

import (
	"context"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// writeStdoutFile creates one provider stdout file so a digest can be proven from
// the directory listing alone.
func writeStdoutFile(t *testing.T, directory, name string) {
	t.Helper()
	if err := os.WriteFile(filepath.Join(directory, name), []byte("line\n"), 0o600); err != nil {
		t.Fatalf("write %s: %v", name, err)
	}
}

// TestResolveRowTargetByDigestProvesSessionAndTaskRows proves the shortcut
// recovers every selector a read needs, including the task flag.
//
// The task flag is the part that cannot be guessed: it selects the file family,
// so a row proven without it would read a different file. Both families are
// therefore asserted here, and the task row is asserted to be distinguishable
// from a session row that shares its session identifier.
func TestResolveRowTargetByDigestProvesSessionAndTaskRows(t *testing.T) {
	directory := t.TempDir()
	writeStdoutFile(t, directory, "wa-session.4242.session.stdout")
	writeStdoutFile(t, directory, "wa-session.5151.task.stdout")
	writeStdoutFile(t, directory, "wa-session.5151.extra.task.stdout")

	provider := newProvider(stubCommandRunner{}, controlCatalog{}, supportedPlatform, directory, "")

	sessionKey, err := providerSessionKey(workspaceItem{
		SessionID: "wa-session", ProviderRowKey: "wa-session.4242.session.stdout",
	})
	if err != nil {
		t.Fatal(err)
	}
	sessionRow, ok := provider.resolveRowTargetByDigest(sessionKey)
	if !ok {
		t.Fatal("session row was not proven from its filename")
	}
	if sessionRow.SessionID != "wa-session" || sessionRow.PID != 4242 || sessionRow.IsTask {
		t.Fatalf("session row = %+v", sessionRow)
	}

	taskKey, err := providerSessionKey(workspaceItem{
		SessionID: "wa-session", ProviderRowKey: "wa-session.5151.task.stdout", IsTask: true,
	})
	if err != nil {
		t.Fatal(err)
	}
	taskRow, ok := provider.resolveRowTargetByDigest(taskKey)
	if !ok {
		t.Fatal("task row was not proven from its filename")
	}
	if taskRow.SessionID != "wa-session" || taskRow.PID != 5151 || !taskRow.IsTask {
		t.Fatalf("task row = %+v", taskRow)
	}
	if taskRow.ProviderRowKey != "wa-session.5151.task.stdout" {
		t.Fatalf("task row key = %q", taskRow.ProviderRowKey)
	}
}

// TestResolveRowTargetByDigestRefusesWhatItCannotProve proves the shortcut never
// guesses.
//
// A session-scoped key names a session rather than a row, so it must be left to
// discovery, which applies the provider's own liveness selection. A row whose
// file is gone cannot be proven either. Both must report false so the caller
// falls back instead of reading an arbitrary file.
func TestResolveRowTargetByDigestRefusesWhatItCannotProve(t *testing.T) {
	directory := t.TempDir()
	writeStdoutFile(t, directory, "wa-live.7777.session.stdout")
	provider := newProvider(stubCommandRunner{}, controlCatalog{}, supportedPlatform, directory, "")

	sessionScoped, err := sessionProviderKey("wa-live")
	if err != nil {
		t.Fatal(err)
	}
	if _, ok := provider.resolveRowTargetByDigest(sessionScoped); ok {
		t.Fatal("a session-scoped key must not be proven as one row")
	}

	deletedKey, err := providerSessionKey(workspaceItem{
		SessionID: "wa-gone", ProviderRowKey: "wa-gone.9999.session.stdout",
	})
	if err != nil {
		t.Fatal(err)
	}
	if _, ok := provider.resolveRowTargetByDigest(deletedKey); ok {
		t.Fatal("a row whose file is gone must not be proven")
	}

	withoutDirectory := newProvider(stubCommandRunner{}, controlCatalog{}, supportedPlatform, "", "")
	if _, ok := withoutDirectory.resolveRowTargetByDigest(deletedKey); ok {
		t.Fatal("an unconfigured task directory must not prove anything")
	}
}

// TestResolveReadTargetFallsBackToDiscovery proves the shortcut is a fast path
// and not a replacement.
//
// The runner answers only the discovery argv, so the assertion is that discovery
// was actually invoked. Without it, a shortcut that silently answered for an
// unprovable target would look identical to a correct fallback.
func TestResolveReadTargetFallsBackToDiscovery(t *testing.T) {
	runner := &scriptedRunner{t: t, answers: map[string][]runnerAnswer{
		strings.Join([]string{"workspace", "list", "--json", "--local"}, "\x00"): answer(`{"items":[],"total":0}`),
	}}
	provider := newProvider(runner, controlCatalog{}, supportedPlatform, t.TempDir(), "")

	key, err := providerSessionKey(workspaceItem{
		SessionID: "wa-gone", ProviderRowKey: "wa-gone.9999.session.stdout",
	})
	if err != nil {
		t.Fatal(err)
	}
	if _, err := provider.resolveReadTarget(context.Background(), &target{
		ResourceKind: resourceSession, ProviderResourceKey: key,
	}); err == nil {
		t.Fatal("an unprovable target must be refused by discovery, not answered")
	}
	if len(runner.calls) != 1 {
		t.Fatalf("discovery calls = %d, want 1", len(runner.calls))
	}
}

// TestResolveReadTargetSkipsDiscoveryForAProvenRow proves the saving is real.
//
// The runner has no answers at all, so any CLI call fails the test. Asserting
// only that the target resolved would pass even if discovery still ran, which is
// exactly the cost this change exists to remove.
func TestResolveReadTargetSkipsDiscoveryForAProvenRow(t *testing.T) {
	directory := t.TempDir()
	writeStdoutFile(t, directory, "wa-fast.3131.session.stdout")
	runner := &scriptedRunner{t: t, answers: map[string][]runnerAnswer{}}
	provider := newProvider(runner, controlCatalog{}, supportedPlatform, directory, "")

	key, err := providerSessionKey(workspaceItem{
		SessionID: "wa-fast", ProviderRowKey: "wa-fast.3131.session.stdout",
	})
	if err != nil {
		t.Fatal(err)
	}
	resolved, err := provider.resolveReadTarget(context.Background(), &target{
		ResourceKind: resourceSession, ProviderResourceKey: key,
	})
	if err != nil {
		t.Fatal(err)
	}
	if resolved.PID != 3131 || resolved.IsTask {
		t.Fatalf("resolved = %+v", resolved)
	}
	if len(runner.calls) != 0 {
		t.Fatalf("discovery ran %d times for a proven row: %v", len(runner.calls), runner.calls)
	}
}

// TestResolveTaskDirFollowsProviderPrecedence proves the directory is derived the
// same way the provider CLI derives it.
//
// A mismatch here would make the shortcut silently useless, because it would scan
// a directory that holds no stdout files and fall back on every read. The
// directories are created, because the derivation only reports a path it can
// actually read: a test that asserted an uncreated path would be asserting the
// guess rather than the directory the scan would use.
func TestResolveTaskDirFollowsProviderPrecedence(t *testing.T) {
	root := t.TempDir()
	home := filepath.Join(root, "home")
	configured := filepath.Join(root, "ts")
	for _, directory := range []string{
		filepath.Join(configured, "workspace", "task"),
		filepath.Join(home, ".topsailai", "workspace", "task"),
		filepath.Join(home, "ts", "workspace", "task"),
	} {
		if err := os.MkdirAll(directory, 0o700); err != nil {
			t.Fatalf("create %s: %v", directory, err)
		}
	}
	tests := []struct {
		name        string
		environment []string
		want        string
	}{
		{"topsailai home wins", []string{"TOPSAILAI_HOME=" + configured, "HOME=" + home}, filepath.Join(configured, "workspace", "task")},
		{"home is the default", []string{"HOME=" + home}, filepath.Join(home, ".topsailai", "workspace", "task")},
		{"tilde expands against home", []string{"TOPSAILAI_HOME=~/ts", "HOME=" + home}, filepath.Join(home, "ts", "workspace", "task")},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			if got := resolveTaskDir(test.environment); got != test.want {
				t.Fatalf("resolveTaskDir = %q, want %q", got, test.want)
			}
		})
	}
}

// TestResolveTaskDirRefusesADirectoryItCannotRead proves the shortcut is disabled
// rather than guessed when the derived path does not exist.
//
// The precedence above is a second copy of a rule the provider CLI owns, so it can
// disagree with the CLI. A disagreement would make the digest scan read a directory
// that holds no stdout files, and every read would fall back to discovery while the
// shortcut looked healthy. An empty result disables the shortcut outright, so the
// cost of a wrong guess is the discovery call it was meant to avoid.
func TestResolveTaskDirRefusesADirectoryItCannotRead(t *testing.T) {
	root := t.TempDir()
	missing := filepath.Join(root, "absent")
	if got := resolveTaskDir([]string{"TOPSAILAI_HOME=" + missing, "HOME=" + root}); got != "" {
		t.Fatalf("resolveTaskDir = %q for a directory that does not exist, want an empty result", got)
	}
	// A file where a directory is expected must be refused too, because the scan
	// would fail on it and the shortcut would silently prove nothing.
	file := filepath.Join(root, "not-a-directory")
	if err := os.WriteFile(file, []byte("x"), 0o600); err != nil {
		t.Fatalf("write %s: %v", file, err)
	}
	if got := resolveTaskDir([]string{"TOPSAILAI_HOME=" + file, "HOME=" + root}); got != "" {
		t.Fatalf("resolveTaskDir = %q for a regular file, want an empty result", got)
	}
}

// TestParseStdoutFilenameReadsEachFamilyByItsOwnGrammar proves the PID position
// is not shared between the two families.
//
// A session stdout names its PID last, while a task stdout names it second and may
// carry further identifiers. Reading one family with the other's rule would
// produce a PID belonging to a different process, which the provider CLI would
// then reject as a mismatch.
func TestParseStdoutFilenameReadsEachFamilyByItsOwnGrammar(t *testing.T) {
	tests := []struct {
		name      string
		filename  string
		sessionID string
		pid       int64
		isTask    bool
		ok        bool
	}{
		{"session", "wa-a.123.session.stdout", "wa-a", 123, false, true},
		{"task", "wa-a.456.task.stdout", "wa-a", 456, true, true},
		{"task with extra identifier", "wa-a.456.extra.task.stdout", "wa-a", 456, true, true},
		{"dotted session identifier", "wa.a.b.789.session.stdout", "wa.a.b", 789, false, true},
		{"unrelated file", "notes.txt", "", 0, false, false},
		{"non numeric pid", "wa-a.pid.session.stdout", "", 0, false, false},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			sessionID, pid, isTask, ok := parseStdoutFilename(test.filename)
			if ok != test.ok || sessionID != test.sessionID || pid != test.pid || isTask != test.isTask {
				t.Fatalf("parseStdoutFilename(%q) = %q,%d,%v,%v", test.filename, sessionID, pid, isTask, ok)
			}
		})
	}
}
