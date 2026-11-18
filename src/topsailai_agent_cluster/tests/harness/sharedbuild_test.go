package harness

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

// TestSharedBuildDirDefaultIsProjectLocalAndStable asserts the default build
// location is one fixed project-local directory rather than a per-process
// temporary directory.
//
// The defect this guards: os.MkdirTemp never removes itself, so a per-process
// directory leaked one copy of the three test binaries on every run, including
// runs that ended normally. A fixed path is bounded by construction because the
// same directory is reused.
func TestSharedBuildDirDefaultIsProjectLocalAndStable(t *testing.T) {
	t.Setenv(sharedBuildDirEnv, "")
	resetSharedBuilds(t)

	first, err := sharedBuildDir()
	if err != nil {
		t.Fatalf("sharedBuildDir: %v", err)
	}
	second, err := sharedBuildDir()
	if err != nil {
		t.Fatalf("sharedBuildDir second call: %v", err)
	}
	if first != second {
		t.Fatalf("build directory is not stable: %q then %q", first, second)
	}
	if !filepath.IsAbs(first) {
		t.Fatalf("build directory %q is not absolute", first)
	}
	if !strings.HasSuffix(filepath.ToSlash(first), "/"+defaultSharedBuildDir) {
		t.Fatalf("build directory %q does not end with %q", first, defaultSharedBuildDir)
	}
	if strings.Contains(filepath.ToSlash(first), "/tmp/") {
		t.Fatalf("build directory %q is under the system temporary directory, so it is not project-local", first)
	}
	if _, err := os.Stat(first); err != nil {
		t.Fatalf("build directory %q was not created: %v", first, err)
	}
}

// TestSharedBuildDirHonoursOverride asserts a caller-supplied directory wins and
// is not treated as owned by this process.
//
// The Makefile points AGENT_CLUSTER_TEST_BUILD_DIR at .tmp/bdd-build so six
// sequential BDD groups reuse one build. Cleanup must therefore never remove a
// caller-supplied directory, or every group after the first would rebuild.
func TestSharedBuildDirHonoursOverride(t *testing.T) {
	override := t.TempDir()
	t.Setenv(sharedBuildDirEnv, override)
	resetSharedBuilds(t)

	dir, err := sharedBuildDir()
	if err != nil {
		t.Fatalf("sharedBuildDir: %v", err)
	}
	if dir != override {
		t.Fatalf("build directory = %q, want the override %q", dir, override)
	}
	if sharedBuilds.owned {
		t.Fatal("a caller-supplied directory was recorded as owned, so cleanup would delete it")
	}
}

// TestCleanupSharedBuildDirRemovesOnlyOwnedDirectory asserts cleanup removes a
// harness-created directory and leaves a caller-supplied one intact.
//
// Both halves matter: the first proves the residue is reclaimable, the second
// proves the Makefile's cross-group reuse is not destroyed.
func TestCleanupSharedBuildDirRemovesOnlyOwnedDirectory(t *testing.T) {
	t.Run("owned directory is removed", func(t *testing.T) {
		t.Setenv(sharedBuildDirEnv, "")
		resetSharedBuilds(t)

		dir, err := sharedBuildDir()
		if err != nil {
			t.Fatalf("sharedBuildDir: %v", err)
		}
		if err := os.WriteFile(filepath.Join(dir, "residue"), []byte("x"), 0o644); err != nil {
			t.Fatalf("seed residue: %v", err)
		}
		removed, err := CleanupSharedBuildDir()
		if err != nil {
			t.Fatalf("CleanupSharedBuildDir: %v", err)
		}
		if !removed {
			t.Fatal("cleanup reported nothing removed for a harness-created directory")
		}
		if _, err := os.Stat(dir); !os.IsNotExist(err) {
			t.Fatalf("build directory %q still exists after cleanup: %v", dir, err)
		}
	})

	t.Run("caller directory is preserved", func(t *testing.T) {
		override := t.TempDir()
		t.Setenv(sharedBuildDirEnv, override)
		resetSharedBuilds(t)

		if _, err := sharedBuildDir(); err != nil {
			t.Fatalf("sharedBuildDir: %v", err)
		}
		marker := filepath.Join(override, "keep")
		if err := os.WriteFile(marker, []byte("x"), 0o644); err != nil {
			t.Fatalf("seed marker: %v", err)
		}
		removed, err := CleanupSharedBuildDir()
		if err != nil {
			t.Fatalf("CleanupSharedBuildDir: %v", err)
		}
		if removed {
			t.Fatal("cleanup removed a caller-supplied directory")
		}
		if _, err := os.Stat(marker); err != nil {
			t.Fatalf("caller-supplied directory content was destroyed: %v", err)
		}
	})
}

