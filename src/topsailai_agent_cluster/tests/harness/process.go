// Package harness provides isolated real-process test resources for integration and BDD tests.
package harness

import (
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"sync"
	"testing"
)

// CertFiles contains the CA and endpoint/server certificate paths for one scenario.
type CertFiles struct {
	CA, ServerCert, ServerKey string
	ClientCert, ClientKey     string
	ClientCert2, ClientKey2   string
}

// Cluster contains process paths and isolated persistent state for a scenario.
type Cluster struct {
	Root, API, Channel string
	// EndpointChannel is the Endpoint listener port, set only when the Server
	// dials. It stays empty in the default endpoint-initiated direction.
	EndpointChannel             string
	ServerDB, EndpointDB        string
	Server, Endpoint, Endpoint2 *exec.Cmd
	Record, Record2             string
	EndpointPath                string
	EndpointEnv                 []string
	// CLIEnv holds extra environment entries for every CLI process the harness
	// starts. It is the client-side configuration seam: the Endpoint token map
	// lives here because it is the CLI's own configuration, and the Server must
	// never hold it.
	CLIEnv []string
	Certs                       CertFiles
	TUIPath                     string
	tuiBuildMu                  sync.Mutex
	stopMu                      sync.Mutex
	stopped                     bool
}

// ModuleRoot returns the repository root for tests launched from a package directory.
func ModuleRoot(t testing.TB) string {
	t.Helper()
	wd, err := os.Getwd()
	if err != nil {
		t.Fatal(err)
	}
	return filepath.Clean(filepath.Join(wd, "..", ".."))
}

// FreePort reserves and releases a loopback port for a child-process listener.
func FreePort(t testing.TB) string {
	t.Helper()
	port, err := FreePortE()
	if err != nil {
		t.Fatal(err)
	}
	return port
}

// Build compiles one repository command into the scenario directory.
func Build(output, packagePath string) error {
	cmd := exec.Command("go", "build", "-tags=testhooks", "-o", output, packagePath)
	cmd.Dir = ModuleRootForBuild()
	outputBytes, err := cmd.CombinedOutput()
	if err != nil {
		return fmt.Errorf("build %s: %w\n%s", packagePath, err, outputBytes)
	}
	return nil
}

// ModuleRootForBuild returns the repository root without coupling build failures to a test.
func ModuleRootForBuild() string {
	wd, err := os.Getwd()
	if err != nil {
		return wd
	}
	return filepath.Clean(filepath.Join(wd, "..", ".."))
}

// Certificates creates a private CA and server/client certificates under dir.
func Certificates(t testing.TB, dir string) CertFiles {
	t.Helper()
	certs, err := CertificatesE(dir)
	if err != nil {
		t.Fatal(err)
	}
	return certs
}

// StartProcess starts a child process with the repository as its working directory.
func StartProcess(t testing.TB, path string, env []string) *exec.Cmd {
	t.Helper()
	cmd, err := StartProcessE(path, env)
	if err != nil {
		t.Fatal(err)
	}
	return cmd
}

// mergeEnvironment applies overrides once so inherited configuration cannot shadow scenario ports.
func mergeEnvironment(overrides []string) []string {
	values := make(map[string]string)
	order := make([]string, 0)
	for _, entry := range append(os.Environ(), overrides...) {
		key, _, ok := strings.Cut(entry, "=")
		if !ok {
			continue
		}
		if _, exists := values[key]; !exists {
			order = append(order, key)
		}
		values[key] = entry
	}
	result := make([]string, 0, len(order))
	for _, key := range order {
		result = append(result, values[key])
	}
	return result
}

// StopProcess sends SIGTERM to one owned child and waits for its exit.
func StopProcess(t testing.TB, cmd *exec.Cmd) {
	t.Helper()
	if err := StopProcessE(cmd); err != nil {
		t.Logf("stop process: %v", err)
	}
}
