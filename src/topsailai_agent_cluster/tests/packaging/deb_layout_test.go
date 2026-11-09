package packaging_test

import (
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"sync"
	"testing"
)

// The program payload lives under one directory so a node can be inspected,
// backed up or removed as a unit. Configuration, TLS material, state, logs and
// pid files are real directories beside the controller, not symlinks into the
// Debian policy locations. These constants pin that contract, so a packaging
// change that scatters the payload again fails here instead of on a node.
const (
	debOptDir  = "./opt/agent-cluster"
	debSbinDir = "./usr/local/sbin"
)

// debLayoutDirs is the real directory set that makes one directory show the
// whole product, with the permission string dpkg-deb reports. A symlink here
// would silently redirect a write to whatever filesystem the link names, which
// is how a state directory ends up on a full root filesystem while the operator
// believes it lives under /opt.
var debLayoutDirs = map[string]string{
	debOptDir + "/conf":  "rwxr-xr-x",
	debOptDir + "/certs": "rwxr-xr-x",
	debOptDir + "/data":  "rwxr-x---",
	debOptDir + "/logs":  "rwxr-x---",
	debOptDir + "/run":   "rwxr-xr-x",
}

// debEntry is one path in a package payload. target is empty for a real file or
// directory and holds the link destination for a symlink. mode is the permission
// string dpkg-deb prints, such as "0750".
type debEntry struct {
	path   string
	target string
	mode   string
}

// debPackage is one built package and its parsed payload.
type debPackage struct {
	path      string
	version   string
	depends   string
	entries   map[string]debEntry
	conffiles []string
}

// Building the three packages compiles two large static binaries, so the result
// is shared across the tests in this file instead of rebuilt per test. The build
// is lazy, so running an unrelated integration test does not pay for it.
var (
	debBuildOnce sync.Once
	debBuilt     map[string]*debPackage
	debBuildErr  error
	debWorkDir   string
)

// TestMain removes the shared package build after every test in this package has
// finished. A per-test cleanup would delete the payload while a later test still
// needs to read it.
func TestMain(m *testing.M) {
	code := m.Run()
	if debWorkDir != "" {
		if err := os.RemoveAll(debWorkDir); err != nil {
			os.Stderr.WriteString("cannot remove " + debWorkDir + ": " + err.Error() + "\n")
		}
	}
	os.Exit(code)
}

// buildDebPackages builds the three packages once and returns them keyed by
// role. Throwaway TLS material is generated so the test never depends on
// developer certificates or on a site configuration.
func buildDebPackages(t *testing.T) map[string]*debPackage {
	t.Helper()
	if _, err := exec.LookPath("dpkg-deb"); err != nil {
		t.Skip("dpkg-deb is not available")
	}
	if _, err := exec.LookPath("openssl"); err != nil {
		t.Skip("openssl is not available")
	}
	debBuildOnce.Do(func() {
		debBuilt, debBuildErr = buildDebPackagesOnce()
	})
	if debBuildErr != nil {
		t.Fatalf("cannot build the packages: %v", debBuildErr)
	}
	return debBuilt
}

