package packaging_test

import (
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
)

// The launcher reads ROLE from the packaged node.conf and nothing else, so a
// config package built for one role from a file that declares another installs a
// configuration that starts the wrong process. That happened once: a server
// config package carried ROLE=endpoint, so `agent-clusterctl -c conf/server/node.conf
// restart` stopped the Endpoint and then started it with the Server's paths, and
// the Endpoint died on the first Server-only key. Every other packaging check
// passed, because --config-role and the file's own ROLE were never compared.
//
// These tests pin the comparison. The mismatch case is the defect; the matching
// case proves the guard does not simply refuse every config package, which would
// be a different way to break the build.
func TestConfigPackageRefusesAConfigurationForAnotherRole(t *testing.T) {
	root, work := configRoleProbeWorkspace(t)
	config := writeRoleProbeConfig(t, work, "endpoint.conf", "ROLE=endpoint\nENDPOINT_ID=probe\n")

	output, err := runConfigPackageBuild(root, work, "server", config)
	if err == nil {
		t.Fatalf("building a server config package from a file declaring ROLE=endpoint succeeded; "+
			"the launcher would start the Endpoint with the Server's paths\noutput: %s", output)
	}
	if !strings.Contains(output, "declares ROLE=endpoint but the package is built for server") {
		t.Fatalf("the refusal does not name the mismatch, so an operator cannot tell what to fix\noutput: %s", output)
	}
}

// A configuration with no ROLE at all is refused too. The launcher requires the
// key, so a package carrying a file without it installs a configuration that
// cannot start either role, and the failure would appear at start time on the
// node instead of at build time.
func TestConfigPackageRefusesAConfigurationWithoutARole(t *testing.T) {
	root, work := configRoleProbeWorkspace(t)
	config := writeRoleProbeConfig(t, work, "norole.conf", "ENDPOINT_ID=probe\n")

	output, err := runConfigPackageBuild(root, work, "endpoint", config)
	if err == nil {
		t.Fatalf("building a config package from a file with no ROLE succeeded\noutput: %s", output)
	}
	if !strings.Contains(output, "declares no ROLE") {
		t.Fatalf("the refusal does not name the missing ROLE\noutput: %s", output)
	}
}

// The matching case must build. Without it the guard could reject every config
// package and both tests above would still pass, which is the failure mode a
// one-sided test cannot see.
func TestConfigPackageAcceptsAConfigurationForItsOwnRole(t *testing.T) {
	root, work := configRoleProbeWorkspace(t)
	config := writeRoleProbeConfig(t, work, "endpoint.conf", "ROLE=endpoint\nENDPOINT_ID=probe\n")

	output, err := runConfigPackageBuild(root, work, "endpoint", config)
	if err != nil {
		t.Fatalf("building an endpoint config package from a file declaring ROLE=endpoint failed: %v\noutput: %s", err, output)
	}
}

// configRoleProbeWorkspace prepares a throwaway build tree with TLS material, so
// a successful build has everything it needs and a refused build is refused for
// the role reason rather than for a missing certificate.
func configRoleProbeWorkspace(t *testing.T) (root, work string) {
	t.Helper()
	if _, err := exec.LookPath("dpkg-deb"); err != nil {
		t.Skip("dpkg-deb is not available")
	}
	if _, err := exec.LookPath("openssl"); err != nil {
		t.Skip("openssl is not available")
	}
	root, err := filepath.Abs("../..")
	if err != nil {
		t.Fatalf("cannot resolve the project root: %v", err)
	}
	work, err = os.MkdirTemp(filepath.Join(root, ".tmp"), "deb-role-probe-")
	if err != nil {
		t.Fatalf("cannot create the probe workspace: %v", err)
	}
	t.Cleanup(func() {
		if err := os.RemoveAll(work); err != nil {
			t.Errorf("cannot remove %s: %v", work, err)
		}
	})
	certs := filepath.Join(work, "certs")
	if err := os.MkdirAll(certs, 0o755); err != nil {
		t.Fatalf("cannot create the certificate directory: %v", err)
	}
	if err := generateTestCertificate(certs); err != nil {
		t.Fatalf("cannot generate the test certificate: %v", err)
	}
	return root, work
}

// writeRoleProbeConfig writes one site configuration whose ROLE is the subject of
// the test. The body is deliberately minimal: the guard reads ROLE before any
// other key is consulted, so a short file keeps the test focused on the decision
// it is checking.
func writeRoleProbeConfig(t *testing.T, work, name, body string) string {
	t.Helper()
	path := filepath.Join(work, name)
	if err := os.WriteFile(path, []byte(body), 0o644); err != nil {
		t.Fatalf("cannot write %s: %v", path, err)
	}
	return path
}

// runConfigPackageBuild invokes the packaging script for one config role and
// returns its combined output. The certificate paths are the throwaway material
// from the probe workspace, so a build that reaches TLS resolution succeeds.
func runConfigPackageBuild(root, work, configRole, config string) (string, error) {
	certs := filepath.Join(work, "certs")
	args := []string{
		filepath.Join(root, "scripts", "make-deb.sh"),
		"--role", "config",
		"--config-role", configRole,
		"--site", "role-probe",
		"--config", config,
		"--dest", filepath.Join(work, "deb"),
		"--build-dir", filepath.Join(work, "build"),
		"--version", debTestVersion,
		"--revision", "1",
		"--cert", filepath.Join(certs, "node.pem"),
		"--key", filepath.Join(certs, "node-key.pem"),
		"--ca", filepath.Join(certs, "ca.pem"),
	}
	command := exec.Command("bash", args...)
	command.Dir = root
	output, err := command.CombinedOutput()
	return string(output), err
}
