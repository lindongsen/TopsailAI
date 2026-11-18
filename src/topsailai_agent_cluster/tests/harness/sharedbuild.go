// Package harness provides isolated real-process test resources for integration and BDD tests.
package harness

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"time"
)

// sharedBuildDirEnv overrides where the shared test binaries are built.
//
// It exists so a caller can point the cache at a directory with enough space, or
// keep it across runs. The default is a fixed directory inside the project's
// .tmp tree, so repeated runs reuse one bounded location instead of creating a
// new directory per process.
const sharedBuildDirEnv = "AGENT_CLUSTER_TEST_BUILD_DIR"

// defaultSharedBuildDir is the project-relative default build location.
//
// It is fixed rather than per-process on purpose. os.MkdirTemp never removes
// itself, so a per-process directory leaked one copy of the three binaries on
// every run, including runs that ended normally. A fixed path is bounded by
// construction: the same directory is reused, so the residue cannot grow with
// the number of runs.
const defaultSharedBuildDir = ".tmp/test-build"

// sharedBuilds caches one compiled binary per package path for the whole test process.
//
// Every real-cluster scenario used to compile the Server, the Endpoint and the
// provider fixture into its own t.TempDir(). With 99 real-cluster scenarios that
// was 99 x 43 MB of identical binaries, about 4.3 GB, all of it held until the
// top-level test returned. The binaries do not depend on scenario state, so they
// are built once here and every scenario runs the same files.
//
// The cache is process-scoped rather than test-scoped on purpose: a scenario's
// t.TempDir() is removed when that scenario ends, so a binary stored there cannot
// be reused. The directory itself lives at a fixed project-local path, so a
// killed run leaves at most one copy that the next run reuses instead of adding
// another.
var sharedBuilds = struct {
	mu        sync.Mutex
	dir       string
	owned     bool
	built     map[string]string
	err       error
	newest    time.Time
	newestErr error
}{built: make(map[string]string)}

// sharedBuildDir returns the directory that holds shared binaries.
//
// owned records whether this process created the location, so cleanup never
// removes a directory the caller supplied.
//
// The caller must hold sharedBuilds.mu.
func sharedBuildDir() (string, error) {
	if sharedBuilds.dir != "" {
		return sharedBuilds.dir, nil
	}
	if sharedBuilds.err != nil {
		return "", sharedBuilds.err
	}
	dir := os.Getenv(sharedBuildDirEnv)
	if dir == "" {
		dir = filepath.Join(ModuleRootForBuild(), defaultSharedBuildDir)
		sharedBuilds.owned = true
	}
	if err := os.MkdirAll(dir, 0o755); err != nil {
		sharedBuilds.err = fmt.Errorf("create shared build directory %s: %w", dir, err)
		return "", sharedBuilds.err
	}
	sharedBuilds.dir = dir
	return dir, nil
}

// SharedBinary returns the path of one compiled test binary, building it once per process.
//
// name is the file name inside the shared directory, so two packages that must sit
// beside each other, such as the TopsailAI provider and its session-info helper,
// pass distinct names and still land in the same directory.
func SharedBinary(name, packagePath string) (string, error) {
	sharedBuilds.mu.Lock()
	defer sharedBuilds.mu.Unlock()
	if path, ok := sharedBuilds.built[packagePath]; ok {
		return path, nil
	}
	dir, err := sharedBuildDir()
	if err != nil {
		return "", err
	}
	path := filepath.Join(dir, name)
	if !binaryIsFresh(path) {
		if err := buildAtomically(path, packagePath); err != nil {
			return "", err
		}
	}
	sharedBuilds.built[packagePath] = path
	return path, nil
}

// buildAtomically compiles into a process-private name and renames it into place.
//
// The shared directory is reused across processes, so two concurrent test binaries
// can build the same output path. go build writes its output directly, so a reader
// could otherwise execute a partially written file. A rename is atomic within one
// filesystem, so a reader sees either the previous binary or the complete new one.
func buildAtomically(path, packagePath string) error {
	staged := fmt.Sprintf("%s.tmp-%d", path, os.Getpid())
	if err := Build(staged, packagePath); err != nil {
		os.Remove(staged)
		return err
	}
	if err := os.Rename(staged, path); err != nil {
		os.Remove(staged)
		return fmt.Errorf("install %s: %w", path, err)
	}
	return nil
}

// binaryIsFresh reports whether path is at least as new as every build input.
//
// Reusing a fixed directory across runs means a binary from an earlier commit
// could otherwise be executed against the current source, which would make a test
// pass while verifying code that no longer exists. The check is a make-style
// timestamp comparison against the module's Go sources and module files, so a
// changed tree always rebuilds and an unchanged tree reuses.
//
// The newest input time is computed once per process, because the tree does not
// change while one test binary runs and walking it per binary would add a full
// source scan to every SharedBinary call.
//
// The caller must hold sharedBuilds.mu.
func binaryIsFresh(path string) bool {
	info, err := os.Stat(path)
	if err != nil {
		return false
	}
	if sharedBuilds.newest.IsZero() && sharedBuilds.newestErr == nil {
		sharedBuilds.newest, sharedBuilds.newestErr = newestBuildInput(ModuleRootForBuild())
	}
	if sharedBuilds.newestErr != nil {
		return false
	}
	return !sharedBuilds.newest.After(info.ModTime())
}

// newestBuildInput returns the newest modification time among the module's build inputs.
//
// Only Go sources and module files can change a compiled binary, so testdata,
// documentation and the .tmp tree are skipped. Skipping .tmp also keeps the walk
// from descending into the build directory it is validating.
func newestBuildInput(root string) (time.Time, error) {
	var newest time.Time
	err := filepath.WalkDir(root, func(path string, entry os.DirEntry, walkErr error) error {
		if walkErr != nil {
			return walkErr
		}
		if entry.IsDir() {
			if path == root {
				return nil
			}
			switch entry.Name() {
			case ".git", ".tmp", "vendor":
				return filepath.SkipDir
			}
			return nil
		}
		name := entry.Name()
		if !strings.HasSuffix(name, ".go") && name != "go.mod" && name != "go.sum" {
			return nil
		}
		info, err := entry.Info()
		if err != nil {
			return err
		}
		if info.ModTime().After(newest) {
			newest = info.ModTime()
		}
		return nil
	})
	return newest, err
}

// CleanupSharedBuildDir removes the shared build directory when this process created it.
//
// It reports whether anything was removed. A caller-supplied directory is never
// removed: the Makefile points AGENT_CLUSTER_TEST_BUILD_DIR at .tmp/bdd-build so
// six sequential BDD groups reuse one build, and deleting it after the first group
// would force every later group to rebuild the same three binaries.
func CleanupSharedBuildDir() (bool, error) {
	sharedBuilds.mu.Lock()
	defer sharedBuilds.mu.Unlock()
	if !sharedBuilds.owned || sharedBuilds.dir == "" {
		return false, nil
	}
	dir := sharedBuilds.dir
	sharedBuilds.dir = ""
	sharedBuilds.built = make(map[string]string)
	if err := os.RemoveAll(dir); err != nil {
		return false, fmt.Errorf("remove shared build directory %s: %w", dir, err)
	}
	return true, nil
}

// SharedBuildDir reports the directory holding the shared binaries, for diagnostics.
func SharedBuildDir() string {
	sharedBuilds.mu.Lock()
	defer sharedBuilds.mu.Unlock()
	return sharedBuilds.dir
}