// buildDebPackagesOnce performs the actual build into a temporary directory
// under the project's .tmp folder, so the artifacts stay inside the workspace
// and are removed by TestMain.
func buildDebPackagesOnce() (map[string]*debPackage, error) {
	root, err := filepath.Abs("../..")
	if err != nil {
		return nil, err
	}
	tmpRoot := filepath.Join(root, ".tmp")
	if err := os.MkdirAll(tmpRoot, 0o755); err != nil {
		return nil, err
	}
	work, err := os.MkdirTemp(tmpRoot, "deb-test-")
	if err != nil {
		return nil, err
	}
	debWorkDir = work
	certs := filepath.Join(work, "certs")
	if err := os.MkdirAll(certs, 0o755); err != nil {
		return nil, err
	}
	if err := generateTestCertificate(certs); err != nil {
		return nil, err
	}

	dest := filepath.Join(work, "deb")
	if err := os.MkdirAll(dest, 0o755); err != nil {
		return nil, err
	}

	// The endpoint package is built from a site configuration that omits the
	// allowlist key, because that is what a real deployment supplies: a site file
	// replaces the example template wholesale and carries only the values the
	// operator set. Building from the example template would hide the defect this
	// test exists to catch, since the template already names the allowlist.
	siteConfig, err := writeSiteConfig(work)
	if err != nil {
		return nil, err
	}

	packages := make(map[string]*debPackage, 3)
	for _, role := range []string{"node", "server", "endpoint"} {
		args := []string{
			filepath.Join(root, "scripts", "make-deb.sh"),
			"--role", role,
			"--dest", dest,
			"--version", "0.0.0-test",
			"--revision", "1",
		}
		if role != "node" {
			args = append(args,
				"--cert", filepath.Join(certs, "node.pem"),
				"--key", filepath.Join(certs, "node-key.pem"),
				"--ca", filepath.Join(certs, "ca.pem"),
			)
		}
		if role == "endpoint" {
			args = append(args, "--config", siteConfig)
		}
		command := exec.Command("bash", args...)
		command.Dir = root
		if output, err := command.CombinedOutput(); err != nil {
			return nil, &debBuildFailure{role: role, err: err, output: string(output)}
		}
		pkg, err := readDebPackage(dest, role)
		if err != nil {
			return nil, err
		}
		packages[role] = pkg
	}
	return packages, nil
}

// writeSiteConfig writes an endpoint site configuration that omits the allowlist
// key, mirroring what a real deployment supplies. Every other value is a
// placeholder the packaging script accepts.
func writeSiteConfig(work string) (string, error) {
	body := strings.Join([]string{
		"ROLE=endpoint",
		"ENDPOINT_ID=deb-test",
		"INSTANCE_ID=deb-test-1",
		"CHANNEL_ADDRESS=wss://127.0.0.1:53943",
		"AUTH_TOKEN=deb-test-token",
		"SERVER_API_URL=http://127.0.0.1:53680",
		"STOP_TIMEOUT_SECONDS=5",
		"LOG_MAX_SIZE_MB=100",
		"LOG_BACKUPS=10",
		"LOG_MAX_AGE_DAYS=30",
		"LOG_OUTPUT=file",
		"",
	}, "\n")
	path := filepath.Join(work, "site.endpoint.conf")
	if err := os.WriteFile(path, []byte(body), 0o644); err != nil {
		return "", err
	}
	return path, nil
}

// debBuildFailure reports which package failed and what the builder printed.
type debBuildFailure struct {
	role   string
	err    error
	output string
}

// Error renders the builder failure with its captured output.
func (f *debBuildFailure) Error() string {
	return "building the " + f.role + " package: " + f.err.Error() + "\n" + f.output
}

// generateTestCertificate writes a self-signed certificate, its key and a CA
// into dir. The packaging script only requires the files to exist and be
// readable, so one self-signed pair serves as both leaf and CA.
func generateTestCertificate(dir string) error {
	command := exec.Command("openssl", "req", "-x509", "-newkey", "rsa:2048",
		"-nodes", "-days", "1", "-subj", "/CN=agent-cluster-test",
		"-keyout", filepath.Join(dir, "node-key.pem"),
		"-out", filepath.Join(dir, "node.pem"))
	if output, err := command.CombinedOutput(); err != nil {
		return &debBuildFailure{role: "certificate", err: err, output: string(output)}
	}
	body, err := os.ReadFile(filepath.Join(dir, "node.pem"))
	if err != nil {
		return err
	}
	return os.WriteFile(filepath.Join(dir, "ca.pem"), body, 0o644)
}

