package endpoint

import (
	"context"
	"os"
	"path/filepath"
	"syscall"
	"testing"
	"time"
)

func writeAllowlistFile(t *testing.T, dir, content string) string {
	t.Helper()
	path := filepath.Join(dir, "command-allowlist.conf")
	if err := os.WriteFile(path, []byte(content), 0o600); err != nil {
		t.Fatal(err)
	}
	return path
}

func TestLoadAllowlistFileReadsEntries(t *testing.T) {
	path := writeAllowlistFile(t, t.TempDir(), "git status\nls\n")
	file, err := LoadAllowlistFile(path)
	if err != nil {
		t.Fatal(err)
	}
	if err := file.Allowlist.Permit([]string{"git", "status"}); err != nil {
		t.Fatalf("expected git status to be permitted: %v", err)
	}
}

func TestLoadAllowlistFileRequiresPath(t *testing.T) {
	if _, err := LoadAllowlistFile(""); err == nil {
		t.Fatalf("empty path must be rejected")
	}
}

func TestLoadAllowlistFileRejectsMissingFile(t *testing.T) {
	if _, err := LoadAllowlistFile(filepath.Join(t.TempDir(), "absent.conf")); err == nil {
		t.Fatalf("missing file must be rejected")
	}
}

func TestAllowlistFileReloadKeepsPreviousOnParseFailure(t *testing.T) {
	dir := t.TempDir()
	path := writeAllowlistFile(t, dir, "ls\n")
	file, err := LoadAllowlistFile(path)
	if err != nil {
		t.Fatal(err)
	}
	// A broken edit must not widen or clear the policy in force.
	if err := os.WriteFile(path, []byte("git\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	if err := file.Reload(); err == nil {
		t.Fatalf("expected reload to reject a single token git entry")
	}
	if err := file.Allowlist.Permit([]string{"ls"}); err != nil {
		t.Fatalf("previous entry must survive a failed reload: %v", err)
	}
}

func TestAllowlistFileReloadAppliesNewEntries(t *testing.T) {
	dir := t.TempDir()
	path := writeAllowlistFile(t, dir, "ls\n")
	file, err := LoadAllowlistFile(path)
	if err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(path, []byte("git status\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	if err := file.Reload(); err != nil {
		t.Fatalf("reload must succeed: %v", err)
	}
	if err := file.Allowlist.Permit([]string{"git", "status"}); err != nil {
		t.Fatalf("new entry must permit: %v", err)
	}
	if err := file.Allowlist.Permit([]string{"ls"}); err == nil {
		t.Fatalf("replaced entry must no longer permit")
	}
}

func TestAllowlistFileWatchReloadOnSIGHUP(t *testing.T) {
	dir := t.TempDir()
	path := writeAllowlistFile(t, dir, "ls\n")
	file, err := LoadAllowlistFile(path)
	if err != nil {
		t.Fatal(err)
	}
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	results := make(chan error, 4)
	stop, err := file.WatchReload(ctx, func(reloadErr error) { results <- reloadErr })
	if err != nil {
		t.Fatal(err)
	}
	defer stop()
	if err := os.WriteFile(path, []byte("git status\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	if err := syscall.Kill(os.Getpid(), syscall.SIGHUP); err != nil {
		t.Fatalf("send SIGHUP: %v", err)
	}
	select {
	case reloadErr := <-results:
		if reloadErr != nil {
			t.Fatalf("reload reported error: %v", reloadErr)
		}
	case <-time.After(5 * time.Second):
		t.Fatal("SIGHUP did not trigger a reload")
	}
	if err := file.Allowlist.Permit([]string{"git", "status"}); err != nil {
		t.Fatalf("reloaded entry must permit: %v", err)
	}
}

func TestAllowlistFileWatchReloadStopsOnCancel(t *testing.T) {
	path := writeAllowlistFile(t, t.TempDir(), "ls\n")
	file, err := LoadAllowlistFile(path)
	if err != nil {
		t.Fatal(err)
	}
	ctx, cancel := context.WithCancel(context.Background())
	stop, err := file.WatchReload(ctx, nil)
	if err != nil {
		t.Fatal(err)
	}
	cancel()
	stopped := make(chan struct{})
	go func() {
		stop()
		close(stopped)
	}()
	select {
	case <-stopped:
	case <-time.After(5 * time.Second):
		t.Fatal("stop did not return after context cancellation")
	}
}