// TestBinaryIsFreshRejectsStaleBinary asserts a binary older than the newest
// build input is rebuilt rather than reused.
//
// Reusing a fixed directory across runs makes this the load-bearing check: without
// it a test could execute a binary from an earlier commit and pass while verifying
// code that no longer exists.
func TestBinaryIsFreshRejectsStaleBinary(t *testing.T) {
	dir := t.TempDir()
	stale := filepath.Join(dir, "stale-binary")
	if err := os.WriteFile(stale, []byte("old"), 0o755); err != nil {
		t.Fatalf("write stale binary: %v", err)
	}
	// A binary older than every source file must be rejected.
	old := mustNewestBuildInput(t).Add(-time.Hour)
	if err := os.Chtimes(stale, old, old); err != nil {
		t.Fatalf("age the binary: %v", err)
	}
	resetSharedBuilds(t)
	if binaryIsFresh(stale) {
		t.Fatal("a binary older than the newest build input was reported fresh")
	}

	// A binary newer than every source file must be accepted, so the check is a
	// real comparison rather than an unconditional rebuild.
	fresh := filepath.Join(dir, "fresh-binary")
	if err := os.WriteFile(fresh, []byte("new"), 0o755); err != nil {
		t.Fatalf("write fresh binary: %v", err)
	}
	newer := mustNewestBuildInput(t).Add(time.Hour)
	if err := os.Chtimes(fresh, newer, newer); err != nil {
		t.Fatalf("freshen the binary: %v", err)
	}
	resetSharedBuilds(t)
	if !binaryIsFresh(fresh) {
		t.Fatal("a binary newer than the newest build input was reported stale")
	}
}

// TestNewestBuildInputIgnoresNonBuildFiles asserts the freshness probe looks only
// at files that can change a compiled binary.
//
// Without this the probe would descend into .tmp, which holds the build directory
// it is validating, and every run would consider the tree changed.
func TestNewestBuildInputIgnoresNonBuildFiles(t *testing.T) {
	root := t.TempDir()
	goFile := filepath.Join(root, "main.go")
	if err := os.WriteFile(goFile, []byte("package main\n"), 0o644); err != nil {
		t.Fatalf("write go file: %v", err)
	}
	base := time.Date(2026, 1, 1, 0, 0, 0, 0, time.UTC)
	if err := os.Chtimes(goFile, base, base); err != nil {
		t.Fatalf("set go file time: %v", err)
	}
	// A newer non-build file must not influence the result.
	doc := filepath.Join(root, "README.md")
	if err := os.WriteFile(doc, []byte("docs\n"), 0o644); err != nil {
		t.Fatalf("write doc: %v", err)
	}
	later := base.Add(48 * time.Hour)
	if err := os.Chtimes(doc, later, later); err != nil {
		t.Fatalf("set doc time: %v", err)
	}

	newest, err := newestBuildInput(root)
	if err != nil {
		t.Fatalf("newestBuildInput: %v", err)
	}
	if !newest.Equal(base) {
		t.Fatalf("newest build input = %v, want %v; a non-build file influenced the probe", newest, base)
	}
}

// resetSharedBuilds clears the process-wide cache so one test cannot observe
// another test's directory.
func resetSharedBuilds(t *testing.T) {
	t.Helper()
	sharedBuilds.mu.Lock()
	defer sharedBuilds.mu.Unlock()
	sharedBuilds.dir = ""
	sharedBuilds.owned = false
	sharedBuilds.built = make(map[string]string)
	sharedBuilds.err = nil
	sharedBuilds.newest = time.Time{}
	sharedBuilds.newestErr = nil
}

// mustNewestBuildInput returns the newest build input time of the real module.
func mustNewestBuildInput(t *testing.T) time.Time {
	t.Helper()
	newest, err := newestBuildInput(ModuleRootForBuild())
	if err != nil {
		t.Fatalf("newestBuildInput: %v", err)
	}
	if newest.IsZero() {
		t.Fatal("newestBuildInput found no build inputs in the module root")
	}
	return newest
}