// readDebPackage parses one built package into its payload and conffiles.
func readDebPackage(dest, role string) (*debPackage, error) {
	matches, err := filepath.Glob(filepath.Join(dest, "agent-cluster-"+role+"_*.deb"))
	if err != nil {
		return nil, err
	}
	if len(matches) != 1 {
		return nil, &debBuildFailure{role: role, err: err, output: "expected exactly one package, found " + strings.Join(matches, ", ")}
	}
	pkg := &debPackage{path: matches[0], entries: map[string]debEntry{}}

	contents, err := exec.Command("dpkg-deb", "-c", pkg.path).Output()
	if err != nil {
		return nil, err
	}
	for _, line := range strings.Split(string(contents), "\n") {
		fields := strings.Fields(line)
		if len(fields) < 6 {
			continue
		}
		// dpkg-deb prints a directory with a trailing slash, so the key is
		// normalised to the bare path. Without this a directory entry never
		// matches a path written without the slash.
		entry := debEntry{path: strings.TrimSuffix(fields[5], "/")}
		// The first field is the permission string, such as "drwxr-x---" for a
		// directory or "-rw-r-----" for a file. The leading character is the
		// entry type, so the mode is the remaining nine characters.
		if len(fields[0]) == 10 {
			entry.mode = fields[0][1:]
		}
		// A symlink line ends with "path -> target".
		if len(fields) >= 8 && fields[6] == "->" {
			entry.target = fields[7]
		}
		pkg.entries[entry.path] = entry
	}

	control, err := exec.Command("dpkg-deb", "--ctrl-tarfile", pkg.path).Output()
	if err != nil {
		return nil, err
	}
	pkg.conffiles = readConffiles(control)

	// The version and dependency fields are read separately because the epoch
	// only exists in the control metadata, never in the file name.
	fields, err := exec.Command("dpkg-deb", "-f", pkg.path, "Version", "Depends").Output()
	if err != nil {
		return nil, err
	}
	for _, line := range strings.Split(string(fields), "\n") {
		switch {
		case strings.HasPrefix(line, "Version:"):
			pkg.version = strings.TrimSpace(strings.TrimPrefix(line, "Version:"))
		case strings.HasPrefix(line, "Depends:"):
			pkg.depends = strings.TrimSpace(strings.TrimPrefix(line, "Depends:"))
		}
	}
	return pkg, nil
}

// readConffiles extracts the conffiles control file from a control tar stream.
// conffiles is a separate control file rather than a control field, so
// dpkg-deb -f cannot report it.
func readConffiles(control []byte) []string {
	command := exec.Command("tar", "-xO", "./conffiles")
	command.Stdin = strings.NewReader(string(control))
	output, err := command.Output()
	if err != nil {
		// A package without conffiles has no such member, which is not a failure.
		return nil
	}
	var paths []string
	for _, line := range strings.Split(string(output), "\n") {
		if fields := strings.Fields(line); len(fields) > 0 {
			paths = append(paths, fields[0])
		}
	}
	return paths
}

// readPackagedFile returns one file from a package payload.
func readPackagedFile(t *testing.T, pkg *debPackage, path string) string {
	t.Helper()
	fsys, err := exec.Command("dpkg-deb", "--fsys-tarfile", pkg.path).Output()
	if err != nil {
		t.Fatalf("cannot read the payload of %s: %v", pkg.path, err)
	}
	command := exec.Command("tar", "-xO", path)
	command.Stdin = strings.NewReader(string(fsys))
	output, err := command.Output()
	if err != nil {
		t.Fatalf("cannot extract %s from %s: %v", path, pkg.path, err)
	}
	return string(output)
}

