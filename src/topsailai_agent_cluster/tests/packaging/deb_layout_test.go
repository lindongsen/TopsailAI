package packaging_test

import (
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
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

// debTestSite is the site identifier the test builds config packages with. A
// config package name carries it, so two sites produce distinguishable
// artifacts instead of two packages that differ only in content.
const debTestSite = "test-site"

// debTestVersion is the release version every packaging test builds with. It is
// deliberately not a release number: a test that pinned the current release
// would fail on every version bump for a reason unrelated to packaging, and it
// would also hide a real defect, because a hardcoded expectation passes whether
// or not the build actually used the version it was given. The Provider version
// is injected from this value, so the assertion that reads it back proves the
// injection reached the binary.
const debTestVersion = "0.0.0-test"

// debMinEpoch is the lowest Debian epoch a package may carry. It is a floor
// rather than an exact value because the epoch is a one-way ratchet: a future
// scheme may raise it again, and this test must not have to change for that.
// It must never be lowered, because a lower epoch sorts below what is already
// installed and dpkg then reports a downgrade.
const debMinEpoch = 2

// debLayoutDirs is the real directory set that makes one directory show the
// whole product, with the permission string dpkg-deb reports. A symlink here
// would silently redirect a write to whatever filesystem the link names, which
// is how a state directory ends up on a full root filesystem while the operator
// believes it lives under /opt.
var debLayoutDirs = map[string]string{
	debOptDir + "/conf":           "rwxr-xr-x",
	debOptDir + "/certs":          "rwxr-xr-x",
	debOptDir + "/data":           "rwxr-x---",
	debOptDir + "/logs":           "rwxr-x---",
	debOptDir + "/run":            "rwxr-xr-x",
	debOptDir + "/conf/server":    "rwxr-xr-x",
	debOptDir + "/conf/endpoint":  "rwxr-xr-x",
	debOptDir + "/certs/server":   "rwxr-xr-x",
	debOptDir + "/certs/endpoint": "rwxr-xr-x",
	debOptDir + "/data/server":    "rwxr-x---",
	debOptDir + "/data/endpoint":  "rwxr-x---",
	debOptDir + "/logs/server":    "rwxr-x---",
	debOptDir + "/logs/endpoint":  "rwxr-x---",
	debOptDir + "/run/server":     "rwxr-xr-x",
	debOptDir + "/run/endpoint":   "rwxr-xr-x",
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
	provides  string
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

	// The staging tree is kept outside the output directory, mirroring the
	// Makefile default. Passing it explicitly also proves the builder honours
	// --build-dir instead of writing into the project .tmp tree.
	buildDir := filepath.Join(work, "build")
	if err := os.MkdirAll(buildDir, 0o755); err != nil {
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

	packages := make(map[string]*debPackage, 5)
	// The binary packages carry no site data, so they are built without a
	// configuration or certificate. The config packages carry both, so they are
	// built with the throwaway material and the site configuration.
	//
	// A config package name carries the site identifier, so the build needs one.
	// The test uses a single site, which is enough to prove the suffix reaches
	// the package name and the virtual name stays stable.
	builds := []struct {
		key          string
		role         string
		configRole   string
		providerType string
		site         string
	}{
		{key: "node", role: "node"},
		{key: "server", role: "server"},
		{key: "endpoint", role: "endpoint"},
		{key: "config-server", role: "config", configRole: "server", site: debTestSite},
		{key: "config-endpoint", role: "config", configRole: "endpoint", site: debTestSite},
		// The Provider CLI package is built here so the layout assertions below
		// cover it. It is a standalone executable, so it is built without a
		// certificate and without a site configuration.
		{key: "provider-topsailai", role: "provider", providerType: "topsailai"},
	}
	for _, build := range builds {
		args := []string{
			filepath.Join(root, "scripts", "make-deb.sh"),
			"--role", build.role,
			"--dest", dest,
			"--build-dir", buildDir,
			"--version", debTestVersion,
			"--revision", "1",
		}
		if build.configRole != "" {
			args = append(args, "--config-role", build.configRole)
		}
		if build.providerType != "" {
			args = append(args, "--provider-type", build.providerType)
		}
		if build.site != "" {
			args = append(args, "--site", build.site)
		}
		// Only the role and config packages carry a TLS identity. The node
		// package ships the controller and the Provider package ships a
		// standalone executable, so neither needs a certificate.
		if build.role == "server" || build.role == "endpoint" || build.role == "config" {
			args = append(args,
				"--cert", filepath.Join(certs, "node.pem"),
				"--key", filepath.Join(certs, "node-key.pem"),
				"--ca", filepath.Join(certs, "ca.pem"),
			)
		}
		if build.configRole == "endpoint" {
			args = append(args, "--config", siteConfig)
		}
		command := exec.Command("bash", args...)
		command.Dir = root
		if output, err := command.CombinedOutput(); err != nil {
			return nil, &debBuildFailure{role: build.key, err: err, output: string(output)}
		}
		pkg, err := readDebPackage(dest, build.key, build.site)
		if err != nil {
			return nil, err
		}
		packages[build.key] = pkg
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

// readDebPackage parses one built package into its payload and conffiles. A
// config package name carries the site suffix, so the site is part of the glob;
// an empty site matches the binary packages, whose names carry no suffix.
func readDebPackage(dest, role, site string) (*debPackage, error) {
	name := "agent-cluster-" + role
	if site != "" {
		name += "-" + site
	}
	matches, err := filepath.Glob(filepath.Join(dest, name+"_*.deb"))
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

	// The version, dependency and virtual-name fields are read separately
	// because the epoch only exists in the control metadata, never in the file
	// name.
	fields, err := exec.Command("dpkg-deb", "-f", pkg.path, "Version", "Depends", "Provides").Output()
	if err != nil {
		return nil, err
	}
	for _, line := range strings.Split(string(fields), "\n") {
		switch {
		case strings.HasPrefix(line, "Version:"):
			pkg.version = strings.TrimSpace(strings.TrimPrefix(line, "Version:"))
		case strings.HasPrefix(line, "Depends:"):
			pkg.depends = strings.TrimSpace(strings.TrimPrefix(line, "Depends:"))
		case strings.HasPrefix(line, "Provides:"):
			pkg.provides = strings.TrimSpace(strings.TrimPrefix(line, "Provides:"))
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
			if strings.Contains(path, "/server") || strings.Contains(path, "/endpoint") {
				if !strings.Contains(path, "/"+role) {
					continue
				}
			}
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
// configuration names every conffile the config package installs.
//
// This is the invariant behind a real defect: the endpoint package shipped
// command-allowlist.conf while the packaged configuration never referenced it,
// because a site configuration replaces the template wholesale and did not carry
// the key. An empty allowlist path makes the Endpoint skip loading the allowlist
// entirely, which permits every command instead of failing closed. The payload
// looked correct, so only the runtime reported it. Asserting the reference here
// catches the regression without needing a root install.
//
// The TLS material is deliberately exempt. It is a conffile so an upgrade keeps
// the site identity, but it is not a policy path: the controller supplies a
// default for each of the three files (scripts/agent-clusterctl), and a missing
// file aborts the launch instead of widening access. A site configuration that
// omits the keys therefore still resolves the shipped material, so requiring an
// explicit reference would assert a rule the runtime does not have.
func TestDebPackagedConfigReferencesEveryShippedConffile(t *testing.T) {
	packages := buildDebPackages(t)

	// The TLS material is registered as a conffile but is not a policy path, so
	// it is exempt from the reference rule for the reason stated above.
	exempt := map[string]bool{
		"node.conf":    true,
		"ca.pem":       true,
		"node.pem":     true,
		"node-key.pem": true,
	}

	for _, role := range []string{"config-server", "config-endpoint"} {
		pkg := packages[role]
		configRole := strings.TrimPrefix(role, "config-")
		config := readPackagedFile(t, pkg, "./opt/agent-cluster/conf/"+configRole+"/node.conf")

		if len(pkg.conffiles) == 0 {
			t.Fatalf("the %s package declares no conffiles", role)
		}
		for _, conffile := range pkg.conffiles {
			base := filepath.Base(conffile)
			if exempt[base] {
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

// TestDebRegistersTLSMaterialAsConffiles proves the TLS material survives an
// upgrade.
//
// This guards a real defect: the packages shipped ca.pem, node.pem and
// node-key.pem without registering them as conffiles, so dpkg replaced them on
// every upgrade. A site replaces the shipped development certificate with its own
// identity, and the certificate subject is what names the node to its peer. The
// overwrite therefore reverted the certificate to the build host's name while
// node.conf kept the site ENDPOINT_ID, so the hello identity disagreed with the
// certificate and the Server rejected the connection. The symptom was a
// reconnect loop that looked like a network fault, and nothing in the payload
// revealed it. Registering the material keeps the operator's copy in force and
// leaves the shipped copy as a .dpkg-dist file to compare against.
func TestDebRegistersTLSMaterialAsConffiles(t *testing.T) {
	packages := buildDebPackages(t)

	for _, role := range []string{"config-server", "config-endpoint"} {
		pkg := packages[role]
		configRole := strings.TrimPrefix(role, "config-")
		want := []string{
			"/opt/agent-cluster/certs/" + configRole + "/ca.pem",
			"/opt/agent-cluster/certs/" + configRole + "/node.pem",
			"/opt/agent-cluster/certs/" + configRole + "/node-key.pem",
		}
		registered := make(map[string]bool, len(pkg.conffiles))
		for _, conffile := range pkg.conffiles {
			registered[conffile] = true
		}
		for _, path := range want {
			if !registered[path] {
				t.Fatalf("the %s package ships %s but does not register it as a conffile;\n"+
					"an upgrade then overwrites the site certificate and the node identity "+
					"silently reverts to the build host", role, path)
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

	for _, role := range []string{"config-server", "config-endpoint"} {
		configRole := strings.TrimPrefix(role, "config-")
		config := readPackagedFile(t, packages[role], "./opt/agent-cluster/conf/"+configRole+"/node.conf")
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
// must be identical across every package that depends on another.
func TestDebPackagesCarryAMonotonicEpoch(t *testing.T) {
	packages := buildDebPackages(t)

	var epoch string
	for _, role := range []string{"node", "server", "endpoint", "config-server", "config-endpoint"} {
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

	// The epoch is a one-way ratchet. It was raised to 2 because the fleet had
	// been deployed at 1:2.0.0-1 and the next release was numbered 1.3.0, so
	// every install printed a downgrade warning while succeeding. Lowering it
	// again would reintroduce exactly that, and the warning would then hide a
	// real downgrade instead of being noise. Asserting a floor rather than the
	// exact value lets a future scheme raise it again without editing this test.
	//
	// Compared as integers, not as strings: "10" sorts below "2" lexically, so a
	// string comparison would reject a legitimately raised epoch.
	epochNumber, err := strconv.Atoi(epoch)
	if err != nil {
		t.Fatalf("the package epoch %q is not a number: %v", epoch, err)
	}
	if epochNumber < debMinEpoch {
		t.Fatalf("the package epoch is %d, below the required floor %d; lowering the "+
			"epoch makes every package sort below what is already installed, so dpkg "+
			"reports a downgrade and an operator cannot tell an upgrade from a rollback",
			epochNumber, debMinEpoch)
	}

	// The epoch must stay out of the file name: a colon in a path breaks scp and
	// several artifact steps, even though dpkg reads the epoch from the package.
	for _, role := range []string{"node", "server", "endpoint", "config-server", "config-endpoint"} {
		if strings.Contains(filepath.Base(packages[role].path), ":") {
			t.Fatalf("the %s package file name %q contains a colon; the epoch belongs in "+
				"the control Version field only", role, filepath.Base(packages[role].path))
		}
	}

	// Every package that depends on the node package must declare the same
	// compatibility window, and the window must carry the epoch. A bound without
	// the epoch never matches the installed node package and dpkg refuses the
	// install. The config packages depend on it too, so they belong in this check
	// rather than only the binary packages.
	//
	// The dependency is a window rather than an exact pin so a patch release
	// installs alone. Asserting the window here is what keeps that property from
	// silently reverting to `=`: an exact pin still satisfies a "names the node
	// package" check, so a weaker assertion would not notice.
	floor, ceiling := debCompatWindow(t, epoch)
	for _, role := range []string{"server", "endpoint", "config-server", "config-endpoint"} {
		for _, bound := range []string{
			"agent-cluster-node (>= " + floor + ")",
			"agent-cluster-node (<< " + ceiling + ")",
		} {
			if !strings.Contains(packages[role].depends, bound) {
				t.Fatalf("the %s package Depends %q does not carry the bound %q;\n"+
					"an exact pin forces every sibling package to be rebuilt at the same "+
					"version, so a one-line patch cannot be installed alone",
					role, packages[role].depends, bound)
			}
		}
	}
}

// debCompatWindow returns the compatibility window the packages must declare for
// the node package, derived from the version the packaging tests build with.
//
// It is derived rather than hardcoded so a change to debTestVersion does not
// require editing every assertion, and so the test states the rule instead of one
// instance of it.
func debCompatWindow(t *testing.T, epoch string) (floor, ceiling string) {
	t.Helper()
	base := debTestVersion
	if index := strings.Index(base, "-"); index >= 0 {
		base = base[:index]
	}
	parts := strings.Split(base, ".")
	if len(parts) < 2 {
		t.Fatalf("the test version %q is not major.minor.patch", debTestVersion)
	}
	major, err := strconv.Atoi(parts[0])
	if err != nil {
		t.Fatalf("the test version %q has a non-numeric major: %v", debTestVersion, err)
	}
	minor, err := strconv.Atoi(parts[1])
	if err != nil {
		t.Fatalf("the test version %q has a non-numeric minor: %v", debTestVersion, err)
	}
	return fmt.Sprintf("%s:%d.%d.0", epoch, major, minor),
		fmt.Sprintf("%s:%d.%d.0", epoch, major, minor+1)
}

// TestDebConfigPackageNamesCarryTheSite proves a config package name carries the
// site identifier and still provides the unsuffixed name.
//
// This guards a real defect: every site built a package called
// agent-cluster-config-endpoint with the same version, so the three artifacts
// differed only in content. dpkg compares names and versions, so installing the
// wrong site's package was accepted silently, and dpkg -l could not show which
// site a machine carried. The suffix makes the artifact self-describing; the
// virtual name keeps the generic binary package's dependency stable, so the
// binary package still names no site.
func TestDebConfigPackageNamesCarryTheSite(t *testing.T) {
	packages := buildDebPackages(t)

	for _, role := range []string{"config-server", "config-endpoint"} {
		pkg := packages[role]
		base := "agent-cluster-" + role

		if !strings.HasPrefix(filepath.Base(pkg.path), base+"-"+debTestSite+"_") {
			t.Fatalf("the %s package file is %q, want a name starting with %q;\n"+
				"without the site suffix two sites build indistinguishable packages",
				role, filepath.Base(pkg.path), base+"-"+debTestSite+"_")
		}

		want := base + " (= " + pkg.version + ")"
		if pkg.provides != want {
			t.Fatalf("the %s package Provides %q, want %q;\n"+
				"the binary package depends on the unsuffixed name, so a missing or "+
				"differently versioned Provides makes the dependency unsatisfiable",
				role, pkg.provides, want)
		}
	}

	// The binary packages must keep depending on the unsuffixed name, so a
	// generic package never names a site. The bound is a window for the same
	// reason the node dependency is: a patch release of the binary package must
	// install without rebuilding the site config package, which carries the
	// node's identity and TLS material and is therefore the most expensive
	// artifact to rebuild.
	//
	// The epoch is read from the built node package rather than assumed, so this
	// test keeps checking the real window if the epoch is ever raised again.
	nodeVersion := packages["node"].version
	epochIndex := strings.Index(nodeVersion, ":")
	if epochIndex < 0 {
		t.Fatalf("the node package version %q carries no epoch", nodeVersion)
	}
	floor, ceiling := debCompatWindow(t, nodeVersion[:epochIndex])
	for role, name := range map[string]string{
		"endpoint": "agent-cluster-config-endpoint",
		"server":   "agent-cluster-config-server",
	} {
		for _, bound := range []string{
			name + " (>= " + floor + ")",
			name + " (<< " + ceiling + ")",
		} {
			if !strings.Contains(packages[role].depends, bound) {
				t.Fatalf("the %s package Depends %q does not carry the bound %q;\n"+
					"a generic binary package must depend on the unsuffixed config "+
					"package within the compatibility window, never on a site and never "+
					"on one exact version",
					role, packages[role].depends, bound)
			}
		}
	}
}

// TestDebLauncherForwardsTheAccessPolicyDir proves the packaged launcher passes
// the access policy directory to the Endpoint binary.
//
// This guards a real defect: the launcher forwarded the command allowlist and the
// control action catalog but never the access policy directory, so a node
// deployed from a package and started through the launcher served every caller
// while node.conf named the directory. The failure is silent and asymmetric: the
// allowlist and the catalog are fail-closed when absent, so their omission
// disables a capability, while an absent policy directory is permissive, so its
// omission removes the whole authorization boundary and every operation keeps
// working. Nothing in the payload reveals it, and the node looks healthy.
//
// The assertions are structural rather than a bare substring search, because a
// mention of the flag is not a forwarding site: the flag has to appear on a line
// that also names the variable, which is what makes the value reach the binary.
func TestDebLauncherForwardsTheAccessPolicyDir(t *testing.T) {
	packages := buildDebPackages(t)
	launcher := readPackagedFile(t, packages["node"], debOptDir+"/agent-clusterctl")

	// The value has to be resolved from the configuration, otherwise the flag
	// below would forward an empty string and the node stays permissive.
	if !hasLineContaining(launcher, "ENDPOINT_ACCESS_POLICY_DIR=$(resolve_path") {
		t.Fatalf("the packaged launcher never resolves ENDPOINT_ACCESS_POLICY_DIR;\n" +
			"a node that names the directory in node.conf would still start permissive")
	}

	// The forwarding site: one line naming both the flag and the variable.
	if !hasLineContaining(launcher, "--endpoint-access-policy-dir", "ENDPOINT_ACCESS_POLICY_DIR") {
		t.Fatalf("the packaged launcher never forwards --endpoint-access-policy-dir;\n" +
			"an Endpoint with no policy directory permits every caller, so the node " +
			"would lose its authorization boundary while every other capability works")
	}

	// doctor has to show the permissive state, because an operator cannot
	// otherwise tell a node with a policy directory from one without.
	if !hasLineContaining(launcher, "policy     :", "ENDPOINT_ACCESS_POLICY_DIR") {
		t.Fatalf("the packaged launcher doctor output never reports the policy directory;\n" +
			"an absent directory is permissive, so the operator cannot see that the " +
			"authorization boundary is missing")
	}
}

// TestDebLauncherForwardsServerEndpointExpiry proves the packaged launcher
// passes the configured offline-record retention window to the Server binary.
func TestDebLauncherForwardsServerEndpointExpiry(t *testing.T) {
	packages := buildDebPackages(t)
	launcher := readPackagedFile(t, packages["node"], debOptDir+"/agent-clusterctl")
	if !hasLineContaining(launcher, "--endpoint-expiry", "ENDPOINT_EXPIRY") {
		t.Fatal("the packaged launcher never forwards ENDPOINT_EXPIRY to --endpoint-expiry")
	}
}

// TestDebLauncherForwardsEndpointSourceCacheExpiry proves the packaged launcher
// exports the configured cache retention to the Endpoint process.
func TestDebLauncherForwardsEndpointSourceCacheExpiry(t *testing.T) {
	packages := buildDebPackages(t)
	launcher := readPackagedFile(t, packages["node"], debOptDir+"/agent-clusterctl")
	if !hasLineContaining(launcher, "AGENT_CLUSTER_ENDPOINT_SOURCE_CACHE_EXPIRY", "SOURCE_CACHE_EXPIRY") {
		t.Fatal("the packaged launcher never exports SOURCE_CACHE_EXPIRY to the Endpoint")
	}
}

// TestDebLauncherResolvesTheProviderCatalogPath proves the packaged launcher
// resolves and exports the provider catalog path instead of leaving a relative
// value to be interpreted by whatever directory the controller was invoked from.
//
// This guards the fourth instance of one defect class. The launcher was extended
// key by key, so a new setting landed in the binary, the documentation and the
// shipped template while the launcher never learned it: first the command
// allowlist, then the catalog, then the access policy directory, and now the
// catalog path again. Each omission is invisible in the payload, because the
// template looks correct and the binary reads the variable it is given.
//
// The failure direction here is worse than a lost capability. The Provider exits
// when it cannot read the file it was told to use, and the Endpoint refuses to
// start when the Provider cannot describe itself, so an unresolved relative path
// is a node that never comes up rather than a node that serves fewer commands.
// The Endpoint never reads this file and no flag carries it, so the process
// environment is the only path the value can travel.
//
// The assertions are structural rather than a bare substring search: the
// variable has to appear on a line that also resolves, exports or prints it,
// which is what makes the value reach the Provider.
func TestDebLauncherResolvesTheProviderCatalogPath(t *testing.T) {
	packages := buildDebPackages(t)
	launcher := readPackagedFile(t, packages["node"], debOptDir+"/agent-clusterctl")

	// Resolution: without it the exported value stays relative and the Provider
	// resolves it against the controller's working directory.
	if !hasLineContaining(launcher, "AGENT_CLUSTER_TOPSAILAI_CONTROL_ACTIONS=$(resolve_path") {
		t.Fatalf("the packaged launcher never resolves AGENT_CLUSTER_TOPSAILAI_CONTROL_ACTIONS;\n" +
			"a relative catalog path would be resolved against the directory the " +
			"controller was invoked from, and the Provider exits when it cannot read it")
	}

	// Forwarding: the Provider inherits this process environment, so an
	// unexported value never reaches it.
	if !hasLineContaining(launcher, "export AGENT_CLUSTER_TOPSAILAI_CONTROL_ACTIONS") {
		t.Fatalf("the packaged launcher never exports AGENT_CLUSTER_TOPSAILAI_CONTROL_ACTIONS;\n" +
			"the Provider CLI inherits this environment, so the catalog would never " +
			"be read and every ctl. capability would be dropped")
	}

	// Visibility: an operator has to see the resolved value before starting the
	// node, because a wrong value is a failed launch rather than a degraded one.
	if !hasLineContaining(launcher, "catalog    :", "AGENT_CLUSTER_TOPSAILAI_CONTROL_ACTIONS") {
		t.Fatalf("the packaged launcher doctor output never reports the provider catalog path;\n" +
			"an unresolved value stops the node from starting, so the operator cannot " +
			"diagnose it from the payload")
	}
}

// TestCLIEnvWriterUsesExplicitServerTokenName prevents the generated per-user
// configuration from collapsing the two independent credentials back into one
// ambiguous CLI token. The writer is shared by bundle and Debian installation,
// so one source assertion protects both deployment paths without running either
// privileged installer.
func TestCLIEnvWriterUsesExplicitServerTokenName(t *testing.T) {
	root, err := filepath.Abs("../..")
	if err != nil {
		t.Fatalf("resolve project root: %v", err)
	}
	path := filepath.Join(root, "scripts", "lib", "cli-env.sh")
	content, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("read CLI environment writer: %v", err)
	}
	writer := string(content)
	if !hasLineContaining(writer, "echo", "AGENT_CLUSTER_CLI_SERVER_TOKEN=") {
		t.Fatal("CLI environment writer does not emit AGENT_CLUSTER_CLI_SERVER_TOKEN")
	}
	for _, deprecated := range []string{"AGENT_CLUSTER_CLI_TOKEN=", "AGENT_CLUSTER_TOKEN="} {
		if hasLineContaining(writer, "echo", deprecated) {
			t.Fatalf("CLI environment writer still emits deprecated name %s", deprecated)
		}
	}
}

// hasLineContaining reports whether some line of text contains every one of the
// given substrings. A line-scoped check is what distinguishes a forwarding site
// from an unrelated mention of the same name elsewhere in the script.
func hasLineContaining(text string, substrings ...string) bool {
	for _, line := range strings.Split(text, "\n") {
		matched := true
		for _, substring := range substrings {
			if !strings.Contains(line, substring) {
				matched = false
				break
			}
		}
		if matched {
			return true
		}
	}
	return false
}

// postinstSedExpression extracts the sed substitution expression a maintainer
// script uses to read one manifest field.
//
// The expression is taken from the script rather than rebuilt here, because the
// defect this guards against is a reader that disagrees with the writer. A
// rebuilt expression would test the test instead of the script.
//
// Only the line that reads MANIFEST is considered. The same field is also read
// from the describe response, which is compact JSON with no space after the
// colon, so a reader for that document is correct without whitespace tolerance
// and must not be mistaken for the manifest reader.
func postinstSedExpression(t *testing.T, postinst, field string) string {
	t.Helper()

	for _, line := range strings.Split(postinst, "\n") {
		if !strings.Contains(line, `"`+field+`"`) || !strings.Contains(line, "sed -n") {
			continue
		}
		if !strings.Contains(line, "${MANIFEST}") {
			continue
		}
		start := strings.Index(line, "'s/")
		if start < 0 {
			continue
		}
		rest := line[start+1:]
		end := strings.Index(rest, "/p'")
		if end < 0 {
			continue
		}
		return rest[:end+2]
	}
	t.Fatalf("the postinst has no sed expression reading %q from MANIFEST, so the identity check cannot run", field)
	return ""
}

// TestDebLauncherPreservesLegacyBundlePathBase proves an existing bundle with
// conf/node.conf still resolves certs/, data/, logs/ and run/ from the bundle
// root. Role-scoped package configurations resolve from conf/<role>/ instead.
func TestDebLauncherPreservesLegacyBundlePathBase(t *testing.T) {
	packages := buildDebPackages(t)
	launcher := readPackagedFile(t, packages["node"], debOptDir+"/agent-clusterctl")
	if !strings.Contains(launcher, `CTL_DIR}/conf/node.conf`) {
		t.Fatal("the launcher no longer detects the legacy conf/node.conf path")
	}
	if !hasLineContaining(launcher, `CONFIG_DIR="${CTL_DIR}"`) {
		t.Fatal("the launcher no longer preserves the bundle root for legacy conf/node.conf")
	}
}
