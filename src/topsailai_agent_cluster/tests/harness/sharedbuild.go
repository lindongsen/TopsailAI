// Package harness provides isolated real-process test resources for integration and BDD tests.
package harness

import (
	"fmt"
	"os"
	"path/filepath"
	"sync"
)

// sharedBuildDirEnv overrides where the shared test binaries are built.
//
// It exists so a caller can point the cache at a directory with enough space, or
// keep it across runs. The default is a per-process directory under the system
// temporary directory, which is removed when the test process exits.
const sharedBuildDirEnv = "AGENT_CLUSTER_TEST_BUILD_DIR"

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
// be reused. The directory is created lazily and removed by the process exit, and
// a crash leaves at most one copy instead of one per scenario.
var sharedBuilds = struct {
	mu    sync.Mutex
	dir   string
	built map[string]string
	err   error
}{built: make(map[string]string)}

// sharedBuildDir returns the process-scoped directory that holds shared binaries.
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
		created, err := os.MkdirTemp("", "agent-cluster-test-bin-")
		if err != nil {
			sharedBuilds.err = fmt.Errorf("create shared build directory: %w", err)
			return "", sharedBuilds.err
		}
		dir = created
	} else if err := os.MkdirAll(dir, 0o755); err != nil {
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
	if err := Build(path, packagePath); err != nil {
		return "", err
	}
	sharedBuilds.built[packagePath] = path
	return path, nil
}

// SharedBuildDir reports the directory holding the shared binaries, for diagnostics.
func SharedBuildDir() string {
	sharedBuilds.mu.Lock()
	defer sharedBuilds.mu.Unlock()
	return sharedBuilds.dir
}