// TestDebPackagesKeepTheOptLayout proves every package puts the program under
// /opt/agent-cluster and exposes entry points as symlinks in /usr/local/sbin,
// with no leftover path from the earlier scattered layout.
//
// The node package ships the controller rather than a role binary, because it is
// the dependency both role packages install. Its entry points are the controller
// and the configuration helper.
func TestDebPackagesKeepTheOptLayout(t *testing.T) {
	packages := buildDebPackages(t)

	// Each package's real payload files and the entry points that reach them.
	want := map[string]map[string]string{
		"node": {
			debOptDir + "/agent-clusterctl":             debSbinDir + "/agent-clusterctl",
			debOptDir + "/bin/agent-cluster-node-setup": debSbinDir + "/agent-cluster-node-setup",
		},
		"server": {
			debOptDir + "/bin/agent-cluster-server": debSbinDir + "/agent-cluster-server",
		},
		"endpoint": {
			debOptDir + "/bin/agent-cluster-endpoint": debSbinDir + "/agent-cluster-endpoint",
			debOptDir + "/bin/agent-cluster-cli":      debSbinDir + "/agent-cluster-cli",
		},
	}

	for role, files := range want {
		role := role
		files := files
		t.Run(role, func(t *testing.T) {
			pkg := packages[role]
			for realPath, entryPoint := range files {
				entry, ok := pkg.entries[realPath]
				if !ok {
					t.Fatalf("missing %s in the %s payload", realPath, role)
				}
				if entry.target != "" {
					t.Fatalf("%s must be a real file, not a symlink to %s", realPath, entry.target)
				}

				entry, ok = pkg.entries[entryPoint]
				if !ok {
					t.Fatalf("missing the entry point %s", entryPoint)
				}
				if entry.target != "/opt/agent-cluster"+strings.TrimPrefix(realPath, debOptDir) {
					t.Fatalf("%s points at %q, want the payload file %s", entryPoint, entry.target, realPath)
				}
			}

			// No path from the earlier scattered layout may survive.
			for path := range pkg.entries {
				if strings.HasPrefix(path, "./usr/lib/agent-cluster") ||
					path == "./usr/sbin/agent-cluster-node-setup" {
					t.Fatalf("the %s package still ships the superseded path %s", role, path)
				}
			}
		})
	}
}

// TestDebRolePackagesExposeTheLayoutDirs proves the role packages carry the five
// real directories that make /opt/agent-cluster show configuration, TLS material,
// state, logs and pid files, and that none of them is a symlink into the Debian
// policy locations. The node package deliberately omits them: it ships the
// controller without a role, so a conf/ directory would imply a role that is not
// installed.
func TestDebRolePackagesExposeTheLayoutDirs(t *testing.T) {
	packages := buildDebPackages(t)

	for _, role := range []string{"server", "endpoint"} {
		pkg := packages[role]
		for path, want := range debLayoutDirs {
			entry, ok := pkg.entries[path]
			if !ok {
				t.Fatalf("the %s package is missing the layout directory %s", role, path)
			}
			if entry.target != "" {
				t.Fatalf("%s must be a real directory, not a symlink to %s", path, entry.target)
			}
			if entry.mode != want {
				t.Fatalf("%s has mode %q, want %q", path, entry.mode, want)
			}
		}
	}

	node := packages["node"]
	for path := range debLayoutDirs {
		if entry, ok := node.entries[path]; ok {
			t.Fatalf("the node package must not ship %s (it implies a role), found %q", path, entry.target)
		}
	}
}

// TestDebEndpointShipsTheCliAliases proves the endpoint package exposes the
// operator CLI under its native name and both product-facing aliases, and that
// neither alias is a second copy of the binary.
func TestDebEndpointShipsTheCliAliases(t *testing.T) {
	pkg := buildDebPackages(t)["endpoint"]

	cli := debOptDir + "/bin/agent-cluster-cli"
	if entry, ok := pkg.entries[cli]; !ok || entry.target != "" {
		t.Fatalf("%s must be a real file in the endpoint payload", cli)
	}

	want := map[string]string{
		debSbinDir + "/agent-cluster-cli":       "/opt/agent-cluster/bin/agent-cluster-cli",
		debSbinDir + "/topsailai_agent_cluster": "agent-cluster-cli",
		debSbinDir + "/topsailai2":              "agent-cluster-cli",
	}
	for path, target := range want {
		entry, ok := pkg.entries[path]
		if !ok {
			t.Fatalf("missing the CLI entry point %s", path)
		}
		if entry.target != target {
			t.Fatalf("%s points at %q, want %q", path, entry.target, target)
		}
	}
}

// TestDebPackagedConfigReferencesEveryShippedConffile proves the packaged
// configuration names every conffile the package installs.
//
// This is the invariant behind a real defect: the endpoint package shipped
// command-allowlist.conf while the packaged configuration never referenced it,
// because a site configuration replaces the template wholesale and did not carry
// the key. An empty allowlist path makes the Endpoint skip loading the allowlist
// entirely, which permits every command instead of failing closed. The payload
// looked correct, so only the runtime reported it. Asserting the reference here
// catches the regression without needing a root install.
func TestDebPackagedConfigReferencesEveryShippedConffile(t *testing.T) {
	packages := buildDebPackages(t)

	for _, role := range []string{"server", "endpoint"} {
		pkg := packages[role]
		config := readPackagedFile(t, pkg, "./opt/agent-cluster/conf/node.conf")

		if len(pkg.conffiles) == 0 {
			t.Fatalf("the %s package declares no conffiles", role)
		}
		for _, conffile := range pkg.conffiles {
			base := filepath.Base(conffile)
			if base == "node.conf" {
				continue
			}
			if !strings.Contains(config, base) {
				t.Fatalf("the %s package ships the conffile %s but node.conf never references it;\n"+
					"an unreferenced allowlist makes the Endpoint permit every command",
					role, conffile)
			}
		}
	}
}

// TestDebPackagedConfigUsesRelativePaths proves the packaged configuration
// resolves through the layout directories instead of hardcoding absolute policy
// locations. Relative paths are what let a bundle and a package share one
// configuration shape, and they keep working when the payload directory moves.
func TestDebPackagedConfigUsesRelativePaths(t *testing.T) {
	packages := buildDebPackages(t)

	for _, role := range []string{"server", "endpoint"} {
		config := readPackagedFile(t, packages[role], "./opt/agent-cluster/conf/node.conf")
		for _, absolute := range []string{
			"/etc/agent-cluster/",
			"/var/lib/agent-cluster/",
			"/var/log/agent-cluster/",
			"/run/agent-cluster/",
		} {
			if strings.Contains(config, absolute) {
				t.Fatalf("the %s node.conf hardcodes %s; it must use a relative path that "+
					"resolves through the /opt layout", role, absolute)
			}
		}
	}
}

// TestDebPackagesCarryAMonotonicEpoch proves every package carries a Debian
// epoch in its control Version field. Without an epoch, a tag-derived version
// such as 1.0.0+2304+g8d653f5d sorts BELOW the hash-derived versions that were
// installed before this convention (4e160caf-4), so dpkg reports a downgrade
// and an operator cannot tell an upgrade from a rollback. The epoch is the only
// component that outranks every earlier scheme, so it must be present and it
// must be identical across the three packages that depend on each other.
func TestDebPackagesCarryAMonotonicEpoch(t *testing.T) {
	packages := buildDebPackages(t)

	var epoch string
	for _, role := range []string{"node", "server", "endpoint"} {
		pkg := packages[role]
		if pkg.version == "" {
			t.Fatalf("the %s package reports no Version field", role)
		}
		index := strings.Index(pkg.version, ":")
		if index <= 0 {
			t.Fatalf("the %s package version %q carries no Debian epoch; a tag-derived "+
				"version sorts below the hash-derived versions already installed, so dpkg "+
				"reports a downgrade", role, pkg.version)
		}
		current := pkg.version[:index]
		if epoch == "" {
			epoch = current
			continue
		}
		if current != epoch {
			t.Fatalf("the %s package epoch %q differs from %q; the role packages pin the "+
				"node version exactly, so a differing epoch makes the dependency "+
				"unsatisfiable", role, current, epoch)
		}
	}

	// The epoch must stay out of the file name: a colon in a path breaks scp and
	// several artifact steps, even though dpkg reads the epoch from the package.
	for _, role := range []string{"node", "server", "endpoint"} {
		if strings.Contains(filepath.Base(packages[role].path), ":") {
			t.Fatalf("the %s package file name %q contains a colon; the epoch belongs in "+
				"the control Version field only", role, filepath.Base(packages[role].path))
		}
	}

	// A role package pins the node version exactly, so the pin must carry the
	// same epoch. A pin without the epoch never matches the installed node
	// package and dpkg refuses the install.
	for _, role := range []string{"server", "endpoint"} {
		pin := "agent-cluster-node (= " + epoch + ":"
		if !strings.Contains(packages[role].depends, pin) {
			t.Fatalf("the %s package Depends %q does not pin the node version with the "+
				"epoch (%q); the pin would never match the installed node package",
				role, packages[role].depends, pin)
		}
	}
}
